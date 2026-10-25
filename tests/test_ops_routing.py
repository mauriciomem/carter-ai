"""`ops:` routing: local steps anywhere, remote steps only via carter-devops (S-06/S-07/S-14)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPS_SKILL = (ROOT / "skills" / "carter-ops" / "SKILL.md").read_text()
MAESTRO = (ROOT / "templates" / "agents" / "carter-maestro.md.j2").read_text()


class TestOpsSkill:
    def test_has_non_devops_handoff_section(self):
        assert "If you are not carter-devops" in OPS_SKILL
        assert "handoff" in OPS_SKILL

    def test_outward_text_goes_through_narrator(self):
        assert "carter-narrator" in OPS_SKILL

    def test_no_curl_jira_path(self):
        assert "curl" not in OPS_SKILL
        assert "ATLASSIAN_API_TOKEN" not in OPS_SKILL
        assert "/rest/api/" not in OPS_SKILL

    def test_jira_points_to_atlassian_mcp(self):
        assert "carter-atlassian" in OPS_SKILL


class TestMaestroOpsRule:
    def test_ops_rule_routes_remote_steps_to_devops(self):
        line = next(ln for ln in MAESTRO.splitlines() if ln.startswith("- `carter-ops`"))
        assert "carter-devops" in line
        assert "Execute directly, do not delegate" not in line

    def test_gate_is_emitted_as_ask(self):
        assert "emits `gate` as `ask`" in MAESTRO


class TestOpsConfigHasNoJira:
    def test_config_has_no_jira_fields(self):
        from carter.ops.config import Config

        assert not any(f.startswith("jira") for f in Config.__dataclass_fields__)
