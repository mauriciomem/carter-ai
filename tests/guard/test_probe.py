"""``carter check --probe`` (plan 004 step 31; RFC-0007 §4.7, freeze G19).

The agent environment is the reference isolation block applied to a plain environment
(``apply_isolation``), so the probe is tested against the real contract. Real git, no network:
ssh, gh and the GitHub push are faked or refused locally.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import probe
from carter.identity import isolation
from carter.identity.isolation_apply import apply_isolation
from sentinels import fine_grained

SENTINEL_SOCKET = "/run/user/1000/SECRET-SOCK-4711/agent"
NAMES = [
    "ssh_agent_absent",
    "ssh_denied",
    "gh_pat_only",
    "push_refused",
    "commit_unsigned",
    "agent_tagged",
]


def agent_env(home: Path, *, token: str = "ghp_not-a-real-token-for-tests") -> dict[str, str]:
    doc = isolation.render(
        home=str(home), python_path="/p", carter_path="/c", false_path="/usr/bin/false"
    )
    base = {"PATH": os.environ["PATH"], "HOME": str(home), "SSH_AUTH_SOCK": SENTINEL_SOCKET}
    out = apply_isolation(base, doc, token).env
    out.pop("SSH_AUTH_SOCK", None)
    out.update({"CARTER_AGENT_SHELL": "1", "AGENT": "1"})
    return out


@pytest.fixture
def empty_gh(home: Path) -> Path:
    path = home / ".carter" / "run" / "gh-empty"
    path.mkdir(parents=True)
    return path


def fake_runner(real=subprocess.run, *, ssh: str = "", gh: str = ""):
    """Real git; ssh and gh answer with the given text (exit 255 / 0)."""

    def run(argv, **kw):
        if argv[0] == "ssh":
            return subprocess.CompletedProcess(argv, 255, stdout="", stderr=ssh)
        if argv[0] == "gh":
            return subprocess.CompletedProcess(argv, 0, stdout=gh, stderr="")
        return real(argv, **kw)

    return run


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


def results(env, home, **kw):
    runner = kw.pop("runner", fake_runner(ssh="git@github.com: Permission denied (publickey)."))
    return {
        r.name: r for r in probe.run_probes(env, home=home, runner=runner, which=which_all, **kw)
    }


class TestProbes:
    def test_the_reference_block_passes_everything(self, home: Path, empty_gh: Path) -> None:
        got = results(agent_env(home), home)
        assert list(got) == NAMES
        assert {n: r.status for n, r in got.items()} == dict.fromkeys(NAMES, "PASS")

    def test_an_ssh_agent_fails_the_first_probe(self, home: Path, empty_gh: Path) -> None:
        env = {**agent_env(home), "SSH_AUTH_SOCK": SENTINEL_SOCKET}
        assert results(env, home)["ssh_agent_absent"].status == "FAIL"

    def test_ssh_that_authenticates_fails(self, home: Path, empty_gh: Path) -> None:
        runner = fake_runner(ssh="Hi user! You've successfully authenticated, but GitHub...")
        assert results(agent_env(home), home, runner=runner)["ssh_denied"].status == "FAIL"

    @pytest.mark.parametrize(
        "said", ["ssh: Could not resolve hostname github.com", "Connection timed out"]
    )
    def test_offline_is_a_skip_not_a_pass(self, home: Path, empty_gh: Path, said: str) -> None:
        got = results(agent_env(home), home, runner=fake_runner(ssh=said))["ssh_denied"]
        assert got.status == "SKIP" and got.reason == "unreachable"

    def test_a_timeout_is_a_skip(self, home: Path, empty_gh: Path) -> None:
        def run(argv, **kw):
            if argv[0] == "ssh":
                assert kw["timeout"] == 5  # bounded
                raise subprocess.TimeoutExpired(argv, 5)
            return subprocess.run(argv, **kw)

        assert results(agent_env(home), home, runner=run)["ssh_denied"].status == "SKIP"

    def test_no_ssh_binary_is_a_skip(self, home: Path, empty_gh: Path) -> None:
        got = probe.ssh_denied(agent_env(home), subprocess.run, lambda _n: None)
        assert got.status == "SKIP" and got.reason == "ssh not installed"

    def test_gh_with_a_keyring_login_fails(self, home: Path, empty_gh: Path) -> None:
        runner = fake_runner(gh="Logged in to github.com account me (keyring)")
        got = results(agent_env(home), home, runner=runner)["gh_pat_only"]
        assert got.status == "FAIL" and got.reason == "gh found another login"

    def test_gh_config_dir_must_be_the_empty_one(self, home: Path, empty_gh: Path) -> None:
        env = {**agent_env(home), "GH_CONFIG_DIR": str(home / ".config/gh")}
        assert results(env, home)["gh_pat_only"].status == "FAIL"
        (empty_gh / "hosts.yml").write_text("x")
        assert (
            results(agent_env(home), home)["gh_pat_only"].reason == "the empty gh dir is not empty"
        )

    def test_no_gh_token_fails_and_no_gh_binary_skips(self, home: Path, empty_gh: Path) -> None:
        env = agent_env(home)
        env.pop("GH_TOKEN")
        assert results(env, home)["gh_pat_only"].status == "FAIL"
        got = probe.gh_pat_only(agent_env(home), home, subprocess.run, lambda _n: None)
        assert got.status == "SKIP"

    def test_a_push_that_is_not_refused_locally_fails(self, home: Path, empty_gh: Path) -> None:
        env = agent_env(home)
        for k in [k for k in env if k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))]:
            del env[k]
        env["GIT_CONFIG_COUNT"] = "0"
        got = probe.push_refused(env, subprocess.run)
        assert got.status == "FAIL"

    def test_the_scratch_repository_is_removed(
        self, home: Path, empty_gh: Path, tmp_path: Path
    ) -> None:
        import tempfile

        before = set(Path(tempfile.gettempdir()).glob("carter-probe-*"))
        probe.push_refused(agent_env(home), subprocess.run)
        probe.commit_unsigned(agent_env(home), subprocess.run)
        assert set(Path(tempfile.gettempdir()).glob("carter-probe-*")) == before

    def test_a_signing_program_that_is_not_the_root_owned_false_fails(
        self, home: Path, empty_gh: Path, tmp_path: Path
    ) -> None:
        mine = tmp_path / "false"
        mine.write_text("#!/bin/sh\nexit 1\n")
        env = agent_env(home)
        for k, v in list(env.items()):
            if v == "/usr/bin/false" and k.startswith("GIT_CONFIG_VALUE_"):
                env[k] = str(mine)
        got = probe.commit_unsigned(env, subprocess.run)
        assert got.status == "FAIL" and "root-owned false" in got.reason

    def test_commit_signing_on_fails(self, home: Path, empty_gh: Path) -> None:
        env = agent_env(home)
        for k, v in list(env.items()):
            if k.startswith("GIT_CONFIG_KEY_") and v == "commit.gpgsign":
                env["GIT_CONFIG_VALUE_" + k.removeprefix("GIT_CONFIG_KEY_")] = "true"
        assert probe.commit_unsigned(env, subprocess.run).status == "FAIL"

    def test_the_tags(self, home: Path) -> None:
        assert probe.agent_tagged({"CARTER_AGENT_SHELL": "1"}).status == "PASS"
        assert (
            probe.agent_tagged({"CARTER_AGENT_SHELL": "1", "CARTER_HUMAN_SHELL": "1"}).status
            == "FAIL"
        )
        assert probe.agent_tagged({}).status == "FAIL"


class TestCommand:
    def invoke(self, *args: str):
        return CliRunner().invoke(main, ["check", *args], catch_exceptions=False)

    def test_it_refuses_outside_an_agent_shell(self) -> None:
        res = self.invoke("--probe")
        assert res.exit_code == 1 and "E-PROBE-SCOPE" in res.output
        assert "ask your agent to run it" in res.output

    def test_probe_and_host_are_mutually_exclusive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT", "1")
        res = self.invoke("--probe", "--host")
        assert res.exit_code == 2 and "cannot be used together" in res.output

    def test_one_line_per_probe_exit_1_on_a_fail_and_no_value_leaks(
        self, home: Path, empty_gh: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = agent_env(home, token=fine_grained())
        env["SSH_AUTH_SOCK"] = SENTINEL_SOCKET  # a leak to catch: the probe must fail on it
        monkeypatch.setattr(os, "environ", env)
        monkeypatch.setattr(probe.shutil, "which", lambda _n: None)  # no ssh, no gh binary
        res = self.invoke("--probe")
        lines = res.output.strip().splitlines()
        assert [ln.split()[1] for ln in lines] == NAMES
        assert lines[0] == "FAIL ssh_agent_absent" and res.exit_code == 1
        assert all(ln.split()[0] in ("PASS", "FAIL", "SKIP") for ln in lines)
        for forbidden in ("SECRET-SOCK", fine_grained(), "ghp_", str(home), "/run/user"):
            assert forbidden not in res.output, forbidden

    def test_it_is_registered_in_the_help(self) -> None:
        assert "--probe" in self.invoke("--help").output
