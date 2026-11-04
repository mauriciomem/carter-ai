"""``carter-guard`` and its self-contained hook command (plan 004 step 22; RFC-0007 §4.4, C.6.4).

Every case runs the real script under ``dash`` and ``bash --posix`` (macOS ``/bin/sh`` joins in
step 38). The AD1 vectors are the shared ones of ``tests/data/plugin_vectors.json``; the Python
oracle is ``carter.identity.rules.is_agent``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from carter.guard import hooks
from carter.guard.state import GuardState
from carter.identity.errors import registry
from carter.identity.rules import is_agent

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "plugin_vectors.json").read_text("utf-8")
)["ad1"]
SHELLS = [
    pytest.param(["dash"], id="dash"),
    pytest.param(["bash", "--posix"], id="bash-posix"),
    pytest.param(["/bin/sh"], id="bin-sh"),  # macOS: the system sh is the one git hooks run under
]
BASE_PATH = "/usr/bin:/bin"
GIT_RUN = '%s "$@"'  # how git runs a configured hook command: the arguments are appended


@pytest.fixture(params=SHELLS)
def sh(request: pytest.FixtureRequest) -> list[str]:
    argv: list[str] = request.param
    if shutil.which(argv[0]) is None:
        pytest.skip(f"{argv[0]} is not installed")
    return [shutil.which(argv[0]) or argv[0], *argv[1:]]


@pytest.fixture
def script(tmp_path: Path) -> Path:
    path = tmp_path / "hooks" / "carter-guard"
    path.parent.mkdir()
    path.write_text(hooks.render_script())
    path.chmod(0o755)
    return path


def run(argv: list[str], env: dict[str, str], tmp: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        env={"PATH": BASE_PATH, **env},
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp,
        stdin=subprocess.DEVNULL,
    )


class TestAd1Vectors:
    @pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["name"])
    def test_the_script_agrees_with_the_python_oracle(
        self, vector: dict, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        assert is_agent(vector["env"]) is vector["agent"]
        done = run([*sh, str(script), "is-agent"], vector["env"], tmp_path)
        assert (done.returncode == 0) is vector["agent"], (vector["name"], done.stderr)
        assert done.stdout == "" and done.stderr == ""

    @pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["name"])
    def test_the_inline_wrapper_agrees_too(
        self, vector: dict, sh: list[str], tmp_path: Path
    ) -> None:
        command = hooks.hook_command(tmp_path / "no-such-script")
        done = run([*sh, "-c", GIT_RUN % command, "hook", "origin", "url"], vector["env"], tmp_path)
        assert (done.returncode == 1) is vector["agent"], (vector["name"], done.stderr)

    def test_a_forged_broker_marker_changes_nothing(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        for env in (
            {"AGENT": "1", "CARTER_BROKER": "1"},
            {"CARTER_AGENT_SHELL": "1", "CARTER_BROKER": "1"},
        ):
            assert run([*sh, str(script), "pre-push"], env, tmp_path).returncode == 1
        assert run([*sh, str(script), "pre-push"], {"CARTER_BROKER": "1"}, tmp_path).returncode == 0


class TestPrePush:
    def test_an_agent_push_is_blocked_with_the_registered_text(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        done = run([*sh, str(script), "pre-push", "origin", "url"], {"AGENT": "1"}, tmp_path)
        entry = registry()["E-PUSH-GUARD"]
        head = entry.message.split("<reason>")[0]
        assert done.returncode == 1 and done.stdout == ""
        assert done.stderr.startswith(head + "AGENT is set)")
        assert entry.remediation in done.stderr and "carter push" in done.stderr

    def test_the_reason_names_the_signal_never_a_value(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        done = run(
            [*sh, str(script), "pre-push"], {"OPENCODE_SESSION_ID": "ses_SECRET123"}, tmp_path
        )
        assert "OPENCODE_SESSION_ID is set" in done.stderr and "SECRET123" not in done.stderr

    def test_a_human_push_passes_silently(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        for env in ({}, {"CARTER_HUMAN_SHELL": "1"}, {"OPENCODE_TERMINAL": "1"}):
            done = run([*sh, str(script), "pre-push", "origin", "url"], env, tmp_path)
            assert (done.returncode, done.stdout, done.stderr) == (0, "", "")

    def test_the_strong_marker_blocks_even_with_the_human_tag(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        env = {"CARTER_AGENT_SHELL": "1", "CARTER_HUMAN_SHELL": "1"}
        done = run([*sh, str(script), "pre-push"], env, tmp_path)
        assert done.returncode == 1 and "CARTER_AGENT_SHELL=1" in done.stderr

    def test_a_scrubbed_agent_is_a_human_the_documented_ad1_limit(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        env = {"AGENT": "1", "CARTER_HUMAN_SHELL": "1"}
        assert run([*sh, str(script), "pre-push"], env, tmp_path).returncode == 0

    @pytest.mark.parametrize("event", ["", "x", "pre-rebase", "post-merge"])
    def test_unknown_events_exit_0(
        self, event: str, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        done = run([*sh, str(script), event], {"CARTER_AGENT_SHELL": "1"}, tmp_path)
        assert (done.returncode, done.stderr) == (0, "")


class TestWrapper:
    """The configured command is self-contained: a missing or broken script never blocks a human.

    A script that exits 0 is trusted (the file is edit-denied and gate-denied, C.1)."""

    def wrapper(self, sh: list[str], script: Path, env: dict[str, str], tmp: Path):
        command = GIT_RUN % hooks.hook_command(script)
        return run([*sh, "-c", command, "hook", "origin", "url"], env, tmp)

    def test_with_the_script_it_runs_the_script(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        agent = self.wrapper(sh, script, {"AGENT": "1"}, tmp_path)
        assert agent.returncode == 1 and agent.stderr.count("agent push blocked") == 1
        assert self.wrapper(sh, script, {}, tmp_path).returncode == 0

    @pytest.mark.parametrize("damage", ["missing", "not-executable", "crash", "syntax"])
    def test_a_damaged_script_blocks_only_agents(
        self, damage: str, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        if damage == "missing":
            script.unlink()
        elif damage == "not-executable":
            script.chmod(0o644)
        elif damage == "crash":
            script.write_text("#!/bin/sh\nexit 77\n")
        elif damage == "syntax":
            script.write_text("#!/bin/sh\nif then ((\n")
        human = self.wrapper(sh, script, {}, tmp_path)
        assert human.returncode == 0  # the damaged script may print; it never blocks a human
        assert self.wrapper(sh, script, {"CARTER_HUMAN_SHELL": "1"}, tmp_path).returncode == 0
        agent = self.wrapper(sh, script, {"OPENCODE": "1"}, tmp_path)
        assert agent.returncode == 1 and "agent push blocked (OPENCODE is set)" in agent.stderr

    def test_a_crashing_script_never_blocks_the_human(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        script.write_text("#!/bin/sh\nexit 1\n")  # even a script that always refuses
        assert self.wrapper(sh, script, {}, tmp_path).returncode == 0

    def test_the_human_path_makes_zero_git_calls(
        self, sh: list[str], script: Path, tmp_path: Path
    ) -> None:
        trap = tmp_path / "trap"
        trap.mkdir()
        log = tmp_path / "git-calls"
        (trap / "git").write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
        (trap / "git").chmod(0o755)
        for present in (True, False):
            if not present:
                script.unlink()
            for argv in (
                [*sh, "-c", GIT_RUN % hooks.hook_command(script), "hook", "origin", "url"],
                [*sh, str(script), "pre-push", "origin", "url"] if present else None,
            ):
                if argv is None:
                    continue
                done = subprocess.run(
                    argv,
                    env={"PATH": f"{trap}:{BASE_PATH}"},
                    capture_output=True,
                    text=True,
                    cwd=tmp_path,
                )
                assert done.returncode == 0
        assert not log.exists()

    def test_the_hook_arguments_reach_the_script(self, sh: list[str], tmp_path: Path) -> None:
        marker = tmp_path / "args"
        fake = tmp_path / "carter-guard"
        fake.write_text(f'#!/bin/sh\necho "$@" > {marker}\nexit 0\n')
        fake.chmod(0o755)
        self.wrapper(sh, fake, {}, tmp_path)
        assert marker.read_text().strip() == "pre-push origin url"

    def test_a_path_with_spaces_and_quotes_is_quoted(self, sh: list[str], tmp_path: Path) -> None:
        odd = tmp_path / "it's a dir; rm -rf x"
        odd.mkdir()
        fake = odd / "carter-guard"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        assert self.wrapper(sh, fake, {"AGENT": "1"}, tmp_path).returncode == 0


class TestPortability:
    def code_lines(self) -> list[str]:
        text = hooks.render_script()
        return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]

    def test_no_bashisms(self) -> None:
        bad = (
            r"\[\[",
            r"\blocal\b",
            r"\bfunction\b",
            r"echo -e",
            r"\$'",
            r"<<<",
            r"=\(",
            r"\bsource\b",
            r"&>",
            r"\$\{[^}]*[:/#%][^}]*\}.*\$\{!",
            r"\bdeclare\b",
            r"\bselect\b",
        )
        for line in self.code_lines() + hooks.wrapper_statements("/x"):
            for pattern in bad:
                assert not re.search(pattern, line), (pattern, line)

    def test_the_human_path_has_no_external_command_and_no_git(self) -> None:
        # the part of the script that runs before an agent is known: up to Carter's git file
        lines = self.code_lines()
        human = lines[: next(i for i, ln in enumerate(lines) if ln.startswith("cfg="))]
        code = re.sub(r"'[^']*'", "''", "\n".join(human))  # message text is data
        words = set(re.findall(r"(?<![\w$-])([a-z][a-z-]+)(?=\s|$|;)", code))
        for cmd in (
            "git",
            "stat",
            "sed",
            "awk",
            "grep",
            "timeout",
            "cat",
            "date",
            "env",
            "readlink",
        ):
            assert cmd not in words, cmd

    def test_shellcheck_when_available(self, tmp_path: Path) -> None:
        tool = shutil.which("shellcheck")
        if tool is None:
            pytest.skip("shellcheck is not installed")
        path = tmp_path / "carter-guard"
        path.write_text(hooks.render_script())
        done = subprocess.run([tool, "-s", "sh", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, done.stdout

    def test_the_script_parses_under_both_shells(self, sh: list[str], tmp_path: Path) -> None:
        path = tmp_path / "carter-guard"
        path.write_text(hooks.render_script())
        assert subprocess.run([*sh, "-n", str(path)]).returncode == 0
        assert subprocess.run([*sh, "-n", "-c", hooks.hook_command("/x")]).returncode == 0


class TestRender:
    def test_byte_deterministic_with_the_header(self) -> None:
        first = hooks.render_script()
        assert first == hooks.render_script()
        assert first.startswith("#!/bin/sh\n# Managed by Carter")
        assert "@@" not in first
        assert hooks.hook_command("/a b/c") == hooks.hook_command("/a b/c")

    def test_the_command_is_one_line_with_no_external_command(self) -> None:
        command = hooks.hook_command("/h/.carter/hooks/carter-guard")
        code = re.sub(r"'[^']*'", "''", command)  # message text is data
        assert "\n" not in command and "git" not in code.replace("carter-guard", "")

    def test_the_hook_entries_use_the_registered_names(self) -> None:
        entries = dict(hooks.hook_entries("/h/carter-guard"))
        assert entries["hook.carter-guard-pre-push.event"] == "pre-push"
        assert entries["hook.carter-guard-pre-push.command"].startswith("g=/h/carter-guard;")

    def test_install_writes_0755_and_records_the_hash(self, tmp_path: Path) -> None:
        state = GuardState()
        assert hooks.install_script(tmp_path, state) == "created"
        path = hooks.script_path(tmp_path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
        assert state.owned_unchanged(path) and state.guard_version == hooks.GUARD_VERSION
        assert hooks.install_script(tmp_path, state) == "unchanged"

    def test_an_edited_script_is_kept(self, tmp_path: Path) -> None:
        state = GuardState()
        hooks.install_script(tmp_path, state)
        path = hooks.script_path(tmp_path)
        path.write_text(path.read_text() + "# mine\n")
        assert hooks.install_script(tmp_path, state) == "edited-kept"
        assert path.read_text().endswith("# mine\n")
        assert hooks.install_script(tmp_path, state, overwrite_edited=True) == "updated"

    def test_a_signal_name_that_is_not_a_plain_variable_is_refused(self) -> None:
        with pytest.raises(ValueError):
            hooks._name("A;rm -rf /")

    def test_the_script_in_the_wheel_directory_is_found(self) -> None:
        assert os.path.exists(Path(hooks.__file__).parent / "templates" / "carter-guard.sh")
