"""The 2a compatibility contract with the real plugin, gate and identity entry (plan 004 step 32).

RFC §4.9 and App C.8: every OpenCode dependency of G2, on the real binary and the mock model.
Opt-in (``CARTER_E2E=1``); runs on the primary binary and ``CARTER_E2E_OPENCODE_ALT``. Rows of C.8
that are already proven elsewhere are listed in ``notes.md`` (deny-before-hook: spike D; shell
hook order and polluted server with the prototype: spike C).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from e2e.g2 import (
    NAMES,
    PYTHON,
    bang,
    error_message,
    install_files,
    make,
    run_shell,
    status,
    wait_status,
)

pytestmark = pytest.mark.e2e

CORPUS = Path(__file__).resolve().parents[1] / "data" / "gate_corpus.yaml"
BYPASS = [c for c in yaml.safe_load(CORPUS.read_text())["cases"] if c["id"].startswith("s3-")]
ISOLATED = {"AGENT", "CARTER_AGENT_SHELL", "GH_TOKEN", "GIT_CONFIG_COUNT", "GIT_SSH_COMMAND"}
REFUSED = "Refused by the Carter command gate (rule `"


class TestIsolationInThePipeline:
    def test_agent_shell_is_isolated_and_the_bang_shell_is_not(
        self, rig_factory, opencode_bin
    ) -> None:
        rig = make(rig_factory, opencode_bin)
        names = set(run_shell(rig, NAMES).split())
        assert names >= ISOLATED and names.isdisjoint({"SSH_AUTH_SOCK", "GITHUB_TOKEN"})
        assert "CARTER_HUMAN_SHELL" not in names
        early = set(bang(rig, NAMES).split())
        assert "SSH_AUTH_SOCK" in early and not early & {"CARTER_AGENT_SHELL", "GH_TOKEN"}
        wait_status(rig, "passed")
        late = set(bang(rig, NAMES).split())  # the human tag only after a pass
        assert "CARTER_HUMAN_SHELL" in late and "SSH_AUTH_SOCK" in late
        assert not late & {"AGENT", "CARTER_AGENT_SHELL", "GH_TOKEN", "GIT_CONFIG_COUNT"}

    def test_subagent_shells_are_isolated_too(self, rig_factory, opencode_bin) -> None:
        rig = make(rig_factory, opencode_bin)
        sid = rig.new_session()
        rig.prompt(sid, f"TASK RUN {NAMES}")
        names = set(str(rig.wait_results(2)[0]["result"]).split())
        assert "CARTER_AGENT_SHELL" in names and "SSH_AUTH_SOCK" not in names

    def test_the_gh_token_is_the_dummy_without_a_pat_and_the_pat_with_one(
        self, rig_factory, opencode_bin
    ) -> None:
        rig = make(rig_factory, opencode_bin)
        doc = json.loads((rig.home / ".carter/isolation.json").read_text())
        assert run_shell(rig, "printenv GH_TOKEN").strip() == doc["plugin"]["gh_token_dummy"]
        secrets = rig.home / ".carter/secrets"
        secrets.mkdir(parents=True)
        fake = "github_pat_" + "A1b2C3d4E5" * 8
        (secrets / "gh-read.token").write_text(fake + "\n")
        (secrets / "gh-read.token").chmod(0o600)
        assert run_shell(rig, "printenv GH_TOKEN").strip() == fake  # a made-up value, test only


class TestGateInThePipeline:
    def test_each_of_the_16_bypass_forms_is_refused_with_the_model_visible_message(
        self, rig_factory, opencode_bin
    ) -> None:
        assert len(BYPASS) == 16
        rig = make(rig_factory, opencode_bin)
        witness = rig.ws / "ran"
        passed = []
        for case in BYPASS:
            message = error_message(run_shell(rig, f"{case['command']}; touch {witness}"))
            if not message.startswith(REFUSED):
                passed.append((case["id"], message[:80]))
        assert passed == [] and not witness.exists()

    def test_an_allowed_command_runs_and_a_crash_fails_closed(
        self, rig_factory, opencode_bin
    ) -> None:
        rig = make(rig_factory, opencode_bin)
        assert run_shell(rig, "echo allowed-ok").strip() == "allowed-ok"
        broken = make(rig_factory, opencode_bin, files=install_files(python_path="/nonexistent/py"))
        message = error_message(run_shell(broken, "echo should-not-run"))
        assert message.startswith(
            "E-GATE-FAIL: Command gate unavailable; command refused (fail closed)"
        )

    def test_prose_that_mentions_git_push_is_not_a_false_positive(
        self, rig_factory, opencode_bin
    ) -> None:
        """The mock model reads one line per prompt, so the multi-line heredoc idiom lives in the
        corpus (``ok-heredoc-commit``); this is its one-line form through the live pipeline."""
        rig = make(rig_factory, opencode_bin)
        out = run_shell(
            rig,
            'git commit --allow-empty -q -m "fix: mention git push and sudo"; '
            "git log -1 --format=%s",
        )
        assert out.strip() == "fix: mention git push and sudo"


class TestTamper:
    @pytest.mark.parametrize("how", ["delete", "wrong-hash", "unrendered", "byte-edit"])
    def test_the_agent_shell_is_refused_and_the_bang_shell_still_works(
        self, how: str, rig_factory, opencode_bin
    ) -> None:
        if how == "byte-edit":
            files = install_files()
            original = files[".carter/isolation.json"]
            files[".carter/isolation.json"] = lambda h: original(h).replace(
                '"GIT_TERMINAL_PROMPT":"0"', '"GIT_TERMINAL_PROMPT":"1"'
            )
        else:
            files = install_files(tamper=how)
        rig = make(rig_factory, opencode_bin, files=files)
        message = error_message(run_shell(rig, "echo should-not-run"))
        assert message.startswith("E-ISOLATION-MISSING: Carter isolation file is missing"), message
        assert bang(rig, "echo human-ok").strip() == "human-ok"


class TestSelfTestAndPollution:
    def test_a_polluted_server_gets_no_human_tag(self, rig_factory, opencode_bin) -> None:
        rig = make(rig_factory, opencode_bin, env={"AGENT": "1", "OPENCODE_SESSION_ID": "ses_x"})
        run_shell(rig, "true")
        wait_status(rig, "passed")
        assert "CARTER_HUMAN_SHELL" not in bang(rig, NAMES)
        assert "polluted" in status(rig)[0]["flags"]
        log = (rig.logs / "server.log").read_text(errors="replace")
        assert log.count("the server environment looks like an agent shell") == 1

    def test_a_second_plugin_that_rejects_after_ours_ends_in_failed(
        self, rig_factory, opencode_bin
    ) -> None:
        """Accepted residual E12 (spike C g3): the self-test cannot tell this from a broken
        order. The consequence is conservative: every shell, the human's ``!`` too, is tagged
        as an agent's."""
        files = install_files()
        files[".config/opencode/plugins/zz-reject/index.ts"] = lambda _h: (
            'import { Plugin } from "@opencode/plugin"\n'
            "export default Plugin.define({ id: 'zz', setup(ctx: any) {"
            " ctx.tool.hook('execute.before', () => { throw new Error('zz says no') }) } })\n"
        )
        rig = make(rig_factory, opencode_bin, files=files)
        run_shell(rig, "echo x")
        failed = wait_status(rig, "failed", timeout=8)
        assert failed["failed_reason"] == "timeout"
        assert "CARTER_HUMAN_SHELL" not in bang(rig, NAMES)
        assert "CARTER_AGENT_SHELL" in bang(rig, NAMES)


