"""``carter identity unlock | lock`` (plan 005 step 11, freeze H10/H12; D50, D54, D58).

Refusals are tested in-process with a faked terminal (``CliRunner`` has none); the flows run the
real command on a real PTY against a real dedicated agent in the ``/tmp/c2b-*`` base. The one thing
that cannot be driven headless, the human typing into OpenCode's integrated terminal, is listed
for step 33.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from carter import identity_cli
from carter.cli import main
from carter.identity import agent_paths, agent_proc
from carter.identity.errors import (
    E_CONFIG,
    E_UNLOCK_NOPASS,
    E_UNLOCK_OPENCODE,
    E_UNLOCK_PATH,
    E_UNLOCK_TTY,
    registry,
)
from ssh_rig import PASSPHRASE_PROMPT, KeyPair, Rig, pty_run, real_ssh

LOGIN, UID = "llm-bot", 4242


def config_text(key: KeyPair, **signing: str) -> str:
    lines = [
        "schema = 2",
        "[identity]",
        f'login = "{LOGIN}"',
        f"id = {UID}",
        f'email = "{UID}+{LOGIN}@users.noreply.github.com"',
        "[identity.signing]",
        f'public_key = "{key.blob} comment"',
        f'fingerprint = "{key.fingerprint}"',
    ]
    if "agent_socket" not in signing and "program" not in signing:
        lines.append(f'private_key_path = "{key.path}"')
    lines += [f'{name} = "{value}"' for name, value in signing.items()]
    return "\n".join(lines) + "\n"


@dataclass
class Env:
    rig: Rig
    home: Path
    key: KeyPair

    @property
    def config(self) -> Path:
        return self.home / ".carter" / "config.toml"

    def write(self, **signing: str) -> None:
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(config_text(self.key, **signing))

    def child_env(self, **extra: str) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "TERM": "xterm",
            **extra,
        }

    def run(self, *args: str, answers: list[str] | tuple[str, ...] = (), **extra: str):  # type: ignore[no-untyped-def]
        """Run ``carter identity ...`` on a PTY (a real terminal) and type ``answers``."""
        script = [(PASSPHRASE_PROMPT, a) for a in answers]
        return pty_run(
            [sys.executable, "-m", "carter.cli", "identity", *args],
            self.child_env(**extra),
            script,
            scrub=list(answers),
            timeout=40,
        )

    @property
    def agents(self) -> list[int]:
        return agent_proc.agents_under(self.home / ".carter" / "run")


@pytest.fixture
def cli_env(rig: Rig, throwaway_key: Callable[..., KeyPair]) -> Iterator[Env]:
    key = throwaway_key("ed25519", True)
    home = rig.root / "home"
    state = Env(rig, home, key)
    state.write()
    yield state
    for pid in state.agents:
        agent_proc.stop_agent(pid)


@pytest.fixture
def plain_env(rig: Rig, throwaway_key: Callable[..., KeyPair]) -> Iterator[Env]:
    key = throwaway_key("ed25519")  # no passphrase
    state = Env(rig, rig.root / "home", key)
    state.write()
    yield state
    for pid in state.agents:
        agent_proc.stop_agent(pid)


@pytest.fixture
def as_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the in-process command think it has a terminal."""
    monkeypatch.setattr(identity_cli, "stdin_is_tty", lambda: True)
    monkeypatch.setattr(identity_cli, "_stderr_is_tty", lambda: True)


