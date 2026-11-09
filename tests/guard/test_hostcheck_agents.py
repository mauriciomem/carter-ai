"""``check --host``: per-agent denies from ``opencode debug agents`` and the version bands
fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carter import harness
from carter import hostcheck_g2 as g2
from carter.guard.state import GuardState
from carter.install import prereqs

DATA = Path(__file__).resolve().parents[1] / "data"


def fixture(name: str):
    return json.loads((DATA / f"opencode-2.1.4-{name}.json").read_text("utf-8"))


def accepted() -> GuardState:
    st = GuardState()
    st.consent("g2", "accepted", "2026-11-04", 2)
    return st


def items(agents, state=None, loaded=None):
    return g2.agent_items(state or accepted(), lambda: agents, loaded, "/h/opencode.jsonc")


class TestAgentDenies:
    def test_a_complete_install_is_ok_and_devops_is_exempt(self) -> None:
        (item,) = items(fixture("debug-agents-denies"))
        assert item.level == "ok" and "9 agent(s)" in item.text

    def test_a_missing_rule_is_red_and_names_the_agent_and_the_action(self) -> None:
        agents = fixture("debug-agents-denies")
        build = next(a for a in agents if a["id"] == "build")
        build["permissions"] = [r for r in build["permissions"] if r["action"] != "carter_push"]
        (item,) = items(agents)
        assert item.level == "red" and "agent build: carter_push" in item.text

    def test_a_later_allow_is_a_gap(self) -> None:
        agents = fixture("debug-agents-denies")
        plan = next(a for a in agents if a["id"] == "plan")
        plan["permissions"].append({"action": "carter_*", "resource": "*", "effect": "allow"})
        got = items(agents)
        assert [i.text for i in got if i.level == "red"] == [
            "agent plan: carter_push is not denied in `opencode debug agents`",
        ]

    def test_a_dropped_entry_is_red_with_the_hint_and_the_agent_name(self) -> None:
        state = accepted()
        state.record_permission("build", "carter_push", "deny", preexisting=False)
        agents = fixture("debug-agents-denies")
        loaded = harness._resolve(fixture("debug-config-agent-dropped"))
        got = items(agents, state, loaded)
        dropped = [i for i in got if "dropped" in i.text]
        assert dropped and "agent build" in dropped[0].text and dropped[0].level == "red"
        assert "OpenCode drops an agent's whole config entry" in dropped[0].fix
        assert "agents.build" in dropped[0].fix and "/h/opencode.jsonc" in dropped[0].fix

    def test_the_config_file_check_stays_separate(self) -> None:
        from carter.hostcheck import _policies  # the file-level check still exists

        assert callable(_policies)

    def test_nothing_is_checked_without_g2(self) -> None:
        assert items(fixture("debug-agents-denies"), GuardState()) == []

    def test_an_unreadable_listing_is_a_warn(self) -> None:
        def broken():
            raise harness.DebugConfigError("exited 1")

        (item,) = g2.agent_items(accepted(), broken, None, "/c")
        assert item.level == "warn" and "cannot read `opencode debug agents`" in item.text

    def test_a_cold_start_empty_list_is_retried(self) -> None:
        import subprocess

        outputs = iter(["[]", "[]", json.dumps(fixture("debug-agents-denies"))])
        slept: list[float] = []

        def run(argv, **_kw):
            return subprocess.CompletedProcess(argv, 0, stdout=next(outputs), stderr="")

        agents = harness.read_agents(
            runner=run, which=lambda _c: "/x/opencode", sleep=slept.append, home=Path("/")
        )
        assert len(agents) == 9 and len(slept) == 2


class TestVersionBands:
    @pytest.mark.parametrize(
        ("version", "band"),
        [
            ((2, 0, 9), "too-old"),
            ((2, 1, 0), "untested-low"),
            ((2, 1, 3), "untested-low"),
            ((2, 1, 4), "tested"),
            ((2, 1, 5), "above"),
            ((2, 2, 0), "above"),
        ],
    )
    def test_the_band(self, version: tuple[int, int, int], band: str) -> None:
        assert prereqs.version_band(version) == band
        assert prereqs.TESTED_OPENCODE == (2, 1, 4)

    @pytest.mark.parametrize(
        ("version", "level"),
        [((2, 0, 9), "red"), ((2, 1, 2), "warn"), ((2, 1, 4), "ok"), ((2, 3, 0), "warn")],
    )
    def test_host_levels(self, version: tuple[int, int, int], level: str) -> None:
        (item,) = g2.version_items(version, None)
        assert item.level == level
        if level == "warn":
            assert (
                "E-OPENCODE-VERSION" in item.text
                and "relying on the plugin's own check" in item.text
            )

    def test_old_git_is_a_warn_with_the_registered_text(self) -> None:
        (item,) = g2.version_items(None, (2, 39))
        assert item.level == "warn" and "E-GIT-OLD" in item.text and "2.54" in item.text
        assert g2.version_items(None, (2, 56)) == []

    def test_the_install_warns_on_the_same_bands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        messages: list[tuple] = []
        monkeypatch.setattr(prereqs, "log_warn", lambda *a: messages.append(a))
        monkeypatch.setattr(prereqs, "log_ok", lambda *a: messages.append(("ok", *a)))
        monkeypatch.setattr(prereqs, "_which", lambda _c: "/x/opencode")
        monkeypatch.setattr(prereqs, "_cmd_version", lambda *_a, **_k: "opencode v2.1.2")
        assert prereqs.require_opencode() == (2, 1, 2)
        assert messages and "the guards are untested on 2.1.2" in messages[0][-1]
        messages.clear()
        monkeypatch.setattr(prereqs, "_cmd_version", lambda *_a, **_k: "opencode v2.1.4")
        prereqs.require_opencode()
        assert messages[0][0] == "ok"
