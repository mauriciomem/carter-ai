"""Carter's own git config, pulled in by ONE ``include.path`` line.

Every global git key Carter owns lives in ``~/.carter/gitconfig``. The user's global config
gets a single ``include.path = <abs>/.carter/gitconfig`` line; Carter rewrites only its own
file (atomically, hash-tracked) and removal is ``git config --fixed-value --unset-all
include.path <that value>``. Rules:

- The include value is **absolute and unresolved** (a relative path breaks through a
  symlinked ``~/.gitconfig``; a resolved one would not match ``--fixed-value --unset``).
- A symlinked, read-only or dotfile-managed global config is **never written**: Carter
  returns the exact line for the human to add (or remove) and records nothing.
- ``probe_scope`` asks git, in a scratch config, where an included hook is read from:
  ``include`` (global: use the include), ``direct`` (hooks work but not as ``global``:
  write the keys straight into the global config, tracked key by key) or
  ``no-config-hooks`` (git < 2.54: plain keys still use the include, hook entries need the
  per-repo fallback). No version parsing.
- Carter's keys come under the ``hooks`` consent (the hook entries), ``repo_hooks``
  (``init.templateDir``) and ``alias``. With no entry accepted there is no file and no include
  line: the include line is written with the first key, under that key's consent.
- A missing or even absent Carter file never breaks git: ``include.path`` to a missing file
  is silent, so a half-installed state cannot block the human's commit or push.

Every git call names its config file explicitly (``--file``), so tests and ``--dry-run``
never reach the default global config.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from carter.guard.state import GuardState
from carter.install.atomic import atomic_write_bytes
from carter.install.paths import carter_gitconfig_path

Mode = Literal["include", "direct", "no-config-hooks"]
Entry = tuple[str, str]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]
HEADER = (
    "# Managed by Carter (`carter guard`). Do not edit: a changed file is detected,\n"
    "# kept as you left it, and reported by `carter guard status`.\n"
)
PROBE_HOOK = "carter-probe"
INCLUDE_KEY = "include.path"


class GitError(Exception):
    """git is missing or a git command Carter depends on failed."""


def run_git(
    args: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=None if env is None else dict(env),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise GitError("git not found on PATH") from exc


def file_env() -> dict[str, str]:
    """Environment for git calls that name their config file with ``--file``.

    The user's global config is switched off: if an included file is malformed, EVERY git
    command that loads the global config fails ("bad config line"), and these calls (the ones
    that unset the include line!) must keep working exactly then."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return env


def _file_git(*args: str) -> subprocess.CompletedProcess[str]:
    return run_git(["config", "--file", *args], env=file_env())


