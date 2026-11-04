"""Reading and writing the ``carter.*`` mirror inside ``~/.carter/gitconfig`` (plan 005 step 13).

One file holds three kinds of entries: the **mirror** (``carter.*`` keys and the ``includeIf``
cap sections, written by ``identity add|remove`` and ``carter update``), the **hook** entries
(``hook.carter-guard-*``), ``init.templateDir`` and the ``alias`` (written by ``carter guard``).
Each writer replaces only its own kind and carries the others over from the file as it is, so
``guard remove`` leaves the mirror alone and ``identity remove`` leaves the hooks alone.

Ownership as everywhere: the file and every fragment are written atomically, recorded in
guard-state ``files`` with their hash, validated by git before they are moved into place, and an
edited file or fragment is kept and reported. The user's global config is never written here: the
guard reads this file directly, so the mirror needs no include line (the hooks and the alias do).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from carter.guard import gitconfig
from carter.guard.gitconfig import Entry
from carter.guard.state import GuardState
from carter.identity import mirror
from carter.identity.schema import IdentityConfig
from carter.install.paths import carter_gitconfig_path


def carter_dir(base_dir: Path | None) -> Path:
    return carter_gitconfig_path(base_dir).parent


def read_entries(path: Path) -> list[Entry]:
    """Every ``(key, value)`` of Carter's file in order, keys in Carter's spelling."""
    if not path.exists():
        return []
    done = gitconfig._file_git(str(path), "--list", "-z")
    if done.returncode != 0:
        return []
    out: list[Entry] = []
    for item in done.stdout.split("\0"):
        key, _, value = item.partition("\n")
        if key:
            out.append((mirror.canonical_key(key), value))
    return out


def split(entries: list[Entry]) -> tuple[list[Entry], list[Entry]]:
    """(mirror entries, everything else), each in file order."""
    mine = [e for e in entries if mirror.is_mirror_key(e[0])]
    return mine, [e for e in entries if not mirror.is_mirror_key(e[0])]


@dataclass
class SyncResult:
    status: Literal["unchanged", "created", "updated", "removed", "edited-kept"] = "unchanged"
    file: str = ""
    fragments_written: list[str] = field(default_factory=list)
    fragments_removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # edited since Carter wrote them


def _validated(text: str) -> None:
    scratch = Path(tempfile.mkdtemp(prefix="carter-frag-"))
    try:
        probe = scratch / "f"
        probe.write_text(text)
        if not gitconfig.parses(probe):
            raise gitconfig.GitError("a rendered fragment is not valid git config; nothing written")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def write_entries(
    base_dir: Path | None,
    state: GuardState,
    mirror_entries: list[Entry],
    others: list[Entry],
    frags: dict[Path, str],
    *,
    include_value: str | None = None,
) -> SyncResult:
    """Write fragments, then the main file (mirror entries first, then ``others``).

    With no entries at all the file is deleted (only if it is still Carter's, unchanged); stale
    fragments are removed the same way. ``include_value`` is unused here: the include line is the
    business of the hook and alias installer."""
    out = SyncResult()
    main = carter_gitconfig_path(base_dir)
    out.file = str(main)
    for path, text in frags.items():  # fragments first: the main file never points at nothing
        _validated(text)
        status = gitconfig.install_file(path, text, state)
        if status in ("created", "updated"):
            out.fragments_written.append(str(path))
        elif status == "edited-kept":
            out.kept.append(str(path))
    folder = main.with_name(main.name + ".d")
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path not in frags:
            if state.owned_unchanged(path):
                path.unlink()
                out.fragments_removed.append(str(path))
            else:
                out.kept.append(str(path))
            state.forget_file(path)
    entries = [*mirror_entries, *others]
    if not entries:
        if main.exists() and state.owned_unchanged(main):
            main.unlink()
            state.forget_file(main)
            out.status = "removed"
        elif main.exists():
            out.status = "edited-kept"
    else:
        content = gitconfig.render_gitconfig(entries)
        gitconfig.validate_content(content)
        out.status = gitconfig.install_file(main, content, state)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return out


def sync(base_dir: Path | None, state: GuardState, cfg: IdentityConfig) -> SyncResult:
    """Make the mirror in Carter's file match ``cfg``; the hook and alias entries are kept."""
    carter = carter_dir(base_dir)
    ents = mirror.mirror_entries(cfg, carter)
    _, others = split(read_entries(carter_gitconfig_path(base_dir)))
    return write_entries(base_dir, state, ents, others, mirror.fragments(cfg, carter))


def remove_mirror(base_dir: Path | None, state: GuardState) -> SyncResult:
    """``identity remove``: the mirror and its fragments go; hooks, template and alias stay."""
    _, others = split(read_entries(carter_gitconfig_path(base_dir)))
    return write_entries(base_dir, state, [], others, {})


def replace_others(base_dir: Path | None, state: GuardState, others: list[Entry]) -> SyncResult:
    """The guard installer's write: new hook/template/alias entries, the mirror carried over."""
    mine, _ = split(read_entries(carter_gitconfig_path(base_dir)))
    carter = carter_dir(base_dir)
    frags = {p: p.read_text() for p in (carter / mirror.FRAGMENTS_DIR).glob("*")} if mine else {}
    return write_entries(base_dir, state, mine, others, frags)


def identity_files(base_dir: Path | None, state: GuardState) -> list[str]:
    """Recorded files that belong to the identity setup, not to the guards: the shim,
    ``allowed_signers``, the cap fragments and, while it holds the tier mirror, Carter's git file.
    ``guard remove`` leaves them (and their hash records) alone; ``identity remove`` takes them."""
    carter = carter_dir(base_dir)
    main = carter_gitconfig_path(base_dir)
    own = {carter / "bin" / "carter-ssh-sign", carter / "hooks" / "allowed_signers"}
    folder = carter / mirror.FRAGMENTS_DIR
    own |= set(folder.glob("*")) if folder.is_dir() else set()
    if split(read_entries(main))[0]:
        own.add(main)
    recorded = {f["path"] for f in state.files}
    return sorted(str(p) for p in own if str(p) in recorded)
