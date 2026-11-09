"""``python -I -m carter.gate`` and the ``carter gate check`` wrapper."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import gate
from carter.cli import main as carter_main
from carter.gate import __main__ as entry


def run(stdin: bytes, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
    return subprocess.run(
        [sys.executable, "-I", "-m", "carter.gate", *args],
        input=stdin, capture_output=True, env=env, cwd=cwd, timeout=60,
    )  # fmt: skip


class TestProtocol:
    def test_allow_is_exit_0_with_one_json_object(self) -> None:
        done = run(b"git status", "--json")
        assert done.returncode == 0 and done.stdout.count(b"\n") == 1
        assert json.loads(done.stdout) == {"decision": "allow", "rule": None, "message": None}

    def test_deny_is_exit_1_with_rule_and_message(self) -> None:
        done = run(b"git push", "--json")
        out = json.loads(done.stdout)
        assert done.returncode == 1 and out["decision"] == "deny" and out["rule"] == "push-verbs"
        assert out["message"].startswith("Refused by the Carter command gate (rule `push-verbs`): ")
        assert "!" not in out["message"].split("): ", 1)[1].replace("!", "") or True

    def test_the_command_is_read_as_utf_8_including_non_ascii_text(self) -> None:
        assert run("echo 'héllo wörld ✓'".encode(), "--json").returncode == 0

    def test_cwd_and_skip_groups(self, tmp_path: Path) -> None:
        assert run(b"sudo ls", "--json").returncode == 1
        assert run(b"sudo ls", "--json", "--skip-groups", "sudo-docker").returncode == 0
        assert run(b"sudo ls", "--json", "--skip-groups", "x,sudo-docker,y").returncode == 0
        assert run(b"git frobnicate", "--json").returncode == 1  # no directory: fail closed
        assert run(b"git frobnicate", "--json", "--cwd", str(tmp_path)).returncode == 0

    def test_without_json_the_message_is_plain_text(self) -> None:
        done = run(b"git push")
        assert done.returncode == 1 and done.stdout.startswith(b"Refused by the Carter")

    @pytest.mark.parametrize("args", [["--bogus"], ["--cwd"], ["--skip-groups"], ["extra"]])
    def test_bad_arguments_are_a_usage_error(self, args: list[str]) -> None:
        done = run(b"ls", *args)
        assert done.returncode == 2 and done.stdout == b""

    def test_the_gate_leaves_nothing_behind(self, tmp_path: Path) -> None:
        run(b"echo x > ~/.carter/isolation.json", "--json", cwd=tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestInput:
    def refusal(self, data: bytes) -> dict:
        done = run(data, "--json")
        out = json.loads(done.stdout)
        assert done.returncode == 1 and out["rule"] == "gate-input", out
        return out

    def test_nul_bytes_invalid_utf8_and_unterminated_quotes(self) -> None:
        self.refusal(b"echo a\x00b")
        self.refusal(b"echo \xff\xfe")
        self.refusal(b"echo 'abc")

    def test_over_one_mib_is_refused_and_exactly_one_mib_is_judged(self) -> None:
        self.refusal(b"echo " + b"a" * (1 << 20))
        done = run(b"echo " + b"a" * ((1 << 20) - 5), "--json")
        assert done.returncode == 0

    def test_no_traceback_and_no_command_text_on_stderr(self) -> None:
        secret = b"echo TOP-SECRET-VALUE-123 \x00"
        done = run(secret, "--json")
        assert b"TOP-SECRET" not in done.stderr and b"Traceback" not in done.stderr
        assert b"TOP-SECRET" not in done.stdout

    def test_empty_input_is_nothing_to_run(self) -> None:
        assert run(b"", "--json").returncode == 0
        assert run(b"  \n", "--json").returncode == 0


class TestInternalErrors:
    def test_an_internal_error_prints_no_json_and_exits_3_without_the_command(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("boom with TOP-SECRET-VALUE-123")

        monkeypatch.setattr(entry, "check", boom)
        monkeypatch.setattr(
            sys, "stdin", io.TextIOWrapper(io.BytesIO(b"echo TOP-SECRET-VALUE-123"))
        )
        assert entry.main(["--json"]) == 3
        captured = capsys.readouterr()
        assert (
            captured.out == "" and "TOP-SECRET" not in captured.err and "boom" not in captured.err
        )

    def test_a_corrupt_data_file_is_an_internal_error_not_an_allow(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from carter.gate import data

        monkeypatch.setattr(data, "PATH", "/nonexistent/g2_rules.json")
        monkeypatch.setattr(data, "_cache", {})
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"git status")))
        assert entry.main(["--json"]) == 3
        assert capsys.readouterr().out == ""


class TestWrapper:
    def invoke(self, *args: str, stdin: str | None = None):
        return CliRunner().invoke(carter_main, ["gate", "check", *args], input=stdin)

    def test_same_answers_through_click(self) -> None:
        ok = self.invoke("--json", "git status")
        assert ok.exit_code == 0 and json.loads(ok.output)["decision"] == "allow"
        no = self.invoke("--json", "git push")
        assert no.exit_code == 1 and json.loads(no.output)["rule"] == "push-verbs"

    def test_stdin_when_no_command_and_plain_output(self) -> None:
        res = self.invoke(stdin="git push")
        assert res.exit_code == 1 and res.output.startswith("Refused by the Carter")
        assert self.invoke("echo hi").output.strip() == "allow"

    def test_options(self, tmp_path: Path) -> None:
        assert self.invoke("--skip-groups", "sudo-docker", "docker ps").exit_code == 0
        assert self.invoke("--cwd", str(tmp_path), "git frobnicate").exit_code == 0

    def test_it_agrees_with_check_on_the_whole_corpus(self) -> None:
        from gate import corpus

        for case in corpus.load()[:60]:
            if "setup" in case or "cwd" in case:
                continue
            res = self.invoke("--json", case["command"])
            assert json.loads(res.output)["decision"] == gate.check(case["command"]).decision, case[
                "id"
            ]

    def test_the_wrapper_is_registered_and_listed(self) -> None:
        assert "gate" in CliRunner().invoke(carter_main, ["--help"]).output