def _checked(*args: str) -> str:
    """Run ``git config --file <args>``; raise ``GitError`` if it fails."""
    proc = _file_git(*args)
    if proc.returncode != 0:
        raise GitError(
            f"`git {' '.join(args[:3])} ...` failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


# -- detection ------------------------------------------------------------------------


def _parse_scopes(stdout: str) -> dict[str, str]:
    scopes: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            scopes[parts[-1]] = parts[0]
    return scopes


def hook_scopes(
    cwd: Path, event: str = "commit-msg", *, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Map hook name → scope as git reports it (``global``, ``local``, ``command``...).

    Disabled hooks are listed too (``<scope>\\tdisabled\\t<name>``)."""
    return _parse_scopes(run_git(["hook", "list", "--show-scope", event], cwd=cwd, env=env).stdout)


def probe_scope(*, runner: Runner | None = None) -> Mode:
    """Behavioural detection in a scratch config (never the real one, never the real HOME)."""
    run = runner or run_git
    scratch = Path(tempfile.mkdtemp(prefix="carter-probe-"))
    try:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(scratch),
            "XDG_CONFIG_HOME": str(scratch / "xdg"),
            "GIT_CONFIG_GLOBAL": str(scratch / "global"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        repo, probe, glob = scratch / "repo", scratch / "probe.gitconfig", scratch / "global"
        if run(["init", "-q", str(repo)], env=env, cwd=scratch).returncode != 0:
            raise GitError("could not create the scratch repository for the hook probe")
        hook = f'[hook "{PROBE_HOOK}"]\n\tevent = commit-msg\n\tcommand = true\n'
        probe.write_text(hook, encoding="utf-8")
        glob.write_text(f"[include]\n\tpath = {probe}\n", encoding="utf-8")
        listed = run(["hook", "list", "--show-scope", "commit-msg"], env=env, cwd=repo)
        if _parse_scopes(listed.stdout).get(PROBE_HOOK) == "global":
            return "include"
        glob.write_text(hook, encoding="utf-8")
        listed = run(["hook", "list", "--show-scope", "commit-msg"], env=env, cwd=repo)
        return "direct" if PROBE_HOOK in _parse_scopes(listed.stdout) else "no-config-hooks"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# -- locating and guarding the user's global config -------------------------------------


def global_config_path(env: Mapping[str, str] | None = None) -> Path:
    """The file ``git config --global`` writes: ``GIT_CONFIG_GLOBAL``, else the highest-
    precedence file git reports (``--show-origin``), else git's default for a new config."""
    environment = os.environ if env is None else env
    if environment.get("GIT_CONFIG_GLOBAL"):
        return Path(environment["GIT_CONFIG_GLOBAL"])
    listed = run_git(["config", "--global", "--list", "--show-origin"], env=environment)
    origins = [ln.split("\t", 1)[0] for ln in listed.stdout.splitlines() if ln.startswith("file:")]
    if listed.returncode == 0 and origins:
        return Path(origins[-1].removeprefix("file:"))
    home = Path(environment.get("HOME") or Path.home())
    xdg = Path(environment.get("XDG_CONFIG_HOME") or home / ".config") / "git" / "config"
    dot = home / ".gitconfig"
    return xdg if not dot.exists() and xdg.exists() else dot


def manual_reason(path: Path) -> str | None:
    """Why Carter must not write ``path``: symlinked (dotfiles, Nix) or not writable."""
    if path.is_symlink():
        return f"{path} is a symlink (dotfile-managed?)"
    probe = path if path.exists() else next((p for p in path.parents if p.exists()), path.parent)
    if not os.access(probe, os.W_OK) or (path.exists() and not os.access(path.parent, os.W_OK)):
        return f"{path} is not writable"
    return None


# -- the include line ---------------------------------------------------------------------


@dataclass
class IncludeResult:
    status: Literal["added", "present", "removed", "absent", "manual"]
    line: str | None = None  # what the human should run, for "manual"
    note: str = ""


def _absolute(value: str) -> str:
    if not value.startswith("/"):
        raise ValueError(f"the include value must be an absolute path, got {value!r}")
    return value


def has_include_line(path: Path, value: str) -> bool:
    args = [str(path), "--fixed-value", "--get-all", INCLUDE_KEY, value]
    return _file_git(*args).returncode == 0


def parses(path: Path) -> bool:
    """Can git read ``path`` as a config file? (A malformed included file makes EVERY git
    command fail, so ``guard status`` checks it.)"""
    return _file_git(str(path), "--list").returncode == 0


def add_include(path: Path, value: str) -> IncludeResult:
    """Append ``include.path = value`` to the global config unless it is there already."""
    value = _absolute(value)
    line = f"git config --global --add {INCLUDE_KEY} {shlex.quote(value)}"
    if (why := manual_reason(path)) is not None:
        return IncludeResult(
            "manual", line, f"{why}; Carter did not write it. Add the line yourself."
        )
    if path.exists() and has_include_line(path, value):
        return IncludeResult("present")
    _checked(str(path), "--add", INCLUDE_KEY, value)
    return IncludeResult("added")


def remove_include(path: Path, value: str) -> IncludeResult:
    """Unset exactly our line (``--fixed-value``); a line the user changed or removed is left."""
    value = _absolute(value)
    if not path.exists() or not has_include_line(path, value):
        return IncludeResult("absent", note=f"include line not found in {path}; nothing changed")
    if (why := manual_reason(path)) is not None:
        line = f"git config --global --fixed-value --unset-all {INCLUDE_KEY} {shlex.quote(value)}"
        return IncludeResult(
            "manual", line, f"{why}; Carter did not edit it. Remove the line yourself."
        )
    _checked(str(path), "--fixed-value", "--unset-all", INCLUDE_KEY, value)
    return IncludeResult("removed")


def manual_include_state(base_dir: Path | None, env: Mapping[str, str] | None = None) -> str:
    """For a hook install whose include line Carter did not write (dotfiles, read-only):
    ``present`` (the human added it), ``missing`` or ``unknown`` (git cannot say)."""
    value = str(carter_gitconfig_path(base_dir))
    try:
        target = global_config_path(env)
    except GitError:
        return "unknown"
    if target.exists() and has_include_line(target, value):
        return "present"
    return "missing"


def include_line(base_dir: Path | None) -> str:
    value = shlex.quote(str(carter_gitconfig_path(base_dir)))
    return f"git config --global --add {INCLUDE_KEY} {value}"


def unset_line(base_dir: Path | None) -> str:
    value = shlex.quote(str(carter_gitconfig_path(base_dir)))
    return f"git config --global --fixed-value --unset-all {INCLUDE_KEY} {value}"


def record_include(state: GuardState, path: Path, value: str, result: IncludeResult) -> None:
    """Own the include line only when Carter added it or found exactly it already there."""
    if result.status in ("added", "present"):
        state.record_gitconfig(str(path), value)


# -- Carter's file ------------------------------------------------------------------------


def render_gitconfig(entries: Sequence[Entry]) -> str:
    """Carter's file as git itself writes it (so quoting and syntax are always valid)."""
    scratch = Path(tempfile.mkdtemp(prefix="carter-render-"))
    try:
        target = scratch / "gitconfig"
        target.write_text(HEADER, encoding="utf-8")
        for key, val in entries:
            _checked(str(target), "--add", key, val)
        return target.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def validate_content(content: str) -> None:
    """Raise ``GitError`` unless git can read ``content`` as a config file: a malformed included
    file would make EVERY git command fail, so it is checked before it is moved into place."""
    scratch = Path(tempfile.mkdtemp(prefix="carter-validate-"))
    try:
        probe = scratch / "gitconfig"
        probe.write_text(content, encoding="utf-8")
        if not parses(probe):
            raise GitError("the rendered Carter gitconfig is not valid git config; nothing written")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def install_file(
    path: Path,
    content: str,
    state: GuardState,
    *,
    overwrite_edited: bool = False,
    mode: int = 0o600,
) -> Literal["created", "updated", "unchanged", "edited-kept"]:
    """Write Carter's file atomically (0600 unless ``mode``) and record its hash.

    A file the user edited, or one Carter has no record of, is kept as it is unless the
    explicit human install passes ``overwrite_edited``."""
    data = content.encode()
    if not path.exists():
        atomic_write_bytes(path, data, mode=mode)
        state.record_file(path, data)
        return "created"
    if path.read_bytes() == data:
        state.record_file(path, data)
        return "unchanged"
    if state.owned_unchanged(path) or overwrite_edited:
        atomic_write_bytes(path, data, mode=mode)
        state.record_file(path, data)
        return "updated"
    return "edited-kept"


@dataclass
class FileRemoval:
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # edited or never ours: left in place


def remove_files(base_dir: Path | None, state: GuardState) -> FileRemoval:
    """Delete Carter's file and its ``gitconfig.d`` fragments, each only if still unchanged.

    While the file holds the ``carter.*`` hook tier it is rewritten with the mirror alone
    (fragments stay): removing the guards must not blind the guard's own tier source."""
    out = FileRemoval()
    main = carter_gitconfig_path(base_dir)
    frags = main.with_name(main.name + ".d")
    if mirror := carried_mirror(base_dir):  # `identity remove` owns the mirror, not `guard remove`
        if state.owned_unchanged(main):
            install_file(main, render_gitconfig(mirror), state)
            out.removed.append(f"{main} (hook and alias entries; the hook tier stays)")
        else:
            out.kept.append(str(main))
        return out
    candidates = [main] + (sorted(frags.iterdir()) if frags.is_dir() else [])
    for path in candidates:
        if not path.exists():
            continue
        if state.owned_unchanged(path):
            path.unlink()
            out.removed.append(str(path))
        else:
            out.kept.append(str(path))
        state.forget_file(path)
    if frags.is_dir() and not any(frags.iterdir()):
        frags.rmdir()
    return out


# -- direct writes (probe says hooks are not global) -------------------------------------------


@dataclass
class DirectResult:
    written: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # the user has a different value: kept
    manual: list[str] = field(default_factory=list)  # lines for the human (symlinked/read-only)


def _values(path: Path, key: str) -> list[str]:
    proc = _file_git(str(path), "--get-all", key)
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def write_direct(path: Path, entries: Sequence[Entry], state: GuardState) -> DirectResult:
    """Write each key straight into the global config and record it key by key."""
    out = DirectResult()
    if (why := manual_reason(path)) is not None:
        out.manual = [f"git config --global {k} {shlex.quote(v)}   # {why}" for k, v in entries]
        return out
    ours = {(r["file"], r["key"]) for r in state.git_config}
    for key, val in entries:
        existing = _values(path, key) if path.exists() else []
        if existing and val not in existing:
            out.conflicts.append(key)
            continue
        if not existing:
            _checked(str(path), key, val)
            out.written.append(key)
        elif (str(path), key) not in ours:
            continue  # the user already had exactly this: preexisting, never ours to remove
        state.record_git_config(str(path), key, val, "global")
    return out


@dataclass
class DirectRemoval:
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def remove_direct(path: Path, state: GuardState) -> DirectRemoval:
    """Unset each recorded key whose value is still exactly what Carter wrote."""
    out = DirectRemoval()
    for rec in state.git_config:
        if rec["file"] == str(path) and path.exists() and rec["value"] in _values(path, rec["key"]):
            _checked(str(path), "--fixed-value", "--unset-all", rec["key"], rec["value"])
            out.removed.append(rec["key"])
        else:
            out.kept.append(rec["key"])
    state.git_config = [r for r in state.git_config if r["file"] != str(path)]
    return out


def carter_git_entries(
    accepted: Sequence[str] = (),
    *,
    base_dir: Path | None = None,
    template_dir: Path | None = None,
    hooks_rev: int = 2,
    alias: bool = False,
) -> list[Entry]:
    """The global git keys Carter owns for the accepted consent groups.

    ``hooks`` gives the hook entries for the accepted revision (1: ``pre-push``; 2: all four
    events; each a self-contained command, see ``hooks``); ``template_dir`` (decided by
    ``repohooks``: only when the user has none) gives ``init.templateDir``; ``alias`` (decided by
    ``guard.alias``: only when the user has none) gives ``alias.ai-commit``. Nothing accepted,
    nothing returned."""
    from carter.guard import alias as alias_mod  # noqa: PLC0415 - these import this module
    from carter.guard import hooks  # noqa: PLC0415

    out: list[Entry] = []
    if "hooks" in accepted:
        out += hooks.hook_entries(hooks.script_path(base_dir), hooks.events_for_rev(hooks_rev))
    if template_dir is not None and "repo_hooks" in accepted:
        out.append(("init.templateDir", str(template_dir)))
    if alias and "alias" in accepted:
        out.append((alias_mod.ALIAS_KEY, alias_mod.ALIAS_VALUE))
    return out


def carried_mirror(base_dir: Path | None) -> list[Entry]:
    """The ``carter.*`` mirror entries of Carter's file, kept when hook entries are rewritten."""
    from carter.guard import mirror_io  # noqa: PLC0415 - mirror_io imports this module

    mine, _ = mirror_io.split(mirror_io.read_entries(carter_gitconfig_path(base_dir)))
    return mine


@dataclass
class KeysResult:
    status: Literal["not-needed", "applied"] = "not-needed"
    file: str = ""
    include: IncludeResult | None = None
    direct: DirectResult | None = None
    needs_repo_hooks: list[str] = field(default_factory=list)


def apply_keys(
    entries: Sequence[Entry],
    *,
    mode: Mode,
    base_dir: Path | None,
    state: GuardState,
    env: Mapping[str, str] | None = None,
    overwrite_edited: bool = False,
) -> KeysResult:
    """Put ``entries`` where ``mode`` says. No entries: no file and no include line."""
    out = KeysResult()
    if not entries:
        return out
    out.status = "applied"
    target = global_config_path(env)
    if mode == "direct":
        out.direct = write_direct(target, entries, state)
        return out
    plain = [e for e in entries if mode == "include" or not e[0].startswith("hook.")]
    out.needs_repo_hooks = [k for k, v in entries if (k, v) not in plain]
    if not plain:
        return out
    carter_file = carter_gitconfig_path(base_dir)
    named = {k for k, _ in plain}
    carried = [e for e in carried_mirror(base_dir) if e[0] not in named]
    content = render_gitconfig([*carried, *plain])
    validate_content(content)
    out.file = install_file(carter_file, content, state, overwrite_edited=overwrite_edited)
    out.include = add_include(target, str(carter_file))
    record_include(state, target, str(carter_file), out.include)
    return out


@dataclass
class RemoveAll:
    include: IncludeResult | None = None
    files: FileRemoval = field(default_factory=FileRemoval)
    direct: list[DirectRemoval] = field(default_factory=list)


def remove_all(base_dir: Path | None, state: GuardState) -> RemoveAll:
    """Teardown order: the include line, then the file and fragments, then direct keys."""
    out = RemoveAll()
    if state.gitconfig:
        rec = state.gitconfig
        out.include = remove_include(Path(rec["file"]), rec["value"])
        state.clear_gitconfig()
    out.files = remove_files(base_dir, state)
    for target in sorted({r["file"] for r in state.git_config}):
        out.direct.append(remove_direct(Path(target), state))
    return out