def invoke(*args: str, env: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(main, ["identity", *args], env=env, catch_exceptions=False)


class TestRegistration:
    def test_the_group_and_the_two_commands_exist_with_the_frozen_options(self) -> None:
        group = identity_cli.identity
        assert set(group.commands) == {"unlock", "lock"}
        unlock = {o.opts[0] for o in group.commands["unlock"].params} - {"--help"}
        assert unlock == {"--ttl", "--extend", "--allow-no-passphrase"}
        assert {o.opts[0] for o in group.commands["lock"].params} == {"--all"}
        assert "identity" in main.commands

    def test_help_mentions_the_terminal_and_does_not_start_anything(self) -> None:
        out = invoke("unlock", "--help").output
        assert "your own terminal" in out and "--allow-no-passphrase" in out


class TestRefusals:
    """Before any process starts, in the order OpenCode, then terminal (H10)."""

    @pytest.mark.parametrize(
        "variable",
        [
            "AGENT",
            "AI_AGENT",
            "OPENCODE_SESSION_ID",
            "CARTER_AGENT_SHELL",
            "OPENCODE",
            "OPENCODE_TERMINAL",
        ],
    )
    def test_an_agent_signal_or_opencode_terminal_is_refused_even_with_a_terminal(
        self, variable: str, as_human: None, rig: Rig
    ) -> None:
        done = invoke("unlock", env={variable: "1"})
        assert done.exit_code == 1
        assert done.output.startswith(f"Error: {E_UNLOCK_OPENCODE}: ")
        assert registry()[E_UNLOCK_OPENCODE].message in done.output
        assert variable in done.output  # names only, never values

    def test_a_human_tag_does_not_lift_the_opencode_terminal_refusal(self, as_human: None) -> None:
        done = invoke("unlock", env={"OPENCODE_TERMINAL": "1", "CARTER_HUMAN_SHELL": "1"})
        assert done.exit_code == 1 and E_UNLOCK_OPENCODE in done.output

    def test_no_terminal_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(identity_cli, "stdin_is_tty", lambda: False)
        done = invoke("unlock")
        assert done.exit_code == 1 and f"Error: {E_UNLOCK_TTY}: " in done.output
        monkeypatch.setattr(identity_cli, "stdin_is_tty", lambda: True)
        monkeypatch.setattr(identity_cli, "_stderr_is_tty", lambda: False)
        assert E_UNLOCK_TTY in invoke("unlock").output

    def test_the_refusals_come_before_the_config_is_read_or_a_process_started(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import subprocess

        def boom(*_a: object, **_k: object) -> None:
            raise AssertionError("a process was started")

        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(subprocess, "Popen", boom)
        monkeypatch.setenv("HOME", str(tmp_path))  # no config.toml at all
        monkeypatch.setattr(identity_cli, "stdin_is_tty", lambda: False)
        assert E_UNLOCK_TTY in invoke("unlock").output
        assert E_UNLOCK_OPENCODE in invoke("unlock", env={"AGENT": "1"}).output

    def test_lock_refuses_in_an_agent_shell_but_needs_no_terminal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert E_UNLOCK_OPENCODE in invoke("lock", env={"OPENCODE_TERMINAL": "1"}).output
        monkeypatch.setattr(identity_cli, "stdin_is_tty", lambda: False)
        done = invoke("lock")  # no config: reaches the config step, i.e. past the terminal check
        assert E_UNLOCK_TTY not in done.output and "No LLM signing key" in done.output

    def test_a_bad_ttl_is_a_usage_error_before_anything_runs(
        self, as_human: None, plain_env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(plain_env.home))
        for bad in ("forever", "0", "8 hours", "-1h"):
            done = invoke("unlock", "--ttl", bad, "--allow-no-passphrase")
            assert done.exit_code == 2 and "--ttl" in done.output, bad
        assert not plain_env.agents


class TestConfigNeeds:
    def test_without_a_signing_key_it_says_what_to_run(
        self, as_human: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        done = invoke("unlock")
        assert done.exit_code == 1 and "carter identity add" in done.output

    def test_a_broken_config_is_e_config_not_a_guess(
        self, as_human: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / ".carter").mkdir()
        (tmp_path / ".carter" / "config.toml").write_text("schema = 2\nnot toml [[[")
        monkeypatch.setenv("HOME", str(tmp_path))
        done = invoke("unlock")
        assert done.exit_code == 1 and f"Error: {E_CONFIG}" in done.output

    @pytest.mark.parametrize(
        "extra", [{"agent_socket": "/run/pm/agent.sock"}, {"program": "/opt/pm/sign"}]
    )
    def test_password_manager_setups_run_nothing(
        self, as_human: None, plain_env: Env, monkeypatch: pytest.MonkeyPatch, extra: dict[str, str]
    ) -> None:
        import subprocess

        def boom(*_a: object, **_k: object) -> None:
            raise AssertionError("a process was started")

        plain_env.write(**extra)
        monkeypatch.setenv("HOME", str(plain_env.home))
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", boom)
            for verb in ("unlock", "lock"):
                done = invoke(verb)
                assert done.exit_code == 0 and "managed by your password manager" in done.output


@real_ssh
class TestUnlockFlows:
    def test_a_passphrase_key_is_unlocked_once_and_the_second_call_does_not_prompt(
        self, cli_env: Env
    ) -> None:
        pw = cli_env.key.passphrase
        assert pw
        first = cli_env.run("unlock", answers=[pw])
        assert first.rc == 0, first.output
        assert (
            "Unlocked the LLM signing key for 8h" in first.output
            and cli_env.key.fingerprint in first.output
        )
        assert pw not in first.output
        second = cli_env.run("unlock")  # nothing typed: a prompt would time out
        assert second.rc == 0 and "already unlocked" in second.output
        assert "passphrase" not in second.output.lower()
        assert len(cli_env.agents) == 1

    def test_extend_asks_again_and_ttl_is_passed_to_ssh_add(self, cli_env: Env) -> None:
        pw = cli_env.key.passphrase
        assert pw
        assert cli_env.run("unlock", "--ttl", "30m", answers=[pw]).rc == 0
        again = cli_env.run("unlock", "--extend", "--ttl", "2h", answers=[pw])
        assert again.rc == 0 and "for 2h" in again.output and "Enter passphrase" in again.output

    def test_a_wrong_passphrase_is_ssh_adds_own_retry_and_a_blank_line_ends_it(
        self, cli_env: Env
    ) -> None:
        done = cli_env.run("unlock", answers=["wrong-" + "x" * 6, ""])
        assert done.rc == 1
        assert "Bad passphrase, try again" in done.output  # passed through, not wrapped
        assert "Unlock failed" in done.output and "no key was loaded" in done.output
        assert not cli_env.agents  # the agent it started was not left behind

    def test_a_key_without_a_passphrase_is_refused_without_the_flag(self, plain_env: Env) -> None:
        done = plain_env.run("unlock")
        assert done.rc == 1
        assert E_UNLOCK_NOPASS in done.output and LOGIN in done.output
        assert "<llm-login>" not in done.output
        assert not plain_env.agents  # nothing was started

    def test_with_the_flag_it_unlocks_and_warns(self, plain_env: Env) -> None:
        done = plain_env.run("unlock", "--allow-no-passphrase")
        assert done.rc == 0, done.output
        assert f"any process of yours can sign as {LOGIN}" in done.output
        assert "Unlocked the LLM signing key" in done.output

    @pytest.mark.parametrize(
        ("setup", "word"),
        [("missing", "missing"), ("directory", "not a file"), ("loose", "too open")],
    )
    def test_a_bad_key_file_is_reported_without_its_path(
        self, plain_env: Env, setup: str, word: str
    ) -> None:
        key = plain_env.key
        if setup == "missing":
            key.path.unlink()
        elif setup == "directory":
            key.path.unlink()
            key.path.mkdir()
        else:
            key.path.chmod(0o644)
        done = plain_env.run("unlock", "--allow-no-passphrase")
        assert done.rc == 1 and word in done.output and "nothing was started" in done.output
        assert str(key.path) not in done.output
        assert not plain_env.agents

    def test_it_uses_the_configured_ssh_bin_dir_for_all_three_tools(
        self, plain_env: Env, tmp_path: Path
    ) -> None:
        wrappers = plain_env.rig.root / "wrap"
        wrappers.mkdir()
        log = plain_env.rig.root / "tools.log"
        for tool in ("ssh-keygen", "ssh-agent", "ssh-add", "ssh"):
            script = wrappers / tool
            script.write_text(f'#!/bin/sh\necho {tool} >> {log}\nexec /usr/bin/{tool} "$@"\n')
            script.chmod(0o755)
        plain_env.write(ssh_bin_dir=str(wrappers))
        assert plain_env.run("unlock", "--allow-no-passphrase").rc == 0
        assert plain_env.run("lock").rc == 0
        used = set(log.read_text().split())
        assert {"ssh-keygen", "ssh-agent", "ssh-add"} <= used

    def test_it_writes_no_config_and_no_guard_state(self, plain_env: Env) -> None:
        before = hashlib.sha256(plain_env.config.read_bytes()).hexdigest()
        assert plain_env.run("unlock", "--allow-no-passphrase").rc == 0
        assert plain_env.run("lock").rc == 0
        assert hashlib.sha256(plain_env.config.read_bytes()).hexdigest() == before
        carter = plain_env.home / ".carter"
        assert sorted(p.name for p in carter.iterdir()) == ["config.toml", "run"]
        assert not (carter / "guard-state.json").exists()

    def test_output_holds_names_and_states_only(self, cli_env: Env) -> None:
        pw = cli_env.key.passphrase
        assert pw
        done = cli_env.run("unlock", answers=[pw])
        mine = done.output.strip().splitlines()[
            -1
        ]  # ssh-add's own lines above name the key it adds
        assert mine.startswith("Unlocked the LLM signing key")
        assert str(cli_env.key.path) not in mine and str(cli_env.home) not in mine
        assert pw not in done.output

    def test_an_unbindable_socket_path_is_e_unlock_path(self, plain_env: Env) -> None:
        long_home = plain_env.rig.root / ("h" * 100)
        long_home.mkdir()
        (long_home / ".carter").mkdir()
        (long_home / ".carter" / "config.toml").write_text(config_text(plain_env.key))
        env = plain_env.child_env()
        env["HOME"] = str(long_home)
        out = pty_run(
            [sys.executable, "-m", "carter.cli", "identity", "unlock", "--allow-no-passphrase"],
            env,
            [],
            timeout=40,
        )
        assert out.rc == 1 and E_UNLOCK_PATH in out.output and "108" in out.output
        assert not agent_proc.agents_under(long_home / ".carter")


@real_ssh
class TestLockFlows:
    def test_lock_removes_the_key_and_a_second_lock_is_a_quiet_success(
        self, plain_env: Env
    ) -> None:
        plain_env.run("unlock", "--allow-no-passphrase")
        assert plain_env.agents
        first = plain_env.run("lock")
        assert first.rc == 0 and "Locked: the LLM signing key is not loaded" in first.output
        assert "agent was stopped" in first.output and not plain_env.agents
        second = plain_env.run("lock")
        assert second.rc == 0 and "Already locked" in second.output

    def test_lock_without_ever_unlocking_is_already_locked(self, plain_env: Env) -> None:
        done = plain_env.run("lock")
        assert done.rc == 0 and "Already locked" in done.output

    def test_lock_all_stops_a_leftover_agent_under_the_socket_directory(
        self, plain_env: Env
    ) -> None:
        plain_env.run("unlock", "--allow-no-passphrase")
        run_dir = agent_paths.run_dir(plain_env.home)
        leftover = plain_env.rig.run("ssh-agent", "-a", str(run_dir / "old.sock"), "-s")
        pid = int(leftover.stdout.split("SSH_AGENT_PID=")[1].split(";")[0])
        plain_env.rig.pids.append(pid)
        assert len(plain_env.agents) == 2
        done = plain_env.run("lock", "--all")
        assert done.rc == 0 and not plain_env.agents


def test_the_registry_texts_the_cli_prints_exist() -> None:
    reg: Any = registry()
    for code in (E_UNLOCK_TTY, E_UNLOCK_OPENCODE, E_UNLOCK_NOPASS, E_UNLOCK_PATH):
        assert reg[code].slice == "2b"