class TestIdentityEntry:
    def commit(self, rig) -> str:
        return run_shell(rig, "git commit --allow-empty -q -m probe && git log -1 --format=%G?")

    def test_at_t0_an_agent_commit_succeeds_unsigned(self, rig_factory, opencode_bin) -> None:
        rig = make(rig_factory, opencode_bin)
        assert self.commit(rig).strip() == "N"  # no signature
        wait_status(rig, "passed")

    def test_a_failing_identity_entry_blocks_agent_commits_but_not_the_human(
        self, rig_factory, opencode_bin
    ) -> None:
        """C.2: when the identity entry fails, ``blocking_git_config`` is appended (signing
        forced, every signer the root-owned ``false``): the agent commit fails, nothing unsigned."""
        wrapper = (
            f'#!/bin/sh\ncase "$*" in *carter.identity.env*) exit 2 ;; esac\nexec {PYTHON} "$@"\n'
        )
        rig = make(
            rig_factory,
            opencode_bin,
            files={
                **install_files(python_path=lambda home: f"{home}/pywrap"),
                "pywrap": lambda _h: wrapper,
            },
            executable=["pywrap"],
        )
        out = run_shell(rig, "git commit --allow-empty -q -m blocked; echo rc=$?")
        assert "rc=0" not in out, out
        human = bang(rig, "git commit --allow-empty -q -m human; echo rc=$?")
        assert human.strip().endswith("rc=0")


def test_the_status_file_names_the_server(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    run_shell(rig, "true")
    (row,) = status(rig)
    assert row["opencode_version"] == opencode_bin.version and row["pid"] > 0
