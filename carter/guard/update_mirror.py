"""The mirror step of ``carter update`` and of ``identity add|remove``.

``plan`` is read-only and answers "what would change in ``~/.carter/gitconfig`` and its cap
fragments"; ``apply`` writes it (fragments first, then the file, then the guard state, which is
saved last). A cap below the pinned ``require_tier`` is refused with the E-TIER-REQUIRED text. The
user's global git config is not written here; ``include_hint`` returns the include line only when
Carter's file carries hook or alias entries and the line is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from carter.guard import gitconfig, mirror_io
from carter.guard.state import GuardState, load_or_empty_readonly, save
from carter.identity import mirror
from carter.identity.schema import IdentityConfig
from carter.install.paths import carter_gitconfig_path, guard_state_path


@dataclass
class Plan:
    add: list[tuple[str, str]] = field(default_factory=list)
    drop: list[tuple[str, str]] = field(default_factory=list)
    fragments_add: list[str] = field(default_factory=list)
    fragments_drop: list[str] = field(default_factory=list)
    refusal: str = ""

    @property
    def changes(self) -> bool:
        return bool(self.add or self.drop or self.fragments_add or self.fragments_drop)

    def lines(self) -> list[str]:
        out = [f"  - {k} = {v}" for k, v in self.drop] + [f"  + {k} = {v}" for k, v in self.add]
        out += [f"  - fragment {name}" for name in self.fragments_drop]
        out += [f"  + fragment {name}" for name in self.fragments_add]
        return out


def plan(base_dir: Path | None, cfg: IdentityConfig) -> Plan:
    """Desired mirror versus what is in the file now. Read-only."""
    carter = mirror_io.carter_dir(base_dir)
    try:
        wanted = mirror.mirror_entries(cfg, carter)
        frags = mirror.fragments(cfg, carter)
    except mirror.MirrorError as exc:
        return Plan(refusal=str(exc))
    have, _ = mirror_io.split(mirror_io.read_entries(carter_gitconfig_path(base_dir)))
    out = Plan(add=[e for e in wanted if e not in have], drop=[e for e in have if e not in wanted])
    folder = carter / mirror.FRAGMENTS_DIR
    for path, text in frags.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            out.fragments_add.append(path.name)
    out.fragments_drop = [p.name for p in sorted(folder.glob("*")) if p not in frags]
    return out


def apply(base_dir: Path | None, cfg: IdentityConfig) -> mirror_io.SyncResult:
    """Write the mirror and save the guard state. Raises ``MirrorError`` / ``GitError``."""
    path = guard_state_path(base_dir)
    read = load_or_empty_readonly(path)
    state: GuardState = read.state
    result = mirror_io.sync(base_dir, state, cfg)
    save(state, path)
    return result


def include_hint(base_dir: Path | None) -> str | None:
    """The include line to add by hand, when the file holds hook or alias entries and the global
    config lacks it. ``None`` when nothing is needed."""
    _, others = mirror_io.split(mirror_io.read_entries(carter_gitconfig_path(base_dir)))
    if not others or gitconfig.manual_include_state(base_dir) == "present":
        return None
    return gitconfig.include_line(base_dir)
