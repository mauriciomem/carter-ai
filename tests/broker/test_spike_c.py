# ruff: noqa: E501
"""Spike C of plan 007 (step 4): what real git, OpenSSH and the fakes do for B's child process.

Everything is local: bare remotes in tmp, a fake ``ssh`` that runs ``git receive-pack`` against
them, no network, no agent socket. Recorded findings live in ``plans/active/007-slice-b-broker/notes.md``;
these tests pin them so a git or OpenSSH change that breaks an assumption fails here first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aplus import helpers
from broker.fakes import FakeSsh, install_fake_ssh
from carter.aplus import run, sshcfg

DATA = Path(__file__).resolve().parents[1] / "data"
HOSTILE = json.loads((DATA / "b_hostile_argv.json").read_text())
SSH_G = DATA / "ssh_g"
SSH_G_INDEX = json.loads((SSH_G / "index.json").read_text())

GOOD_SCP = "git@github.com:o/r.git"
SENTINEL_SERVER_PASSWORD = "sentinel-server-password-0001"  # noqa: S105 - a test value


def child_env(home: Path) -> dict[str, str]:
    """A from-scratch push environment, as C.5 describes it (no SSH_AUTH_SOCK: the fake needs none)."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
        "GIT_TERMINAL_PROMPT": "0",
        "SSH_ASKPASS_REQUIRE": "never",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
    }


