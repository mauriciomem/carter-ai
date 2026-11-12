"""`carter uninstall` must never delete user-edited or user-owned files."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from carter.install import mcp, orchestrator, paths
from carter.install import uninstall as uninstall_mod
from carter.install.components import _OPENCODE_AGENTS_MD
from carter.install.files import _sha256
from carter.install.uninstall import KeptRow, uninstall
from lifecycle.helpers import tree_diff, tree_snapshot

SEED = "patterns.md"


@pytest.fixture
def installed(base_dir: Path, fake_opencode) -> Path:
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=1)
    return base_dir


def _knowledge(base_dir: Path) -> Path:
    return paths.knowledge_dir(base_dir)


def _agents_md(base_dir: Path) -> Path:
    return paths._opencode_base(base_dir) / "AGENTS.md"


def test_edited_knowledge_is_kept(installed: Path, capsys) -> None:
    f = _knowledge(installed) / SEED
    f.write_text(f.read_text() + "\nmy note\n")
    uninstall(installed)
    assert f.exists()
    got = capsys.readouterr()
    assert "Kept" in got.out + got.err


def test_untouched_seed_knowledge_is_removed(installed: Path) -> None:
    f = _knowledge(installed) / SEED
    assert f.exists()
    uninstall(installed)
    assert not f.exists()


def test_preexisting_user_knowledge_is_never_removed(base_dir: Path, fake_opencode) -> None:
    f = _knowledge(base_dir) / SEED
    f.parent.mkdir(parents=True)
    f.write_text("my own patterns\n")
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=1)
    uninstall(base_dir)
    assert f.read_text() == "my own patterns\n"


def test_user_agents_md_skipped_at_install_is_kept(base_dir: Path, fake_opencode) -> None:
    f = _agents_md(base_dir)
    f.parent.mkdir(parents=True)
    f.write_text("# my rules\n")
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=1)
    uninstall(base_dir)
    assert f.read_text() == "# my rules\n"


def test_carter_agents_md_unmodified_is_removed(installed: Path) -> None:
    f = _agents_md(installed)
    assert f.read_text() == _OPENCODE_AGENTS_MD
    uninstall(installed)
    assert not f.exists()


def test_agents_md_edited_after_install_is_kept(installed: Path) -> None:
    f = _agents_md(installed)
    f.write_text(f.read_text() + "\n- my rule\n")
    uninstall(installed)
    assert f.exists()


def test_edited_skill_is_kept_and_edited_agent_is_removed_with_a_copy(
    installed: Path, capsys
) -> None:
    oc = paths._opencode_base(installed)
    edited_agent = oc / "agents" / "carter-engineer.md"
    edited_agent.write_text(edited_agent.read_text() + "\nmine\n")
    edited_skill = next((oc / "skills").glob("carter-*/SKILL.md"))
    edited_skill.write_text(edited_skill.read_text() + "\nmine\n")

    report = uninstall(installed)

    assert not edited_agent.exists()
    assert edited_skill.exists()
    assert not (oc / "agents" / "carter-pm.md").exists()
    assert not any(d.is_dir() and not any(d.iterdir()) for d in (oc / "skills").iterdir())
    got = capsys.readouterr()
    out = got.out + got.err
    assert "although you edited it" in out and "Kept" in out and edited_skill.name in out
    assert report.kept_files == [edited_skill]
    assert [a for a, _ in report.edited_copies] == [edited_agent]


def test_sibling_dir_prefix_is_not_matched(base_dir: Path) -> None:
    oc = paths._opencode_base(base_dir)
    sibling = oc.parent / (oc.name + "-foo") / "agents" / "carter-x.md"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("x")
    manifest = {
        "files": [str(sibling)],
        "file_hashes": {str(sibling): _sha256(sibling)},
        "mcp_servers": [],
    }
    paths.manifest_path(base_dir).parent.mkdir(parents=True, exist_ok=True)
    paths.manifest_path(base_dir).write_text(json.dumps(manifest))
    uninstall(base_dir)
    assert sibling.exists()


def test_old_manifest_without_hashes(installed: Path) -> None:
    mp = paths.manifest_path(installed)
    data = json.loads(mp.read_text())
    data.pop("file_hashes", None)
    # Older versions also listed pre-existing knowledge/AGENTS.md as owned.
    know = _knowledge(installed) / SEED
    data["files"].append(str(know))
    data["files"].append(str(_agents_md(installed)))
    mp.write_text(json.dumps(data))
    agent = paths._opencode_base(installed) / "agents" / "carter-pm.md"

    uninstall(installed)

    assert know.exists()
    assert _agents_md(installed).exists()
    assert not agent.exists()


def test_install_summary_counts_skill_directories(
    base_dir: Path, fake_opencode, capsys: pytest.CaptureFixture[str]
) -> None:
    """The summary counts skills (directories), not the files inside them."""
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=1)
    shipped = sum(1 for d in (paths.REPO_ROOT / "skills").iterdir() if (d / "SKILL.md").exists())
    assert f"{shipped} skills" in capsys.readouterr().out


class TestWithoutManifest:
    """No ``manifest.json``: remove the names this version ships, never a prefix or a tree."""

    @pytest.fixture
    def oc(self, installed: Path) -> Path:
        paths.manifest_path(installed).unlink()
        return paths._opencode_base(installed)

    def test_shipped_agents_and_skills_go_and_their_empty_dirs_with_them(
        self, installed: Path, oc: Path
    ) -> None:
        uninstall(installed)
        assert not list((oc / "agents").glob("carter-*.md"))
        assert not list((oc / "skills").glob("*/SKILL.md"))
        assert not any((oc / "skills").iterdir())

    def test_a_user_skill_and_a_retired_one_survive(self, installed: Path, oc: Path) -> None:
        for name in ("carter-mine", "carter-retired"):
            (oc / "skills" / name).mkdir()
            (oc / "skills" / name / "SKILL.md").write_text(name)
        (oc / "agents" / "carter-mine.md").write_text("mine")
        uninstall(installed)
        assert (oc / "skills" / "carter-mine" / "SKILL.md").read_text() == "carter-mine"
        assert (oc / "skills" / "carter-retired" / "SKILL.md").exists()
        assert (oc / "agents" / "carter-mine.md").read_text() == "mine"

    def test_an_extra_file_inside_a_shipped_skill_survives_with_its_directory(
        self, installed: Path, oc: Path
    ) -> None:
        extra = oc / "skills" / "carter-adr" / "my-notes.md"
        extra.write_text("notes")
        uninstall(installed)
        assert extra.read_text() == "notes"
        assert not (oc / "skills" / "carter-adr" / "SKILL.md").exists()

    def test_a_shipped_name_that_leaves_the_managed_roots_is_not_followed(
        self, installed: Path, oc: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "SKILL.md").write_text("not carter's")
        shipped = oc / "skills" / "carter-adr"
        for f in shipped.iterdir():
            f.unlink()
        shipped.rmdir()
        shipped.symlink_to(outside, target_is_directory=True)
        uninstall(installed)
        assert (outside / "SKILL.md").read_text() == "not carter's"

    def test_the_branch_deletes_no_directory_tree(self) -> None:
        for name in ("_remove_if_owned", "_shipped_paths", "uninstall"):
            assert "rmtree" not in inspect.getsource(getattr(uninstall_mod, name))


class TestIsDefaultConfig:
    """Uninstall may delete ``config.toml`` only if nothing in it was set by the user."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("schema = 2\n", True),
            ("", False),  # empty is "no file" to the reader; never claimed as default
            (
                'schema = 2\n[identity]\nrole = "co-author"\nlogin = ""\n[broker]\nmin_dwell_ms = 500\n',  # noqa: E501
                True,
            ),
            ('schema = 2\n[identity]\nlogin = "bot"\n', False),
            ('schema = 2\n[workspaces."/w"]\nrole = "author"\n', False),
            ('schema = 2\n[attribution]\nfooter = "mine"\n', False),
            ('schema = 2\n[identity]\nsurprise = "x"\n', False),
            ("schema = 2\n[identity\n", False),
            ("schema = 3\n", False),
        ],
        ids=[
            "minimal",
            "empty",
            "fully-written",
            "login",
            "pin",
            "footer",
            "unknown",
            "broken",
            "future",
        ],
    )
    def test_default_means_the_parsed_value_not_the_text(
        self, tmp_path: Path, text: str, expected: bool
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text(text)
        assert uninstall_mod._is_default_config(path) is expected

    def test_a_missing_file_is_not_default(self, tmp_path: Path) -> None:
        assert uninstall_mod._is_default_config(tmp_path / "config.toml") is False

    def test_what_install_writes_is_default(self, installed: Path) -> None:
        assert uninstall_mod._is_default_config(paths.carter_config_path(installed)) is True


class TestMcpRemoval:
    def _config(self, base_dir: Path, servers: dict) -> Path:
        cfg = paths._opencode_base(base_dir) / "opencode.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"mcp": {"servers": servers}}))
        return cfg

    def test_only_the_names_carter_ships_are_removed(self, base_dir: Path) -> None:
        shipped = {f"carter-{n}": {"type": "remote"} for n in mcp.MCP_SERVERS}
        mine = {"carter-custom": {"type": "remote"}, "github": {"type": "remote"}}
        cfg = self._config(base_dir, {**shipped, **mine})
        assert sorted(mcp.remove_carter_servers(cfg)) == sorted(shipped)
        assert json.loads(cfg.read_text())["mcp"]["servers"] == mine


class TestStatuses:
    """``_remove_if_owned`` says what it did; the caller counts by kind."""

    def _file(self, base_dir: Path, name: str = "carter-x.md", text: str = "x") -> Path:
        f = paths._opencode_base(base_dir) / "agents" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        return f

    def _call(self, base_dir: Path, f: Path, recorded: str | None, copies=None):
        oc = paths._opencode_base(base_dir)
        roots = paths.managed_roots(base_dir)
        return uninstall_mod._remove_if_owned(f, recorded, roots, oc, copies)

    def test_matching_hash_is_removed(self, base_dir: Path) -> None:
        f = self._file(base_dir)
        assert self._call(base_dir, f, _sha256(f)) == "removed"
        assert not f.exists()

    def test_changed_hash_is_kept(self, base_dir: Path) -> None:
        f = self._file(base_dir)
        assert self._call(base_dir, f, "sha256:" + "0" * 64) == "kept"
        assert f.exists()

    def test_a_listed_copy_makes_it_edited_removed(self, base_dir: Path) -> None:
        f = self._file(base_dir)
        status = self._call(base_dir, f, "sha256:" + "0" * 64, {f: base_dir / "copy"})
        assert status == "edited-removed" and not f.exists()

    def test_no_hash_and_not_carters_by_name_is_kept(self, base_dir: Path) -> None:
        f = self._file(base_dir, "mine.md")
        assert self._call(base_dir, f, None) == "kept"

    def test_absent_and_outside_the_roots_are_skipped(self, base_dir: Path, tmp_path: Path) -> None:
        assert self._call(base_dir, base_dir / "nope.md", None) == "skipped"
        outside = tmp_path / "elsewhere" / "carter-x.md"
        outside.parent.mkdir()
        outside.write_text("x")
        assert self._call(base_dir, outside, _sha256(outside)) == "skipped"
        assert outside.exists()


class TestReport:
    def test_counts_by_kind_skills_count_directories(self, installed: Path) -> None:
        shipped_skills = sum(
            1 for d in (paths.REPO_ROOT / "skills").iterdir() if (d / "SKILL.md").exists()
        )
        knowledge = len(list(_knowledge(installed).glob("*.md")))
        report = uninstall(installed)
        assert report.removed == {
            "agents": 8,
            "skills": shipped_skills,
            "knowledge": knowledge,
            "AGENTS.md": 1,
        }
        assert report.code == 0 and report.edited_copies == [] and report.kept_files == []

    def test_a_second_uninstall_is_a_no_op(self, installed: Path) -> None:
        uninstall(installed)
        before = tree_snapshot(installed)
        again = uninstall(installed)
        assert tree_diff(before, tree_snapshot(installed)) == ""
        assert again.code == 0 and again.removed == {} and again.edited_copies == []
        assert again.kept == [] and not again.config_removed

    def test_kept_edited_knowledge_shows_as_a_kept_row(self, installed: Path) -> None:
        f = _knowledge(installed) / SEED
        f.write_text(f.read_text() + "\nmy note\n")
        report = uninstall(installed)
        assert report.kept_files == [f]
        assert report.kept == [KeptRow(_knowledge(installed), "files you edited or added", 1)]
        assert report.leftover is True

    def test_the_fixed_table_lists_only_what_is_there(self, installed: Path) -> None:
        carter = paths._carter_base(installed)
        (carter / "memories" / "user" / "me.md").write_text("m")
        (carter / "memories" / "repo" / "a").mkdir()
        (carter / "memories" / "repo" / "a" / "b.md").write_text("m")
        (carter / "secrets").mkdir()
        (carter / "secrets" / "gh-read.token").write_text("t")
        (carter / "state" / "audit").mkdir(parents=True)
        (carter / "state" / "audit" / "ops.log").write_text("l")
        (carter / "backups" / "20260101T000000").mkdir(parents=True)
        (carter / "backups" / "20260101T000000" / "f").write_text("b")
        rows = {r.path.relative_to(carter).as_posix(): r for r in uninstall(installed).kept}
        assert {k: v.count for k, v in rows.items()} == {
            "memories": 2,
            "secrets": 1,
            "state/audit": 1,
            "backups": 1,
        }
        assert rows["secrets"].reason == "revoke the token on GitHub too"

    def test_a_clean_install_leaves_nothing(self, installed: Path) -> None:
        report = uninstall(installed)
        assert report.kept == [] and report.leftover is False
        assert not paths._carter_base(installed).exists()

    @pytest.mark.parametrize(
        ("executable", "command"),
        [
            ("/home/u/.local/share/uv/tools/carter-ai/bin/python", "uv tool uninstall carter-ai"),
            (
                "/Users/u/Library/Application Support/uv/tools/carter-ai/bin/python",
                "uv tool uninstall carter-ai",
            ),
            ("/home/u/.local/pipx/venvs/carter-ai/bin/python", "pipx uninstall carter-ai"),
            ("/opt/homebrew/opt/carter-ai/libexec/bin/python", "brew uninstall carter-ai"),
            ("/usr/local/Cellar/carter-ai/1/libexec/bin/python", "brew uninstall carter-ai"),
            ("/usr/bin/python3", "pip uninstall carter-ai"),
            ("C:\\Users\\u\\AppData\\Roaming\\uv\\tools\\carter-ai\\Scripts\\python.exe",
             "uv tool uninstall carter-ai"),
        ],
    )  # fmt: skip
    def test_manager_command_comes_from_where_python_runs(
        self, executable: str, command: str
    ) -> None:
        assert uninstall_mod.manager_command(executable) == command

    def test_the_report_carries_the_running_manager(self, installed: Path) -> None:
        assert uninstall(installed).manager == uninstall_mod.manager_command()


class TestCleanup:
    def test_default_config_is_removed_and_a_changed_one_kept(self, installed: Path) -> None:
        config = paths.carter_config_path(installed)
        assert uninstall(installed).config_removed is True and not config.exists()

    def test_an_edited_config_is_kept_and_listed(self, installed: Path) -> None:
        config = paths.carter_config_path(installed)
        config.write_text('schema = 2\n[attribution]\nfooter = "mine"\n')
        report = uninstall(installed)
        assert report.config_removed is False
        assert config.read_text().endswith('footer = "mine"\n')
        assert KeptRow(config, "settings you changed", 1) in report.kept

    def test_run_is_removed_whole(self, installed: Path) -> None:
        run = paths.run_dir(installed)
        (run / "gh").mkdir(parents=True)
        (run / "b-rejections.json").write_text("{}")
        uninstall(installed)
        assert not run.exists()

    def test_a_guard_log_that_could_not_move_keeps_run(self, installed: Path) -> None:
        run = paths.run_dir(installed)
        run.mkdir(parents=True)
        (run / "guard.log").write_text("line\n")
        (paths._carter_base(installed) / "state").write_text("a file, so the move fails")
        uninstall(installed)
        assert (run / "guard.log").read_text() == "line\n"

    def test_empty_directories_carter_made_go_but_not_the_users(self, installed: Path) -> None:
        carter = paths._carter_base(installed)
        (carter / "memories" / "user" / "me.md").write_text("m")
        uninstall(installed)
        assert (carter / "memories" / "user" / "me.md").exists()
        assert not (carter / "memories" / "session").exists()
        assert not (carter / "knowledge").exists() and not (carter / "hooks").exists()

    def test_the_audit_log_the_backups_and_the_token_stay(self, installed: Path) -> None:
        carter = paths._carter_base(installed)
        keep = [carter / "state" / "audit" / "guard.log", carter / "secrets" / "gh-read.token"]
        keep.append(carter / "backups" / "20260101T000000" / "x")
        for f in keep:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("mine")
        uninstall(installed)
        assert all(f.read_text() == "mine" for f in keep)

    def test_opencode_json_that_ends_empty_is_removed(self, base_dir: Path) -> None:
        shipped = {f"carter-{n}": {"type": "remote"} for n in mcp.MCP_SERVERS}
        cfg = TestMcpRemoval()._config(base_dir, shipped)
        uninstall(base_dir)
        assert not cfg.exists()

    def test_opencode_json_with_other_keys_is_kept(self, base_dir: Path) -> None:
        cfg = TestMcpRemoval()._config(base_dir, {"carter-github": {}})
        data = json.loads(cfg.read_text())
        data["theme"] = "mine"
        cfg.write_text(json.dumps(data))
        uninstall(base_dir)
        assert json.loads(cfg.read_text()) == {"theme": "mine"}

    def test_a_users_empty_jsonc_is_not_removed_because_the_other_file_lost_servers(
        self, base_dir: Path
    ) -> None:
        cfg = TestMcpRemoval()._config(base_dir, {"carter-github": {}})
        mine = cfg.with_name("opencode.jsonc")
        mine.write_text("{}")
        report = uninstall(base_dir)
        assert report.mcp_servers == 1 and not cfg.exists() and mine.read_text() == "{}"

    def test_an_opencode_json_with_no_carter_server_is_not_touched(self, base_dir: Path) -> None:
        cfg = TestMcpRemoval()._config(base_dir, {})
        cfg.write_text("{}")
        uninstall(base_dir)
        assert cfg.read_text() == "{}"
