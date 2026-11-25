"""The managed file is a control path: edit deny, shell refusal, `config-edit` revision 2."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from carter.cli import main
from carter.gate.data import rules as gate_rules
from carter.guard import consent
from carter.guard.state import GuardState, load, save
from carter.identity.policyset import consent_groups, policy_statements
from carter.identity.rules import load_rules
from carter.install.paths import guard_state_path
from gate.helpers import rule_of
from guard.helpers import verbose
from guard.test_optouts import glob

MANAGED = "~/.carter/config-managed.toml"
GROUP = "config-edit"


def guard(*args: str, **kw):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def verdict(statements, path: str) -> str:  # type: ignore[no-untyped-def]
    """What the edit tool gets for ``path``: the last matching rule wins, default allow."""
    got = "allow"
    for s in statements:
        if s.resource.startswith("edit:") and glob(s.resource, f"edit:{path}"):
            got = s.effect
    return got


class TestTheDataFile:
    def test_the_file_is_a_control_path(self) -> None:
        assert MANAGED in load_rules().control_paths
        assert MANAGED in gate_rules()["control"]

    def test_it_has_its_own_edit_deny_in_config_edit(self, tmp_path: Path) -> None:
        got = {s.id: s for s in policy_statements([GROUP], home=str(tmp_path))}
        rule = got["deny-edit-carter-managed"]
        assert rule.group == GROUP and rule.effect == "deny"
        assert rule.resource == f"edit:{tmp_path}/.carter/config-managed.toml"
        assert "deny-edit-carter-config" in got  # config.toml keeps its own deny

    def test_every_control_path_file_of_the_carter_folder_has_an_edit_deny(self) -> None:
        """Both lists agree: nothing in `control_paths` under ~/.carter is left to the shell
        rule alone."""
        denied = " ".join(s.resource for s in policy_statements([GROUP], home="/h"))
        for entry in load_rules().control_paths:
            if entry.startswith("~/.carter/") and not entry.endswith("/"):
                assert f"/h/.carter/{entry.removeprefix('~/.carter/')}" in denied, entry

    def test_config_edit_is_on_by_default_and_at_revision_two(self) -> None:
        (group,) = [g for g in consent_groups() if g.id == GROUP]
        assert group.rev == 2 and not group.optional  # offered with the default groups
        assert GROUP in consent.group_names()


class TestTheShellAndTheEditTool:
    def test_the_gate_refuses_shell_writes(self) -> None:
        for cmd in (
            f"echo x > {MANAGED}",
            f"tee {MANAGED}",
            f"sed -i s/a/b/ {MANAGED}",
            f"cp a {MANAGED}",
            f"mv a {MANAGED}",
            f"rm {MANAGED}",
            f"chmod 666 {MANAGED}",
            f"ln -sf /tmp/x {MANAGED}",
        ):
            assert rule_of(cmd) == "control-files", cmd

    def test_an_edit_tool_write_is_denied_with_the_group_installed(self, tmp_path: Path) -> None:
        state = GuardState()
        state.consent(GROUP, "accepted", "2026-11-23", 2)
        state.consent("g2", "accepted", "2026-11-23", 3)
        statements = consent.desired_statements(state, home=str(tmp_path))
        assert verdict(statements, f"{tmp_path}/.carter/config-managed.toml") == "deny"
        assert verdict(statements, f"{tmp_path}/.carter/config.toml") == "deny"

    def test_without_the_group_nothing_denies_it(self, tmp_path: Path) -> None:
        state = GuardState()
        state.consent(GROUP, "declined", "2026-11-23", 2)
        statements = consent.desired_statements(state, home=str(tmp_path))
        assert verdict(statements, f"{tmp_path}/.carter/config-managed.toml") == "allow"


class TestExistingUsersSeeOneNewRow:
    def accepted_at_revision_one(self) -> None:
        state = GuardState()
        for name in ("g2", "sudo-docker", "read-edit-denies", GROUP):
            state.consent(name, "accepted", "2026-11-03", 3 if name == "g2" else 1)
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        save(state, path)

    def test_the_question_has_one_new_row_for_the_group(self, stack, human_tty) -> None:
        self.accepted_at_revision_one()
        human_tty(True)
        stack.fake()
        res = guard("install", input="n\n")
        rows = [ln for ln in res.output.splitlines() if "new:" in ln]
        assert len(rows) == 1 and rows[0].split()[0] == GROUP, res.output
        assert "config-managed.toml" in rows[0] and all(len(r) <= 72 for r in rows)

    def test_a_yes_records_revision_two(self, stack, human_tty) -> None:
        self.accepted_at_revision_one()
        human_tty(True)
        stack.fake()
        assert guard("install", input="y\n").exit_code == 0
        assert load(guard_state_path(None)).consents[GROUP]["rev"] == 2

    def test_a_bare_yes_leaves_revision_one_alone(self, stack, human_tty) -> None:
        self.accepted_at_revision_one()
        human_tty(False)
        stack.fake()
        guard("install", "--yes")
        assert load(guard_state_path(None)).consents[GROUP]["rev"] == 1