class Rig:
    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "home"
        self.home.mkdir()
        (self.home / "gitconfig").write_text("")
        self.fake: FakeSsh = install_fake_ssh(tmp / "fakebin")
        self.bare = self.fake.bare()
        self.bare.parent.mkdir(parents=True)
        helpers.git("init", "-q", "--bare", "-b", "main", str(self.bare))
        self.ws = helpers.make_repo(tmp / "ws")
        helpers.git("config", "user.name", "T", cwd=self.ws)
        helpers.git("config", "user.email", "t@example.invalid", cwd=self.ws)
        self.base_sha = helpers.commit_file(self.ws, "a")
        helpers.git("push", "-q", str(self.bare), f"{self.base_sha}:refs/heads/main", cwd=self.ws)
        helpers.git("checkout", "-q", "-b", "feat/x", cwd=self.ws)
        self.sha = helpers.commit_file(self.ws, "b")
        self.mark = tmp / "MARK"

    def push(
        self, operands: list[str], *, ssh_command: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """B's future shape: hardening, ``-c core.sshCommand``, protocol allow-list, ``--``."""
        argv = [
            "git",
            "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/nonexistent-empty",
            "-c", "credential.helper=", "-c", "core.askPass=", "-c", "core.pager=cat",
            "-c", f"core.sshCommand={ssh_command or self.fake.ssh_command()}",
            "-c", "protocol.allow=never", "-c", "protocol.ssh.allow=always",
            "--no-pager", "push", *operands,
        ]  # fmt: skip
        return subprocess.run(
            argv, cwd=self.ws, env=child_env(self.home), capture_output=True, text=True
        )

    def remote_heads(self) -> list[str]:
        out = helpers.git("for-each-ref", "--format=%(refname)", cwd=self.bare).stdout.split()
        return sorted(r for r in out if r != "refs/heads/main")

    def reset_remote(self) -> None:
        for ref in self.remote_heads():
            helpers.git("update-ref", "-d", ref, cwd=self.bare)
        for path in self.mark.parent.glob("MARK*"):
            path.unlink()
        self.fake.reset()


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


class TestFakeSshSeam:
    @pytest.mark.parametrize("url", [GOOD_SCP, "ssh://git@github.com/o/r.git"])
    def test_the_fake_receives_both_url_forms_through_core_sshcommand_alone(
        self, rig: Rig, url: str
    ) -> None:
        res = rig.push(["--", url, f"{rig.sha}:refs/heads/feat/x"])
        assert res.returncode == 0, res.stderr
        assert rig.remote_heads() == ["refs/heads/feat/x"]
        (call,) = rig.fake.calls()
        assert call["argv"][0] == "git@github.com" and call["argv"][1].startswith(
            "git-receive-pack"
        )

    def test_no_insteadof_and_no_env_var_is_needed(self, rig: Rig) -> None:
        assert (rig.home / "gitconfig").read_text() == ""
        rig.push(["--", GOOD_SCP, f"{rig.sha}:refs/heads/feat/x"])
        (call,) = rig.fake.calls()
        assert not [
            n for n in call["env_names"] if n.startswith(("CARTER", "OPENCODE", "SSH_AUTH"))
        ]
        # git itself adds GIT_EXEC_PATH to the ssh child; nothing else beyond the allowlist
        assert set(call["env_names"]) <= set(child_env(rig.home)) | {"GIT_EXEC_PATH"}

    def test_a_sentinel_in_the_parent_never_reaches_ssh_when_the_env_is_built_from_scratch(
        self, rig: Rig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", SENTINEL_SERVER_PASSWORD)
        rig.push(["--", GOOD_SCP, f"{rig.sha}:refs/heads/feat/x"])
        assert SENTINEL_SERVER_PASSWORD not in (rig.fake.bindir / "ssh.calls").read_text()

    def test_git_ssh_command_in_the_env_would_beat_core_sshcommand(self, rig: Rig) -> None:
        """Why the env must be built from scratch: an inherited GIT_SSH_COMMAND wins."""
        argv = ["git", "-c", f"core.sshCommand={rig.fake.ssh_command()}", "push", "--", GOOD_SCP,
                f"{rig.sha}:refs/heads/feat/x"]  # fmt: skip
        env = {**child_env(rig.home), "GIT_SSH_COMMAND": "/bin/false"}
        res = subprocess.run(argv, cwd=rig.ws, env=env, capture_output=True, text=True)
        assert res.returncode != 0 and rig.fake.calls() == []

    @pytest.mark.parametrize(
        "url",
        [
            "ssh://git@github.com/o/r.git",
            "file://{bare}",
            "{bare}",
            "https://github.com/o/r.git",
            "git://github.com/o/r.git",
        ],
    )
    def test_protocol_allow_never_plus_ssh_always_stops_every_other_transport(
        self, rig: Rig, url: str
    ) -> None:
        url = url.format(bare=rig.bare)
        res = rig.push(["--", url, f"{rig.sha}:refs/heads/feat/x"])
        if url.startswith("ssh://"):
            assert res.returncode == 0
        else:
            assert res.returncode == 128 and "not allowed" in res.stderr
            assert rig.remote_heads() == [] and rig.fake.calls() == []

    def test_quotes_in_a_path_reach_ssh_shell_quoted(self, rig: Rig) -> None:
        rig.push(["--", "ssh://git@github.com/o/r';id;'", f"{rig.sha}:refs/heads/feat/x"])
        (call,) = rig.fake.calls()
        assert call["argv"][1] == "git-receive-pack '/o/r'\\'';id;'\\'''"


def _cases(kind: str, *, dashdash: bool) -> list[Any]:
    return [
        pytest.param(c, id=f"{c['kind']}-{c['id']}-{c['variant']}")
        for c in HOSTILE["cases"]
        if c["kind"] == kind and c["dashdash"] is dashdash
    ]


PROTOCOL_BLOCKED = {"file-url", "local-path"}


def _materialise(rig: Rig, operand: str) -> str:
    return (
        operand.replace("<SHA>", rig.sha)
        .replace("<OTHER>", rig.base_sha)
        .replace("<BARE>", str(rig.bare))
        .replace("<MARK>", str(rig.mark))
    )


class TestHostileOperandsAgainstRealGit:
    """The table in ``tests/data/b_hostile_argv.json``; step 8's validators answer ``expect_validator``."""

    @pytest.mark.parametrize(
        "case", _cases("remote", dashdash=True) + _cases("refspec", dashdash=True)
    )
    def test_git_behaviour_matches_the_recorded_table(self, rig: Rig, case: dict[str, Any]) -> None:
        operands = ["--", *[_materialise(rig, o) for o in case["operands"]]]
        res = rig.push(operands)
        reached = bool(rig.fake.calls()) or res.returncode == 0 or bool(rig.remote_heads())
        # the table was recorded with plain git; B's `protocol.allow=never` additionally stops
        # the two non-ssh transports (the validator still refuses them first)
        expected = (
            case["reaches_transport_or_changes_remote"] and case["id"] not in PROTOCOL_BLOCKED
        )
        assert reached is expected, (case["id"], res.stderr)
        assert not any(rig.mark.parent.glob("MARK*")), "code ran"

    def test_dashdash_alone_blocks_every_option_shaped_operand(self, rig: Rig) -> None:
        optiony = [
            c for c in HOSTILE["cases"]
            if c["dashdash"] and any(o.startswith("-") for o in c["operands"])
        ]  # fmt: skip
        assert len(optiony) >= 12
        for case in optiony:
            rig.reset_remote()
            operands = ["--", *[_materialise(rig, o) for o in case["operands"]]]
            res = rig.push(operands)
            assert res.returncode != 0 or case["id"] == "dash-branch", case["id"]
            assert not rig.mark.exists()

    def test_without_dashdash_an_option_shaped_remote_reaches_ssh_and_is_parsed_as_an_option(
        self, rig: Rig
    ) -> None:
        """The reason the builder always emits ``--``: git takes ``--receive-pack=`` as an option and
        the refspec as an scp-style host (report 21 row 7, reproduced)."""
        res = rig.push([f"--receive-pack=touch {rig.mark}", f"{rig.sha}:refs/heads/feat/x"])
        assert res.returncode != 0
        assert len(rig.fake.calls()) == 1
        assert rig.fake.calls()[0]["argv"][0] == rig.sha
        assert (
            not rig.mark.exists()
        )  # the fake refuses the remote command; the remote host would not

    def test_the_table_is_complete_enough(self) -> None:
        ids = {(c["kind"], c["id"]) for c in HOSTILE["cases"]}
        for needed in [
            ("remote", "recv-pack"), ("remote", "repo-opt"), ("remote", "dash-o"), ("remote", "dash-u"),
            ("refspec", "force-plus"), ("refspec", "delete"), ("refspec", "glob-all"), ("refspec", "tag"),
            ("refspec", "head-sym"), ("refspec", "dash-branch"), ("remote", "newline"), ("remote", "upper-host"),
        ]:  # fmt: skip
            assert needed in ids, needed

    def test_a_trailing_newline_defeats_a_dollar_anchored_pattern(self) -> None:
        """Validators must use ``fullmatch``: ``$`` also matches before a final newline."""
        pattern = r"^git@github\.com:[\w.-]+/[\w.-]+(\.git)?$"
        assert re.match(pattern, "git@github.com:o/r.git\n")
        assert not re.fullmatch(
            r"git@github\.com:[\w.-]+/[\w.-]+(\.git)?", "git@github.com:o/r.git\n"
        )

    def test_dot_dot_segments_pass_the_rfc_character_class(self) -> None:
        """``[\\w.-]+`` accepts ``..``: the validator must reject ``.`` and ``..`` segments."""
        assert re.fullmatch(r"git@github\.com:[\w.-]+/[\w.-]+(\.git)?", "git@github.com:../..")


class TestSshGOutputs:
    @pytest.mark.parametrize("name", sorted(SSH_G_INDEX))
    def test_parse_ssh_g_flags_exactly_the_recorded_keys(self, name: str) -> None:
        found = sorted({f.key for f in sshcfg.parse_ssh_g((SSH_G / name).read_text())})
        assert found == sorted(SSH_G_INDEX[name]["must_flag"]), name

    def test_proxyjump_is_not_flagged_and_is_a_documented_gap(self) -> None:
        assert not sshcfg.parse_ssh_g((SSH_G / "openssh-10.2-proxyjump.txt").read_text())

    def test_fixtures_carry_no_host_user_or_home(self) -> None:
        for path in SSH_G.glob("*.txt"):
            text = path.read_text()
            assert os.environ.get("USER", "-x-") not in text.split()
            assert "/home/" not in text.replace("/home/user", "")

    def test_the_fake_ssh_prints_a_fixture_for_dash_g(self, rig: Rig) -> None:
        rig.fake.set_ssh_g((SSH_G / "openssh-10.2-proxycommand.txt").read_text())
        out = run.run([rig.fake.ssh_command(), "-G", "github.com"], env=run.clean_env())
        assert [f.key for f in sshcfg.parse_ssh_g(out.stdout)] == ["proxycommand"]


MATCH_EXEC_FORMS = {
    "plain": 'Match exec "touch {m}"\n',
    "criteria-before": 'Match host github.com exec "touch {m}"\n',
    "caps": 'MATCH EXEC "touch {m}"\n',
    "tab": 'Match\texec\t"touch {m}"\n',
    "equals-keyword": 'Match=exec "touch {m}"\n',
    "originalhost": 'Match originalhost github.com exec "touch {m}"\n',
    "negated": 'Match !exec "touch {m}"\n',
    "equals-argument": 'Match exec="touch {m}"\n',
}


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH is not installed")
class TestMatchExec:
    @pytest.mark.parametrize("form", sorted(MATCH_EXEC_FORMS))
    def test_ssh_dash_g_really_runs_the_command_of_every_form(
        self, tmp_path: Path, form: str
    ) -> None:
        """Why the textual pre-scan comes first. ``-F`` keeps the test off the developer's own config."""
        marker = tmp_path / "RAN"
        config = tmp_path / "config"
        config.write_text(MATCH_EXEC_FORMS[form].format(m=marker))
        subprocess.run(
            ["ssh", "-F", str(config), "-G", "github.com"],
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            capture_output=True, stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
        assert marker.exists(), form

    @pytest.mark.parametrize(
        "form",
        [
            pytest.param(
                f,
                marks=pytest.mark.xfail(
                    strict=True, reason="GAP in sshcfg.scan_match_exec: step 9 must close it"
                ),
            )
            if f in {"negated", "equals-argument"}
            else f
            for f in sorted(MATCH_EXEC_FORMS)
        ],
    )
    def test_the_existing_prescan_catches_the_form(self, tmp_path: Path, form: str) -> None:
        (tmp_path / ".ssh").mkdir()
        (tmp_path / ".ssh" / "config").write_text(MATCH_EXEC_FORMS[form].format(m="/x"))
        assert [f.key for f in sshcfg.scan_match_exec(tmp_path)] == ["Match exec"]
