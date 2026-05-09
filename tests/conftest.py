"""Shared test fixtures for Carter installer tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Path to the Carter repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Temporary base directory for testing (overrides ~/.copilot etc.)."""
    return tmp_path


@pytest.fixture
def copilot_dir(base_dir: Path) -> Path:
    """Copilot install directory within the test base."""
    d = base_dir / "copilot"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def opencode_dir(base_dir: Path) -> Path:
    """OpenCode install directory within the test base."""
    d = base_dir / "opencode"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def vscode_settings(base_dir: Path) -> Path:
    """VS Code settings.json path within the test base."""
    p = base_dir / "vscode" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n")
    return p


@pytest.fixture
def existing_settings(base_dir: Path) -> Path:
    """VS Code settings.json with pre-existing MCP servers."""
    p = base_dir / "vscode" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "editor.fontSize": 14,
        "mcp.servers": {
            "my-custom-server": {
                "command": "node",
                "args": ["my-server.js"],
            }
        },
    }
    p.write_text(json.dumps(data, indent=2) + "\n")
    return p
