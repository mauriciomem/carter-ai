"""pull requests are allowed, not gated. ``carter pr``, ``carter_pr`` and the handoff are gone;
agents open, edit and comment with ``gh``; merging stays the human's; the token gains
``Pull requests: write`` and ``github-token check`` probes it."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from carter import ghtoken
from carter.cli import main
from carter.gate import check
from carter.identity.errors import registry
from carter.identity.policyset import agent_permission_denies, gh_allowlist
from gh_api import SPIKE_403, SPIKE_422, Reply

OWNED = "carter-llm/zz-probe-repo"


class TestRemoved:
    def test_carter_pr_is_not_a_command_but_push_is(self) -> None:
        assert "pr" not in main.commands and "push" in main.commands

    @pytest.mark.parametrize(
        "module",
        ["carter.aplus.pr", "carter.aplus.handoff", "carter.aplus.secretscan", "carter.broker.pr"],
    )
    def test_the_modules_are_gone(self, module: str) -> None:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)

    def test_the_codes_are_gone_from_the_registry(self) -> None:
        assert "E-HANDOFF" not in registry() and "E-SECRET-SCAN" not in registry()

    def test_the_broker_has_no_pr_verb(self) -> None:
        from carter import broker_cli

        assert broker_cli.run(["pr", "--plan"], {}, stdout=_Sink()) == broker_cli.EXIT_USAGE

    def test_the_only_broker_tool_denied_per_agent_is_push(self) -> None:
        assert agent_permission_denies() == ("carter_push",)

    def test_the_plugin_registers_no_pr_tool(self) -> None:
        root = Path(__file__).resolve().parents[1] / "carter" / "plugin"
        text = (root / "broker.ts").read_text() + (root / "core.ts").read_text()
        assert "carter_pr" not in text and "handoff" not in text

    def test_no_handoff_exclude_in_the_state_repo(self) -> None:
        from carter import state

        assert not hasattr(state, "HANDOFF_EXCLUDE")


class _Sink:
    def __init__(self) -> None:
        self.text = ""

    def write(self, value: str) -> None:
        self.text += value

    def flush(self) -> None:  # pragma: no cover - interface only
        pass


class TestGhAllowlist:
    def test_the_allowlist_gains_create_edit_and_comment_only(self) -> None:
        verbs = {v.verb for v in gh_allowlist()}
        assert {"pr create", "pr edit", "pr comment"} <= verbs
        assert not verbs & {"pr merge", "pr close", "pr review", "pr ready", "api"}

    @pytest.mark.parametrize(
        "command",
        [
            "gh pr create --title x --body y --head feat/x",
            "gh pr create --fill -R o/r",
            "gh pr edit 12 --add-label bug",
            "gh pr comment 12 --body done",
            "gh pr view 12",
        ],
    )
    def test_the_gate_lets_agents_open_edit_and_comment(self, command: str) -> None:
        assert check(command).decision == "allow", command

    @pytest.mark.parametrize(
        "command",
        [
            "gh pr merge 12",
            "gh pr merge 12 --squash",
            "gh pr close 12",
            "gh pr review 12 --approve",
            "gh pr ready 12",
            "gh api repos/o/r/pulls",
            "gh issue create --title x",
            "gh release create v1",
        ],
    )
    def test_the_human_decides_the_rest(self, command: str) -> None:
        assert check(command).decision == "deny", command

    def test_agent_permissions_deny_merge_not_create(self) -> None:
        from carter.config import generate_default_config, permission_rules

        rules = permission_rules(generate_default_config(), "engineer")
        shell = {r["resource"]: r["effect"] for r in rules if r["action"] == "shell"}
        assert shell["gh pr merge *"] == "deny" and shell["gh pr review *"] == "deny"
        for allowed in ("gh pr create *", "gh pr edit *", "gh pr comment *"):
            assert allowed not in shell, allowed


class TestTokenPullRequestProbe:
    @pytest.fixture
    def stored(self, tmp_path: Path) -> Path:
        ghtoken.store_token("github_pat_" + "A1b2C3d4" * 6, tmp_path)
        return tmp_path

    def levels(self, items):  # type: ignore[no-untyped-def]
        return {(i.area, i.level): i.text for i in items}

    def test_422_means_agents_can_open_prs(self, stored: Path, github_api) -> None:  # type: ignore[no-untyped-def]
        github_api.readonly_token_world(pulls=422)
        got = self.levels(ghtoken.check_token(stored))
        assert "agents can open PRs" in got[("pull requests", "ok")]
        assert ("write probe", "ok") in got  # contents stay read-only
        body = [r for r in github_api.requests if r.path == f"/repos/{OWNED}/pulls"]
        assert (
            len(body) == 1 and body[0].method == "POST" and json.loads(body[0].body or b"{}") == {}
        )

    def test_403_is_a_warning_with_the_permission_to_add(self, stored: Path, github_api) -> None:  # type: ignore[no-untyped-def]
        github_api.readonly_token_world(pulls=403)
        items = ghtoken.check_token(stored)
        (warn,) = [i for i in items if i.area == "pull requests"]
        assert warn.level == "warn" and "can't open PRs" in warn.text
        assert "Pull requests: write" in warn.fix
        assert not [i for i in items if i.level == "red"]

    def test_contents_write_is_still_red(self, stored: Path, github_api) -> None:  # type: ignore[no-untyped-def]
        github_api.readonly_token_world(pulls=422)
        github_api.on("POST", f"/repos/{OWNED}/git/refs", Reply(422, SPIKE_422))
        assert [i.area for i in ghtoken.check_token(stored) if i.level == "red"] == ["write probe"]

    def test_the_probe_never_names_the_repository(self, stored: Path, github_api) -> None:  # type: ignore[no-untyped-def]
        github_api.readonly_token_world(pulls=403)
        text = repr(ghtoken.check_token(stored))
        assert "zz-probe-repo" not in text and "carter-llm" not in text

    def test_an_unexpected_answer_is_an_info_not_a_failure(self, stored: Path, github_api) -> None:  # type: ignore[no-untyped-def]
        github_api.readonly_token_world(pulls=403)
        github_api.on("POST", f"/repos/{OWNED}/pulls", Reply(500, SPIKE_403))
        items = ghtoken.check_token(stored)
        assert not [i for i in items if i.level == "red"]


class TestWording:
    def test_the_rule_for_agents_names_gh_pr_create(self) -> None:
        from carter.aplus.push import OWN_TERMINAL
        from carter.install.components import _ATTRIBUTION_RULE

        assert "gh pr create" in _ATTRIBUTION_RULE and "carter pr" not in _ATTRIBUTION_RULE
        assert OWN_TERMINAL.startswith("Run `carter push`") and "carter pr" not in OWN_TERMINAL
