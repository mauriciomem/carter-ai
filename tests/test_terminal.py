"""The human-terminal rule every Carter mutator shares (RFC-0007 App B §1, App C.1 AD1)."""

from __future__ import annotations

import ast
import io
import os
import pty
import sys
from pathlib import Path

import pytest

from carter import terminal
from carter.identity import IdentityError, rules
from carter.identity.errors import E_HUMAN_TERMINAL, registry
from carter.identity.rules import is_agent
from carter.terminal import is_agent_shell, require_human_terminal

REPO = Path(__file__).resolve().parents[1]
SUFFIX = (
    "If you are not an agent, this shell inherited agent variables; "
    "restart the app from a clean terminal"
)


@pytest.fixture
def pty_pair():
    """A real pseudo-terminal: (master, slave file object that reports isatty())."""
    master, slave = pty.openpty()
    handle = os.fdopen(slave, "w")
    yield handle
    handle.close()
    os.close(master)


class TestAgentTable:
    """App C.1 AD1: agent iff CARTER_AGENT_SHELL=1, or (AGENT or OPENCODE_SESSION_ID set and
    CARTER_HUMAN_SHELL unset)."""

    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({}, False),
            ({"AGENT": "x"}, True),
            ({"AGENT": "x", "CARTER_HUMAN_SHELL": "1"}, False),
            ({"CARTER_AGENT_SHELL": "1"}, True),
            ({"CARTER_AGENT_SHELL": "1", "CARTER_HUMAN_SHELL": "1"}, True),  # agent wins
            ({"OPENCODE_SESSION_ID": "ses_1"}, True),
            ({"OPENCODE_SESSION_ID": "ses_1", "CARTER_HUMAN_SHELL": "1"}, False),
            ({"OPENCODE_TERMINAL": "1"}, False),  # `unlock` (2b) cares; AD1 does not
            ({"CARTER_AGENT_SHELL": "0"}, False),  # only the exact value 1 is the strong marker
            ({"CARTER_HUMAN_SHELL": "1"}, False),
            ({"SSH_AUTH_SOCK": "/x", "HOME": "/h", "PATH": "/usr/bin"}, False),
        ],
    )
    def test_ad1_table(self, env: dict[str, str], expected: bool) -> None:
        assert is_agent(env) is expected
        assert is_agent_shell(env) is expected

    def test_no_broker_marker_is_honoured(self) -> None:
        assert is_agent({"CARTER_BROKER": "1"}) is False
        assert is_agent({"AGENT": "x", "CARTER_BROKER": "1"}) is True

    def test_every_agent_signal_in_the_data_file_is_honoured(self) -> None:
        # Parity: a name added to g2_rules.json must make a shell an agent shell.
        for name in rules.load_rules().agent_signals:
            value = "1" if name == "CARTER_AGENT_SHELL" else "x"
            assert is_agent({name: value}), name

    def test_every_human_signal_clears_the_weak_signals_only(self) -> None:
        weak = [n for n in rules.load_rules().agent_signals if n != "CARTER_AGENT_SHELL"]
        for human in rules.load_rules().human_signals:
            assert not is_agent({weak[0]: "x", human: "1"})
            assert is_agent({"CARTER_AGENT_SHELL": "1", human: "1"})

    def test_reads_the_process_environment_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert is_agent_shell() is False
        monkeypatch.setenv("AGENT", "x")
        assert is_agent_shell() is True


class TestRequireHumanTerminal:
    def test_a_human_on_a_real_tty_passes(self, pty_pair: io.TextIOBase) -> None:
        require_human_terminal("guard install", env={}, stdin=pty_pair, stdout=pty_pair)

    def test_agent_shell_is_refused_even_on_a_tty(self, pty_pair: io.TextIOBase) -> None:
        with pytest.raises(IdentityError) as exc:
            require_human_terminal(
                "guard install", env={"AGENT": "x"}, stdin=pty_pair, stdout=pty_pair
            )
        assert exc.value.code == E_HUMAN_TERMINAL

    def test_agent_shell_is_refused_even_when_a_tty_is_not_needed(self) -> None:
        with pytest.raises(IdentityError):
            require_human_terminal("guard install", need_tty=False, env={"AGENT": "x"})

    def test_no_tty_is_not_needed_for_the_scripted_path(self) -> None:
        require_human_terminal(
            "guard install", need_tty=False, env={}, stdin=io.StringIO(), stdout=io.StringIO()
        )

    def test_pipe_stdin_is_refused(self, pty_pair: io.TextIOBase) -> None:
        with pytest.raises(IdentityError, match="own terminal"):
            require_human_terminal("push", env={}, stdin=io.StringIO(), stdout=pty_pair)

    def test_dev_null_stdin_is_refused(self, pty_pair: io.TextIOBase) -> None:
        with open(os.devnull) as null, pytest.raises(IdentityError):
            require_human_terminal("push", env={}, stdin=null, stdout=pty_pair)

    def test_stdout_not_a_tty_is_refused(self, pty_pair: io.TextIOBase) -> None:
        with pytest.raises(IdentityError):
            require_human_terminal("push", env={}, stdin=pty_pair, stdout=io.StringIO())

    def test_the_streams_to_check_are_selectable(self, pty_pair: io.TextIOBase) -> None:
        # github-token set (F8): piped stdin is fine, a TTY on stderr is required.
        require_human_terminal(
            "github-token set",
            env={},
            streams=("stderr",),
            stdin=io.StringIO(),
            stderr=pty_pair,
        )
        with pytest.raises(IdentityError):
            require_human_terminal(
                "github-token set", env={}, streams=("stderr",), stderr=io.StringIO()
            )

    def test_defaults_come_from_sys_streams(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The pytest session has no TTY, so the real streams refuse.
        monkeypatch.setattr(sys, "stdin", io.StringIO())
        with pytest.raises(IdentityError):
            require_human_terminal("push", env={})


class TestMessage:
    def test_message_is_the_registry_text_with_the_appendix_b_suffix(self) -> None:
        message = registry()[E_HUMAN_TERMINAL].message
        assert SUFFIX in message
        with pytest.raises(IdentityError) as exc:
            require_human_terminal("push", env={"AGENT": "x"})
        assert str(exc.value) == message

    def test_detail_names_the_command_and_variable_names_but_never_values(self) -> None:
        secret = "s3cr3t-value-123"
        with pytest.raises(IdentityError) as exc:
            require_human_terminal(
                "guard install", env={"AGENT": secret, "OPENCODE_SESSION_ID": secret}
            )
        assert "guard install" in exc.value.detail
        assert "AGENT" in exc.value.detail and "OPENCODE_SESSION_ID" in exc.value.detail
        assert secret not in exc.value.detail and secret not in str(exc.value)

    def test_the_no_tty_detail_says_which_stream(self, pty_pair: io.TextIOBase) -> None:
        with pytest.raises(IdentityError) as exc:
            require_human_terminal("pr", env={}, stdin=io.StringIO(), stdout=pty_pair)
        assert "stdin" in exc.value.detail and "stdout" not in exc.value.detail


class TestModuleShape:
    def test_terminal_is_stdlib_plus_the_identity_package_only(self) -> None:
        tree = ast.parse(Path(terminal.__file__).read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
        outside = {
            n
            for n in names
            if n.split(".")[0] not in sys.stdlib_module_names
            and not n.startswith("carter.identity")
        }
        assert outside == set()
        assert not {"click", "jinja2", "yaml"} & {n.split(".")[0] for n in names}
