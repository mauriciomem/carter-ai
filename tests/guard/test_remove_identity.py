# ruff: noqa: E501, F811
"""Identity artifacts: removal and damage.

* ``identity remove`` and ``guard remove`` are independent: either order works and each leaves the
  other's artifacts; both together put every touched file back.
* Damage to any identity artifact never blocks the human's own ``git commit`` and ``git push``
  (real git, a ``file://`` remote, the hermetic home).
* The emergency path needs no ``carter``: delete ``~/.carter/gitconfig`` and git is as before;
  delete the shim and a T2 agent commit fails closed (it is never made unsigned).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import identity_add, identity_remove
from carter.cli import main
from carter.guard import mirror_io
from carter.guard.state import load, save
from carter.identity.schema import Workspace
from carter.install.paths import carter_gitconfig_path, guard_state_path
from gh_api import FakeGitHub, Reply
from guard.helpers import debug_config, verbose
from guard.test_never_blocks_human import git, human_commit_and_push, repo  # noqa: F401
from ssh_rig import KeyPair

LOGIN, UID = "octocat", 583231


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def global_cfg() -> Path:
    return Path(os.environ["GIT_CONFIG_GLOBAL"])


def carter_tree(home: Path) -> dict[str, bytes]:
    root = home / ".carter"
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "backups" not in p.parts
    }


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    server = FakeGitHub().start()
    monkeypatch.setenv("GITHUB_API_URL", server.url)
    server.public_world()
    yield server
    server.stop()


@pytest.fixture
def identity(fake: FakeGitHub, throwaway_key) -> KeyPair:  # type: ignore[no-untyped-def]
    """T2 through a password manager's socket (nothing for ``identity remove`` to lock)."""
    key = throwaway_key("ed25519")
    items = [{"id": 1, "key": key.blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
    fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
    fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))
    req = identity_add.AddRequest(LOGIN, str(key.pub_path), None, "/run/pm/agent.sock", None)
    identity_add.apply_add(identity_add.plan_add(req))
    return key


def install_guards(stack) -> None:  # type: ignore[no-untyped-def]
    stack.fake()
    assert guard("install", "--yes", "--only", "hooks,alias").exit_code == 0


def remove_guards(stack) -> None:  # type: ignore[no-untyped-def]
    stack.fake(before=debug_config(stack.live), after=debug_config())
    res = guard("remove", "--yes")
    assert res.exit_code == 0, res.output


