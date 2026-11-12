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
from carter.install.uninstall import uninstall

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


def test_edited_agent_and_skill_kept_unmodified_removed(installed: Path, capsys) -> None:
    oc = paths._opencode_base(installed)
    edited_agent = oc / "agents" / "carter-engineer.md"
    edited_agent.write_text(edited_agent.read_text() + "\nmine\n")
    edited_skill = next((oc / "skills").glob("carter-*/SKILL.md"))
    edited_skill.write_text(edited_skill.read_text() + "\nmine\n")
    other_agent = oc / "agents" / "carter-pm.md"

    uninstall(installed)

    assert edited_agent.exists()
    assert edited_skill.exists()
    assert not other_agent.exists()
    assert not any(d.is_dir() and not any(d.iterdir()) for d in (oc / "skills").iterdir())
    got = capsys.readouterr()
    out = got.out + got.err
    assert "carter-engineer.md" in out and "Kept" in out


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
        assert "rmtree" not in inspect.getsource(uninstall_mod)


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
