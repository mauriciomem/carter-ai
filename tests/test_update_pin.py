"""``carter update`` pins ``carter.yaml identity.role``/``require_tier``.

Nothing in carter.yaml changes attribution at runtime: only a human-run ``update`` copies
the policy into ``~/.carter/config.toml [workspaces."<abs path>"]``.
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from carter.cli import main
from carter.ops.config import Config

EMAIL = "12345+llm-bot@users.noreply.github.com"
T1 = f'schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\nemail = "{EMAIL}"\n'


@pytest.fixture
def home() -> Path:
    return Path(os.environ["HOME"])


@pytest.fixture
def cfg_path(home: Path) -> Path:
    return home / ".carter" / "config.toml"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    result = CliRunner().invoke(main, ["init", str(path), "--no-git-state"])
    assert result.exit_code == 0, result.output
    return path


def set_policy(ws: Path, **identity) -> None:
    yml = ws / ".carter" / "carter.yaml"
    data = yaml.safe_load(yml.read_text())
    data["identity"] = identity
    yml.write_text(yaml.dump(data))


def update(ws: Path, *args: str, env: dict[str, str] | None = None):
    """``carter update`` asks nothing (); ``-v`` shows the details these tests read."""
    return CliRunner().invoke(main, ["update", "-v", str(ws), *args], env=env)


def pinned(cfg_path: Path, ws: Path) -> dict:
    doc = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return doc.get("workspaces", {}).get(str(ws.resolve()), {})


def snap(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


class TestPinning:
    def test_yes_pins_role_and_require_tier_under_the_resolved_path(self, ws, cfg_path):
        set_policy(ws, role="author", require_tier="t2")

        result = update(ws, "--yes")

        assert result.exit_code == 0, result.output
        assert pinned(cfg_path, ws) == {
            "allow_project_opencode_edit": False,
            "role": "author",
            "require_tier": "t2",
        }

    def test_shows_the_change_and_its_source(self, ws, cfg_path):
        set_policy(ws, role="author", require_tier="t2")
        out = update(ws, "--yes").output
        assert "role" in out and "author" in out
        assert "(unset) -> author" in out
        assert "require_tier" in out and "t2" in out
        assert "carter.yaml" in out  # the source
        assert str(ws.resolve()) in out

    def test_only_role_set(self, ws, cfg_path):
        set_policy(ws, role="co-author")
        update(ws, "--yes")
        assert pinned(cfg_path, ws).get("role") == "co-author"
        assert "require_tier" not in pinned(cfg_path, ws)

    def test_rerun_is_a_no_op(self, ws, cfg_path):
        set_policy(ws, role="author", require_tier="t2")
        update(ws, "--yes")
        before = snap(cfg_path)

        again = update(ws, "--yes")

        assert again.exit_code == 0
        assert snap(cfg_path) == before
        assert "already pinned" in again.output.lower()
        assert sorted(p.name for p in cfg_path.parent.iterdir()) == ["config.toml"]

    def test_no_policy_and_no_pin_touches_nothing(self, ws, cfg_path):
        result = update(ws, "--yes")
        assert result.exit_code == 0
        assert not cfg_path.exists()

    def test_hand_edited_fields_survive_a_pin(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(
            T1 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t1"\n'
            "allow_project_opencode_edit = true\n"
        )
        set_policy(ws, role="co-author", require_tier="t1")

        assert update(ws, "--yes").exit_code == 0

        entry = pinned(cfg_path, ws)
        assert entry["max_tier"] == "t1" and entry["allow_project_opencode_edit"] is True
        assert (entry["role"], entry["require_tier"]) == ("co-author", "t1")
        assert tomllib.loads(cfg_path.read_text())["identity"]["login"] == "llm-bot"

    def test_other_workspaces_are_untouched(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1 + '[workspaces."/somewhere/else"]\nrole = "author"\n')
        set_policy(ws, role="co-author")
        update(ws, "--yes")
        doc = tomllib.loads(cfg_path.read_text())
        assert doc["workspaces"]["/somewhere/else"]["role"] == "author"

    def test_removing_the_policy_from_yaml_unpins_after_confirmation(self, ws, cfg_path):
        set_policy(ws, role="author", require_tier="t2")
        update(ws, "--yes")
        set_policy(ws)

        out = update(ws, "--yes").output

        assert "author -> (unset)" in out
        assert pinned(cfg_path, ws) == {}  # the empty entry is dropped

    def test_unpin_keeps_a_hand_edited_cap(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(
            T1 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t0"\nrole = "author"\n'
        )
        set_policy(ws)
        update(ws, "--yes")
        assert pinned(cfg_path, ws) == {"allow_project_opencode_edit": False, "max_tier": "t0"}

    def test_the_file_stays_0600(self, ws, cfg_path):
        set_policy(ws, role="author")
        update(ws, "--yes")
        assert (cfg_path.stat().st_mode & 0o777) == 0o600


class TestCarterYamlIsInertUntilUpdate:
    def test_yaml_policy_changes_nothing_at_runtime(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1)
        set_policy(ws, role="author", require_tier="t2")  # no `carter update` yet

        res = Config.load(workspace=str(ws.resolve()))

        assert (res.role, res.role_source) == ("co-author", "default")
        assert res.commits == "allowed"

    def test_later_yaml_edits_are_inert_after_a_pin(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1)
        set_policy(ws, role="co-author")
        update(ws, "--yes")
        set_policy(ws, role="author")  # edited, not yet pinned

        res = Config.load(workspace=str(ws.resolve()))

        assert (res.role, res.role_source) == ("co-author", "workspace")

    def test_a_pinned_role_author_at_t1_is_reported_as_refused(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1)
        set_policy(ws, role="author")
        update(ws, "--yes")

        res = Config.load(workspace=str(ws.resolve()))

        assert res.role == "author"  # never downgraded
        assert (res.commits, res.refusal_reason) == ("refused", "E-ROLE-B-TIER")


class TestConfirmation:
    def test_dry_run_writes_nothing_and_says_what_would_be_pinned(self, ws, cfg_path):
        set_policy(ws, role="author", require_tier="t2")

        result = update(ws, "--dry-run")

        assert result.exit_code == 0
        assert not cfg_path.exists()
        assert "would pin" in result.output.lower()
        assert "(unset) -> author" in result.output

    def test_dry_run_with_yes_still_writes_nothing(self, ws, cfg_path):
        set_policy(ws, role="author")
        update(ws, "--dry-run", "--yes")
        assert not cfg_path.exists()

    def test_it_asks_nothing_so_no_terminal_and_no_yes_are_needed(self, ws, cfg_path):
        set_policy(ws, role="author")

        result = update(ws)  # no --yes, no TTY, no question

        assert result.exit_code == 0, result.output
        assert pinned(cfg_path, ws)["role"] == "author"
        assert "[y/N]" not in result.output
        assert "✓ updated" in result.output  # the rest of update runs too

    def test_an_agent_shell_never_pins(self, ws, cfg_path):
        set_policy(ws, role="author")
        result = update(ws, env={"AGENT": "1"})
        assert result.exit_code == 0
        assert not cfg_path.exists() and "agent shells never pin" in result.output

    def test_nothing_is_asked_when_nothing_changes(self, ws, cfg_path):
        set_policy(ws, role="author")
        update(ws)
        result = update(ws)
        assert result.exit_code == 0 and "already pinned" in result.output.lower()


class TestRefusals:
    def test_cap_below_require_tier_refuses_everything(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t1"\n')
        before = snap(cfg_path)
        set_policy(ws, require_tier="t2")

        result = update(ws, "--yes")

        assert result.exit_code == 1
        assert "max_tier" in result.output and "require_tier" in result.output
        assert snap(cfg_path) == before

    def test_role_author_next_to_a_cap_is_refused_and_nothing_is_written(self, ws, cfg_path):
        """role author needs T2, a cap is always below it; never downgraded."""
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t1"\n')
        before = snap(cfg_path)
        set_policy(ws, role="author")

        result = update(ws, "--yes")

        assert result.exit_code == 1
        assert "E-ROLE-B-TIER" in result.output and "max_tier" in result.output
        assert snap(cfg_path) == before

    def test_a_cap_added_by_hand_after_the_pin_is_refused_by_the_mirror_step(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1)
        set_policy(ws, role="author")
        assert update(ws, "--yes").exit_code == 0
        cfg_path.write_text(
            cfg_path.read_text().replace('role = "author"', 'role = "author"\nmax_tier = "t1"')
        )

        result = update(ws, "--yes")

        assert result.exit_code == 1 and "E-ROLE-B-TIER" in result.output

    def test_cap_equal_to_require_tier_is_fine(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(T1 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t1"\n')
        set_policy(ws, require_tier="t1")
        assert update(ws, "--yes").exit_code == 0

    def test_unmodelled_keys_refuse_with_the_diff_and_never_overwrite(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        text = T1 + "[extra]\nprecious = 1\n"
        cfg_path.write_text(text)
        set_policy(ws, role="author")

        result = update(ws, "--yes")

        assert result.exit_code == 1
        assert "precious" in result.output
        assert cfg_path.read_text() == text

    def test_broken_config_refuses_to_pin(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text("schema = 2\n[identity\n")
        set_policy(ws, role="author")
        result = update(ws, "--yes")
        assert result.exit_code == 1
        assert "E-CONFIG" in result.output or "invalid" in result.output
        assert cfg_path.read_text() == "schema = 2\n[identity\n"

    def test_broken_config_does_not_block_update_when_nothing_is_to_pin(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text("schema = 2\n[identity\n")
        assert update(ws, "--yes").exit_code == 0

    def test_a_config_with_old_keys_is_not_rewritten_and_the_keys_are_named(self, ws, cfg_path):
        cfg_path.parent.mkdir(parents=True)
        legacy = '[attribution]\nname = "x"\n'
        cfg_path.write_text(legacy)
        set_policy(ws, role="author")
        result = update(ws, "--yes")
        assert result.exit_code == 1
        assert "unknown key(s) `attribution.name`" in result.output
        assert cfg_path.read_text() == legacy

    def test_invalid_yaml_policy_stops_update(self, ws, cfg_path):
        set_policy(ws, role="root")
        result = update(ws, "--yes")
        assert result.exit_code != 0
        assert "identity.role" in result.output
        assert not cfg_path.exists()


class TestWorkspaceKey:
    def test_symlinked_workspace_pins_the_resolved_path(self, ws, cfg_path, tmp_path):
        link = tmp_path / "link"
        link.symlink_to(ws, target_is_directory=True)
        set_policy(ws, role="author")

        assert update(link, "--yes").exit_code == 0

        assert list(tomllib.loads(cfg_path.read_text())["workspaces"]) == [str(ws.resolve())]

    def test_non_ascii_and_awkward_paths_round_trip(self, tmp_path, cfg_path):
        odd = tmp_path / 'ñandú "q" [x] #y \\z 日本'
        odd.mkdir()
        assert CliRunner().invoke(main, ["init", str(odd), "--no-git-state"]).exit_code == 0
        set_policy(odd, role="author", require_tier="t1")

        assert update(odd, "--yes").exit_code == 0

        assert pinned(cfg_path, odd)["role"] == "author"
        res = Config.load(workspace=str(odd.resolve()))
        assert (res.role, res.role_source) == ("author", "workspace")


class TestRetiredKeysAreReported:
    def test_update_and_check_report_retired_keys_without_failing(self, ws):
        set_policy(ws, git_account="me", bot_name="acme-bot")
        yaml_path = ws / ".carter" / "carter.yaml"

        up = update(ws, "--yes")
        chk = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])

        assert up.exit_code == 0, up.output
        assert f"unknown key `identity.bot_name` in {yaml_path} → delete it" in up.output
        assert f"unknown key `identity.git_account` in {yaml_path} → delete it" in chk.output
        assert "Workspace OK" in chk.output  # a report, never an error
        assert "deprecated" not in up.output + chk.output

    def test_check_is_silent_for_a_policy_only_block(self, ws):
        set_policy(ws, role="author", require_tier="t1")
        chk = CliRunner().invoke(main, ["check", str(ws), "--no-harness"])
        assert "unknown key" not in chk.output


class TestWorkspaceLevelNoteOnly:
    """`carter update` mentions the workspace AGENTS.md only; the global note belongs to
    `carter install`."""

    OLD = (
        "- **Commits**: The user is the author (signed `-S`); credit Carter only with a "
        "`Co-authored-by:` trailer — never `--author`.\n"
    )

    def test_old_workspace_agents_md_gets_a_workspace_note(self, ws, home):
        agents = ws / "AGENTS.md"
        agents.write_text("# Mine\n" + self.OLD)

        out = update(ws, "--yes").output

        assert "AGENTS.md" in out and "not rewritten" in out
        assert "coauthor_trailer" in out  # the current workspace rule is shown
        assert agents.read_text() == "# Mine\n" + self.OLD  # never clobbered
        assert not (home / ".carter" / "upgrade-notes").exists()

    def test_the_global_rule_is_not_printed_by_update(self, ws):
        from carter.install.components import _ATTRIBUTION_RULE

        (ws / "AGENTS.md").write_text("# Mine\n" + self.OLD)
        assert _ATTRIBUTION_RULE not in update(ws, "--yes").output

    def test_a_fresh_workspace_has_nothing_to_report(self, ws):
        assert "not rewritten" not in update(ws, "--yes").output

    def test_a_workspace_with_the_commit_rule_but_no_push_rule_gets_the_push_rule(self, ws):
        from carter.aplus.push import OWN_TERMINAL

        agents = ws / "AGENTS.md"
        agents.write_text("# Mine\n- **Commits**: use the coauthor_trailer.\n")

        out = update(ws, "--yes").output

        assert "not rewritten" in out and OWN_TERMINAL in out
        assert "- **Pushing**" in out and "- **Commits**" not in out  # only what is missing
        assert agents.read_text() == "# Mine\n- **Commits**: use the coauthor_trailer.\n"

    def test_a_current_workspace_file_gets_no_note(self, ws):
        from carter.aplus.push import OWN_TERMINAL

        agents = ws / "AGENTS.md"
        agents.write_text(f"# Mine\ncoauthor_trailer\n{OWN_TERMINAL}\n")
        assert "not rewritten" not in update(ws, "--yes").output