class TestRoundTrip:
    @pytest.mark.parametrize(
        "identity_first", [True, False], ids=["identity-first", "guards-first"]
    )
    def test_both_removals_in_either_order_restore_every_touched_file(
        self,
        stack,
        repo: Path,
        fake: FakeGitHub,
        throwaway_key,
        identity_first: bool,  # type: ignore[no-untyped-def]
    ) -> None:
        home = stack.home
        git(
            "config", "--global", "alias.user-thing", "!echo user", cwd=repo
        )  # preexisting user entries
        git("config", "--global", "carter.userkey", "mine", cwd=repo)
        before_global, before_tree = global_cfg().read_bytes(), carter_tree(home)
        install_guards(stack)
        key = throwaway_key("ed25519")
        items = [{"id": 1, "key": key.blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
        fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
        fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))
        identity_add.apply_add(
            identity_add.plan_add(
                identity_add.AddRequest(LOGIN, str(key.pub_path), None, "/run/pm/agent.sock", None)
            )
        )
        report = None
        if identity_first:
            report = identity_remove.remove_identity()
            hooks_left = [k for k, _ in mirror_io.read_entries(carter_gitconfig_path(None))]
            assert (
                "hook.carter-guard-pre-push.event" in hooks_left and "carter.tier" not in hooks_left
            )
            assert (
                home / ".carter" / "hooks" / "carter-guard"
            ).exists()  # the guards are not its business
            remove_guards(stack)
        else:
            remove_guards(stack)
            leftover = [k for k, _ in mirror_io.read_entries(carter_gitconfig_path(None))]
            assert leftover[0] == "carter.tier" and not any(
                k.startswith(("hook.", "alias.")) for k in leftover
            )
            assert (home / ".carter" / "bin" / "carter-ssh-sign").exists()
            from carter.identity.payload import shim_state

            assert shim_state(home).ok  # the guards' removal kept the shim's hash record
            report = identity_remove.remove_identity()
        assert report is not None and not report.kept
        assert global_cfg().read_bytes() == before_global
        assert carter_tree(home) == before_tree, sorted(set(carter_tree(home)) ^ set(before_tree))
        assert git("config", "--global", "--get", "carter.userkey").stdout.strip() == "mine"

    def test_a_users_own_alias_survives_both_removals(
        self, stack, repo: Path, identity: KeyPair
    ) -> None:
        git("config", "--global", "alias.ai-commit", "!echo mine", cwd=repo)
        stack.fake()
        guard("install", "--yes", "--only", "alias")  # kept: the user has one
        remove_guards(stack)
        identity_remove.remove_identity()
        assert git("config", "--global", "--get", "alias.ai-commit").stdout.strip() == "!echo mine"

    def test_the_plugin_rollback_keeps_the_identity(self, stack, identity: KeyPair) -> None:
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert guard("remove", "--yes", "--only", "plugin").exit_code == 0
        assert (stack.home / ".carter" / "bin" / "carter-ssh-sign").exists()
        assert "carter.tier" in dict(mirror_io.read_entries(carter_gitconfig_path(None)))

    def test_uninstall_runs_both_removals(self, stack, identity: KeyPair, human_tty) -> None:  # type: ignore[no-untyped-def]
        install_guards(stack)
        stack.fake(before=debug_config(stack.live), after=debug_config())
        done = CliRunner().invoke(main, ["uninstall", "--yes"], catch_exceptions=False)
        assert done.exit_code == 0, done.output
        assert "carter identity remove" in done.output
        assert not (stack.home / ".carter" / "bin" / "carter-ssh-sign").exists()
        assert not carter_gitconfig_path(None).exists()

    def test_uninstall_asks_nothing_but_an_agent_shell_keeps_the_identity(
        self, stack, identity: KeyPair, human_tty, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        human_tty(False)
        shim = stack.home / ".carter" / "bin" / "carter-ssh-sign"
        monkeypatch.setenv("AGENT", "1")
        agent = CliRunner().invoke(main, ["uninstall"], catch_exceptions=False)
        assert "LLM identity kept: agent shell" in agent.output and shim.exists()
        monkeypatch.delenv("AGENT")
        done = CliRunner().invoke(main, ["uninstall"], catch_exceptions=False)
        assert done.exit_code == 0 and not shim.exists()


def human_ok(repo: Path, name: str) -> None:
    human_commit_and_push(repo, name)


class TestNeverBlocksTheHuman:
    @pytest.fixture(autouse=True)
    def installed(self, stack, repo: Path, identity: KeyPair) -> None:  # type: ignore[no-untyped-def]
        stack.fake()
        assert guard("install", "--yes", "--only", "hooks").exit_code == 0
        human_ok(repo, "base")

    def test_a_deleted_cap_fragment(self, repo: Path, tmp_path: Path) -> None:
        from dataclasses import replace

        from carter.identity.config import load_identity
        from carter.identity.writer import write_config

        cfg = load_identity()
        cfg = replace(cfg, workspaces={str(repo.parent): Workspace(max_tier="t1")})
        write_config(cfg, Path.home() / ".carter" / "config.toml")
        state = load(guard_state_path(None))
        mirror_io.sync(None, state, cfg)
        save(state, guard_state_path(None))
        (frag,) = (Path.home() / ".carter" / "gitconfig.d").iterdir()
        human_ok(repo, "with-fragment")
        frag.unlink()
        human_ok(repo, "no-fragment")

    def test_a_malformed_fragment_breaks_git_only_in_that_workspace_and_deleting_it_fixes_it(
        self, repo: Path
    ) -> None:
        from dataclasses import replace

        from carter.identity.config import load_identity
        from carter.identity.writer import write_config

        cfg = replace(load_identity(), workspaces={str(repo.parent): Workspace(max_tier="t1")})
        write_config(cfg, Path.home() / ".carter" / "config.toml")
        state = load(guard_state_path(None))
        mirror_io.sync(None, state, cfg)
        save(state, guard_state_path(None))
        (frag,) = (Path.home() / ".carter" / "gitconfig.d").iterdir()
        frag.write_text(
            "[carter\n\ttier = broken\n"
        )  # git's own rule: an unparseable include is fatal
        assert git("status", cwd=repo).returncode != 0  # inside the capped workspace
        elsewhere = repo.parent.parent / "elsewhere"
        elsewhere.mkdir()
        assert git("init", "-q", cwd=elsewhere).returncode == 0  # outside it git is fine
        frag.unlink()  # the documented emergency step
        human_ok(repo, "fixed")

    def test_the_shim_allowed_signers_and_socket_directory_gone(self, repo: Path) -> None:
        carter = Path.home() / ".carter"
        for rel in ("bin/carter-ssh-sign", "hooks/allowed_signers"):
            (carter / rel).unlink()
        human_ok(repo, "a")
        (carter / "run").mkdir(exist_ok=True)
        os.rmdir(carter / "run")
        human_ok(repo, "b")

    def test_a_corrupt_config_toml_disables_agent_commits_not_the_humans(self, repo: Path) -> None:
        (Path.home() / ".carter" / "config.toml").write_text("schema = 2\n[identity\nbroken")
        human_ok(repo, "c")
        from carter.identity.env import answer

        assert (
            answer(str(repo), {}, str(Path.home() / ".carter" / "config.toml"), Path.home())[
                "reason"
            ]
            == "config-error"
        )

    def test_a_killed_identity_add_leaves_nothing_and_git_works(
        self,
        repo: Path,
        fake: FakeGitHub,
        throwaway_key,
        monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    ) -> None:
        identity_remove.remove_identity()
        before = carter_tree(Path.home())
        key = throwaway_key("ed25519")
        items = [{"id": 1, "key": key.blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
        fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
        fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))

        def die(*_a: object, **_k: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(mirror_io, "sync", die)
        plan = identity_add.plan_add(
            identity_add.AddRequest(LOGIN, str(key.pub_path), None, "/run/pm/a.sock", None)
        )
        with pytest.raises(KeyboardInterrupt):
            identity_add.apply_add(plan)
        assert carter_tree(Path.home()) == before
        human_ok(repo, "d")

    def test_a_deleted_gitconfig_with_the_include_line_left(self, repo: Path) -> None:
        carter_gitconfig_path(None).unlink()
        human_ok(repo, "e")

    def test_the_guard_script_deleted_or_unreadable(self, repo: Path) -> None:
        script = Path.home() / ".carter" / "hooks" / "carter-guard"
        script.chmod(0)
        human_ok(repo, "f")
        script.unlink()
        human_ok(repo, "g")


class TestEmergencyPath:
    def test_deleting_carters_gitconfig_restores_git_without_carter(
        self, stack, repo: Path, identity: KeyPair
    ) -> None:
        stack.fake()
        guard("install", "--yes", "--only", "hooks")
        assert (
            git("config", "--global", "--includes", "--get", "carter.tier", cwd=repo).stdout.strip()
            == "t2"
        )
        carter_gitconfig_path(None).unlink()
        assert (
            git("config", "--global", "--includes", "--get", "carter.tier", cwd=repo).returncode
            == 1
        )
        assert git("hook", "list", "pre-push", cwd=repo).stdout.strip() == ""
        human_commit_and_push(repo, "z")

    def test_a_deleted_shim_makes_a_t2_agent_commit_fail_closed(
        self, stack, repo: Path, identity: KeyPair
    ) -> None:
        from carter.identity import env as entry
        from carter.identity.payload import to_git_env

        stack.fake()
        guard("install", "--yes", "--only", "hooks")
        home = Path.home()
        block = entry.answer(str(repo), {}, str(home / ".carter" / "config.toml"), home)
        # the shim file is recorded, so the block is offered; then the file disappears
        shim = home / ".carter" / "bin" / "carter-ssh-sign"
        assert block["signing"]
        shim.unlink()
        env = to_git_env(
            {
                **os.environ,
                "CARTER_AGENT_SHELL": "1",
                "GIT_AUTHOR_NAME": "a",
                "GIT_AUTHOR_EMAIL": "a@e.invalid",
            },
            block["signing"],
        ).env
        (repo / "x").write_text("x")
        git("add", "x", cwd=repo)
        done = subprocess.run(
            ["git", "commit", "-q", "-m", "agent"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert done.returncode != 0, (
            "a T2 commit with the shim gone must fail, never fall back to unsigned"
        )
        assert git("log", "-1", "--format=%s", cwd=repo).stdout.strip() != "agent"
