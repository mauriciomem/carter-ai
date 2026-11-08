"""Leftover keys Carter no longer reads, reported so the user can delete them (D70).

Carter keeps no migration and no deprecation shim. A key an older Carter wrote, or the user
copied from an old doc, is simply *unknown*: this module finds it and names the file::

    ⚠ unknown key `attribution.name` in /home/me/.carter/config.toml → delete it

Nothing is changed or migrated, and an unknown key never fails a command. Only key names and
absolute paths are printed, never values.

Files scanned:

- ``~/.carter/config.toml``: every key the schema-2 model does not know.
- ``.carter/carter.yaml``: the retired ``identity.git_account`` and ``identity.bot_name``
  (the file keeps extra keys on purpose, so only the retired ones are named).
- ``.carter/state/plans/*/*/README.md`` front matter: the retired ``push_policy``.
- the OpenCode config entries Carter recorded in ``guard-state.json`` with ``form: "v1"``:
  ``agent.<name>.permission``; and the old-shape ``mcp.carter-*`` server entries.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from carter.checkitems import Item
from carter.identity.config import unknown_keys
from carter.install.jsonc import _load_jsonc
from carter.install.mcp import config_target
from carter.install.paths import carter_config_path, guard_state_path

RETIRED_YAML_KEYS = ("identity.git_account", "identity.bot_name")
RETIRED_PLAN_KEYS = ("push_policy",)
AREA = "unknown key"


@dataclass(frozen=True)
class Hit:
    """One leftover key and the absolute path of the file that holds it."""

    key: str
    path: Path

    def line(self, *, unicode: bool = True) -> str:
        mark, arrow = ("⚠", "→") if unicode else ("!", "->")
        return f"{mark} unknown key `{self.key}` in {self.path} {arrow} delete it"

    def item(self) -> Item:
        """The ``check --host`` row; ``raw`` is the exact line the user sees."""
        return Item("warn", AREA, f"`{self.key}` in {self.path}", "delete it", raw=self.line())


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}  # a broken file is reported as E-CONFIG elsewhere, not as unknown keys


def config_toml(path: Path) -> list[Hit]:
    return [Hit(key, path) for key in unknown_keys(_read_toml(path))]


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError):
        return None


def carter_yaml(path: Path) -> list[Hit]:
    doc = _read_yaml(path)
    if not isinstance(doc, dict):
        return []
    hits = []
    for dotted in RETIRED_YAML_KEYS:
        head, _, leaf = dotted.partition(".")
        block = doc.get(head)
        if isinstance(block, dict) and leaf in block:
            hits.append(Hit(dotted, path))
    return hits


def plans(plans_root: Path) -> list[Hit]:
    from carter.plans import parse_frontmatter

    hits = []
    for bucket in ("active", "completed"):
        directory = plans_root / bucket
        if not directory.is_dir():
            continue
        for readme in sorted(directory.glob("*/README.md")):
            try:
                fm = parse_frontmatter(readme.read_text(encoding="utf-8")) or {}
            except (OSError, UnicodeDecodeError):
                continue
            hits += [Hit(key, readme) for key in RETIRED_PLAN_KEYS if key in fm]
    return hits


def v1_permissions(base_dir: Path | None) -> list[Hit]:
    """``agent.<name>.permission`` entries Carter recorded as ``form: "v1"`` and that are still
    in the OpenCode config."""
    from carter.guard.state import load_or_empty_readonly

    state = load_or_empty_readonly(guard_state_path(base_dir)).state
    agents = sorted({r["agent"] for r in state.agent_permissions if r.get("form") == "v1"})
    if not agents:
        return []
    path = Path(state.opencode_config) if state.opencode_config else config_target(base_dir)
    data = _load_jsonc(path) if path.is_file() else None
    entries = data.get("agent") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return []
    return [
        Hit(f"agent.{name}.permission", path)
        for name in agents
        if isinstance(entries.get(name), dict) and "permission" in entries[name]
    ]


def old_mcp_entries(base_dir: Path | None) -> list[Hit]:
    """``mcp.carter-*`` entries: Carter's servers live under ``mcp.servers`` now."""
    path = config_target(base_dir)
    data = _load_jsonc(path) if path.is_file() else None
    mcp = data.get("mcp") if isinstance(data, dict) else None
    if not isinstance(mcp, dict):
        return []
    return [Hit(f"mcp.{name}", path) for name in sorted(mcp) if name.startswith("carter-")]


def host(base_dir: Path | None = None) -> list[Hit]:
    """The machine-level files: ``config.toml``, and the OpenCode config entries of Carter."""
    return [
        *config_toml(carter_config_path(base_dir)),
        *v1_permissions(base_dir),
        *old_mcp_entries(base_dir),
    ]


def workspace(target: Path) -> list[Hit]:
    """The workspace files: ``.carter/carter.yaml`` and the plan front matter."""
    carter_dir = target / ".carter"
    return [*carter_yaml(carter_dir / "carter.yaml"), *plans(carter_dir / "state" / "plans")]


def once_per_key(hits: Iterable[Hit]) -> list[Hit]:
    """The first hit of each key (``install`` and ``update`` name a key once per run)."""
    seen: dict[str, Hit] = {}
    for hit in hits:
        seen.setdefault(hit.key, hit)
    return list(seen.values())


def host_items(base_dir: Path | None = None) -> list[Item]:
    """Every host hit as a ``check --host`` row (no deduplication)."""
    return [hit.item() for hit in host(base_dir)]


def workspace_items(target: Path) -> list[Item]:
    return [hit.item() for hit in workspace(target)]


def report(hits: Iterable[Hit]) -> int:
    """Print one line per hit on stderr; returns how many. Never raises, never exits."""
    count = 0
    err = sys.stderr
    unicode = (getattr(err, "encoding", None) or "ascii").lower().replace("-", "") in (
        "utf8",
        "utf16",
        "utf32",
    )
    for hit in hits:
        print(hit.line(unicode=unicode), file=err)
        count += 1
    return count
