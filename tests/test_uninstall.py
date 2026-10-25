"""`carter uninstall` must never delete user-edited or user-owned files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carter.install import orchestrator, paths
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
    assert "Kept" in capsys.readouterr().out


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
    out = capsys.readouterr().out
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
    assert f"  Skills: {shipped}\n" in capsys.readouterr().out
