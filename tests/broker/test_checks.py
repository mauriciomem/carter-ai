# ruff: noqa: E501
"""the broker's refuse-mode checks: repo config, SSH config, signatures."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from aplus.helpers import commit_file, git, make_repo
from broker.fakes import FakeSsh, install_fake_ssh
from carter.aplus import repocfg, run
from carter.aplus.findings import Finding
from carter.broker import checks
from carter.broker.env import Tools, child_env
from carter.identity.errors import E_B_REPOCFG, IdentityError
from carter.identity.schema import IdentityConfig

SSH_G = Path(__file__).resolve().parents[1] / "data" / "ssh_g"
ORIGIN = "git@github.com:owner/repo.git"


class World:
    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "acct"
        self.home.mkdir()
        (self.home / ".ssh").mkdir()
        self.fake: FakeSsh = install_fake_ssh(tmp / "ssh-bin")
        self.fake.link_real_tools()
        self.fake.set_ssh_g((SSH_G / "openssh-10.2-plain.txt").read_text())
        self.repo = make_repo(tmp / "repo")
        commit_file(self.repo, "seed.txt")
        git("remote", "add", "origin", ORIGIN, cwd=self.repo)
        carter = tmp / "carterhome"
        carter.mkdir()
        self.carter_gitconfig = carter / "gitconfig"
        self.carter_gitconfig.write_text("# managed by Carter\n")
        tools = Tools(git="/usr/bin/git", gh="", ssh_bin_dir=str(self.fake.bindir))
        self.ctx = checks.Context(
            cfg=IdentityConfig(),
            owned=repocfg.CarterOwned(
                include=(str(self.carter_gitconfig),),
                fragment_dir=f"{self.carter_gitconfig}.d",
                gitconfig_files=(str(self.carter_gitconfig),),
            ),
            tools=tools,
            home=self.home,
        )

    def global_config(self, text: str) -> None:
        (self.home / ".gitconfig").write_text(text)

    def vet(self) -> list[Finding]:
        env = child_env("push", {}, self.ctx.tools, self.home)
        with run.forced_env(env):
            return checks.vet(self.repo, ORIGIN, self.ctx)

    def ssh_config(self, text: str) -> None:
        (self.home / ".ssh" / "config").write_text(text)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def keys(found: list[Finding]) -> list[str]:
    return sorted(f"{f.scope}:{f.key}" for f in found)


class TestPassesTheRfcTableRows:
    def test_a_plain_repo_is_clean(self, world: World) -> None:
        assert world.vet() == []

    def test_a_global_include_path_to_carters_gitconfig_passes(self, world: World) -> None:
        world.global_config(f"[include]\n\tpath = {world.carter_gitconfig}\n")
        assert world.vet() == []

    def test_gh_auth_setup_git_credential_helper_passes(self, world: World) -> None:
        world.global_config(
            '[credential "https://github.com"]\n\thelper = !/usr/bin/gh auth git-credential\n'
        )
        assert world.vet() == []

    def test_a_global_pager_passes(self, world: World) -> None:
        world.global_config("[core]\n\tpager = delta\n[pager]\n\tdiff = delta\n")
        assert world.vet() == []

    def test_carters_hook_entries_from_carters_own_file_pass(self, world: World) -> None:
        world.carter_gitconfig.write_text(
            '[hook "carter-guard-pre-push"]\n\tcommand = /x/carter-guard pre-push\n\tevent = pre-push\n'
        )
        world.global_config(f"[include]\n\tpath = {world.carter_gitconfig}\n")
        assert world.vet() == []


class TestRefusesTheRfcTableRows:
    @pytest.mark.parametrize(
        ("where", "text", "expect"),
        [
            ("local", "[core]\n\tsshCommand = ssh -F /tmp/x\n", "local:core.sshcommand"),
            ("local", '[url "ssh://evil/"]\n\tinsteadOf = git@github.com:\n', "local:url.ssh://evil/.insteadof"),
            ("local", '[remote "origin"]\n\tpushurl = ssh://evil/x\n', "local:remote.origin.pushurl"),
            ("local", '[credential]\n\thelper = !x\n', "local:credential.helper"),
            ("local", "[include]\n\tpath = /tmp/x\n", "local:include.path"),
            ("local", "[core]\n\tfsmonitor = /tmp/fsm\n", "local:core.fsmonitor"),
            ("local", "[core]\n\thooksPath = /tmp/h\n", "local:core.hookspath"),
            ("local", "[diff]\n\texternal = /tmp/d\n", "local:diff.external"),
            ("local", '[protocol "ext"]\n\tallow = always\n', "local:protocol.ext.allow"),
            ("global", "[core]\n\tsshCommand = ssh -i /tmp/k\n", "global:core.sshcommand"),
            ("global", '[url "ssh://evil/"]\n\tinsteadOf = git@github.com:\n', "global:url.ssh://evil/.insteadof"),
            ("global", '[remote "origin"]\n\turl = x\n', "global:remote.origin.url"),
            ("global", '[protocol "ext"]\n\tallow = always\n', "global:protocol.ext.allow"),
        ],
    )  # fmt: skip
    def test_each_row_refuses_with_e_b_repocfg(
        self, world: World, where: str, text: str, expect: str
    ) -> None:
        if where == "local":
            with (world.repo / ".git" / "config").open("a") as fh:
                fh.write(text)
        else:
            world.global_config(text)
        found = world.vet()
        assert expect in keys(found)
        with pytest.raises(IdentityError) as exc:
            checks.require_clean(found)
        assert exc.value.code == E_B_REPOCFG

    def test_a_foreign_hook_file_refuses(self, world: World) -> None:
        hook = world.repo / ".git" / "hooks" / "reference-transaction"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        assert "hooks:reference-transaction" in keys(world.vet())

    def test_findings_never_hold_a_value(self, world: World) -> None:
        with (world.repo / ".git" / "config").open("a") as fh:
            fh.write("[credential]\n\thelper = !echo SECRET-VALUE-123\n")
        assert "SECRET-VALUE-123" not in repr(world.vet())

    def test_system_scope_is_never_read(self, world: World, tmp_path: Path) -> None:
        system = tmp_path / "etc-gitconfig"
        system.write_text("[core]\n\tsshCommand = evil\n")
        env = child_env("push", {}, world.ctx.tools, world.home)
        env["GIT_CONFIG_SYSTEM"] = str(system)  # git reads this as the "system" file...
        with run.forced_env(env):  # ...unless GIT_CONFIG_NOSYSTEM wins, which clean_env sets
            assert checks.vet(world.repo, ORIGIN, world.ctx) == []


class TestSshConfig:
    def test_match_exec_in_the_account_home_refuses_before_ssh_g_runs(self, world: World) -> None:
        world.ssh_config('Match exec "touch /tmp/x"\n')
        found = world.vet()
        assert keys(found) == ["ssh config:Match exec"]
        assert world.fake.calls() == []  # `ssh -G` would have run the command

    @pytest.mark.parametrize("form", ['Match !exec "x"', 'Match exec="x"', "MATCH EXEC true"])
    def test_the_two_forms_the_1g_scan_missed_are_caught(self, world: World, form: str) -> None:
        world.ssh_config(form + "\n")
        assert keys(world.vet()) == ["ssh config:Match exec"]

    def test_an_include_is_followed(self, world: World) -> None:
        (world.home / ".ssh" / "more").write_text("Match exec true\n")
        world.ssh_config("Include more\n")
        assert keys(world.vet()) == ["ssh config:Match exec"]

    def test_an_unreadable_include_refuses(self, world: World) -> None:
        target = world.home / ".ssh" / "locked"
        target.write_text("Host x\n")
        target.chmod(0)
        world.ssh_config("Include locked\n")
        try:
            if os.access(target, os.R_OK):
                pytest.skip("running as a user that ignores file modes")
            assert keys(world.vet()) == ["ssh config:Include"]
        finally:
            target.chmod(0o600)

    @pytest.mark.parametrize(
        ("fixture", "expect"),
        [
            ("proxycommand", ["ssh config:proxycommand"]),
            ("localcommand-permitted", ["ssh config:localcommand", "ssh config:permitlocalcommand"]),
            ("knownhostscommand", ["ssh config:knownhostscommand"]),
            ("permitlocalcommand-only", ["ssh config:permitlocalcommand"]),
            ("proxyjump", []),
        ],
    )  # fmt: skip
    def test_ssh_g_output_is_judged_by_the_c5_key_list(
        self, world: World, fixture: str, expect: list[str]
    ) -> None:
        world.fake.set_ssh_g((SSH_G / f"openssh-10.2-{fixture}.txt").read_text())
        assert keys(world.vet()) == expect

    def test_ssh_g_runs_from_ssh_bin_dir_for_the_push_user(self, world: World) -> None:
        world.vet()
        (call,) = world.fake.calls()
        assert call["argv"] == ["-G", "git@github.com"]

    def test_path_order_is_never_consulted(self, world: World, tmp_path: Path) -> None:
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        (decoy / "ssh").write_text("#!/bin/sh\necho proxycommand evil\n")
        (decoy / "ssh").chmod(0o755)
        env = child_env("push", {}, world.ctx.tools, world.home)
        env["PATH"] = f"{decoy}:{env['PATH']}"
        with run.forced_env(env):
            assert checks.vet(world.repo, ORIGIN, world.ctx) == []

    def test_a_missing_ssh_is_a_finding_not_a_pass(self, world: World, tmp_path: Path) -> None:
        empty = tmp_path / "no-ssh"
        empty.mkdir()
        ctx = checks.Context(
            world.ctx.cfg, world.ctx.owned, Tools("/usr/bin/git", "", str(empty)), world.home
        )
        env = child_env("push", {}, ctx.tools, world.home)
        with run.forced_env(env):
            found = checks.vet(world.repo, ORIGIN, ctx)
        assert keys(found) == ["ssh config:ssh"]


class TestForcedEnv:
    def test_read_only_git_calls_never_see_the_server_environment(
        self, world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "sentinel-pw")
        spy = tmp_path / "spy"
        spy.write_text(f'#!/bin/sh\nenv > {tmp_path}/seen\nexec /usr/bin/git "$@"\n')
        spy.chmod(0o755)
        tools = Tools(str(spy), "", str(world.fake.bindir))
        ctx = checks.Context(world.ctx.cfg, world.ctx.owned, tools, world.home)
        env = child_env("push", {}, tools, world.home)
        with run.forced_env(env):
            run.git(
                ["rev-parse", "--git-dir"], world.repo
            )  # the `carter push` runner honours the base
            assert "sentinel-pw" not in run.clean_env().values()
        del ctx
        # the subprocess itself is plain git (the spy is for the pr/push runner tests later)
        subprocess.run([str(spy), "--version"], capture_output=True, env=env)
        assert "sentinel-pw" not in (tmp_path / "seen").read_text()
