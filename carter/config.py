"""Configuration loading and schema validation for carter.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REQUIRED_KEYS = {"version", "workspace", "identity", "agents"}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "2",
    "workspace": {
        "name": "my-workspace",
        "description": "",
        "mode": "umbrella",
    },
    "identity": {
        "git_account": "",
        "git_org": None,
        "bot_name": "carter-bot",
        "bot_email": "carter-bot@users.noreply.github.com",
    },
    "personality": {
        "skepticism": "scaled",
        "style": "reviewer",
    },
    "agents": [
        "maestro",
        "architect",
        "engineer",
        "devops",
        "pm",
        "learner",
    ],
    "quality_gate": {
        "enabled": True,
        "max_iterations": 2,
        "trigger": "user-initiated",
    },
    "redaction": {
        "enabled": True,
        "categories": [
            "secrets",
            "internal_urls",
            "security_incidents",
            "pii",
            "financials",
            "employee_data",
            "infra_ids",
        ],
    },
    "tdd": {
        "strict": False,
        "spec_handoff": True,
    },
    "state": {
        "git_tracked": True,
    },
    "target": "copilot",
}


class ConfigError(Exception):
    """Raised when carter.yaml is invalid or missing required fields."""


def load_config(config_path: Path) -> dict[str, Any]:
    """Load and validate carter.yaml from the given path."""
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ConfigError(f"Invalid config format in {config_path}")

    missing = REQUIRED_KEYS - config.keys()
    if missing:
        raise ConfigError(f"Missing required keys: {', '.join(sorted(missing))}")

    return config


def generate_default_config(
    workspace_name: str = "my-workspace",
    mode: str = "umbrella",
) -> dict[str, Any]:
    """Generate a default config dict for a new workspace."""
    config = dict(DEFAULT_CONFIG)
    config["workspace"] = {
        "name": workspace_name,
        "description": "",
        "mode": mode,
    }
    return config


def write_config(config_path: Path, config: dict[str, Any]) -> None:
    """Write config dict to a YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
