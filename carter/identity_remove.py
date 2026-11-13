"""``carter identity remove``: take the identity artifacts away, and only those.

Ownership discipline (ADR): every file is removed only if guard state records it and its hash
still matches; an edited file stays and is reported. Order: the key leaves Carter's agent first
(the ``lock --all`` logic, never ``ssh-agent -k``), then the ``[identity]`` and
``[identity.signing]`` parts of ``config.toml`` (the writer, with a backup; workspace pins and
the footer stay), the shim, ``allowed_signers``, the dedicated socket directory, the hook tier
and its cap fragments.
The guards, hooks, policies and the ``git ai-commit`` alias are not this command's business
(``carter guard remove``), and neither is anything on GitHub or the private key file. Either
order of the two removals works. ``dry_run`` reads and reports, and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from carter.guard import mirror_io
from carter.guard.state import GuardState, load_or_empty_readonly, save
from carter.home import STAMP_FORMAT
from carter.identity import agent, agent_paths
from carter.identity.agent_setup import setup_from_config
from carter.identity.config import ConfigError, load_identity
from carter.identity.schema import Identity, IdentityConfig, Signing
from carter.identity.writer import dumps, write_config
from carter.install.paths import backups_dir, guard_state_path


@dataclass
class RemoveReport:
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def verb(self) -> str:
        return "Would remove" if self.dry_run else "Removed"


def _owned_file(path: Path, state: GuardState, report: RemoveReport, dry: bool) -> None:
    if not path.exists():
        return
    if state.owned_unchanged(path):
        if not dry:
            path.unlink()
        report.removed.append(str(path))
    else:
        report.kept.append(f"{path} (edited since Carter wrote it, or not recorded as Carter's)")
    if not dry:
        state.forget_file(path)


def _stop_key(
    cfg: IdentityConfig | None, base_dir: Path | None, report: RemoveReport, dry: bool
) -> None:
    """Take the LLM key out of Carter's agent and stop that agent (a password manager's stays)."""
    if cfg is None or not cfg.signing.public_key or base_dir is not None:
        return
    s = cfg.signing
    if s.agent_socket or s.program:
        report.notes.append("the key is managed by your password manager; nothing to lock")
        return
    if s.mode == "file":
        return  # signs from its file: there is no agent to stop
    if dry:
        report.notes.append("would remove the key from Carter's agent and stop it")
        return
    try:
        result = agent.lock(setup_from_config(cfg), stop_all=True)
    except (ValueError, OSError) as exc:
        report.notes.append(
            f"could not lock the key ({type(exc).__name__}); stop the agent yourself"
        )
        return
    except Exception as exc:  # IdentityError (a path that is not our socket): never touched
        report.notes.append(f"agent not touched: {exc}")
        return
    report.notes.append(
        f"key: {result.status}" + ("; agent stopped" if result.agent_stopped else "")
    )


def _socket_dir(base_dir: Path | None, report: RemoveReport, dry: bool) -> None:
    if base_dir is not None:
        return
    sock = agent_paths.socket_path()
    names = [sock, agent_paths.pidfile_path(), agent_paths.lock_path()]
    for path in names:
        if path.is_socket() or path.is_file():
            if not dry:
                path.unlink(missing_ok=True)
            report.removed.append(str(path))
    for folder in {sock.parent, agent_paths.run_dir()}:
        if folder.is_dir() and not any(folder.iterdir()) and not dry:
            folder.rmdir()


def _config(
    cfg: IdentityConfig | None, path: Path, base_dir: Path | None, report: RemoveReport, dry: bool
) -> None:
    if cfg is None:
        if path.exists():
            report.kept.append(
                f"{path} (not valid; its [identity] part is left, fix it and run again)"
            )
        return
    if cfg.identity == Identity() and cfg.signing == Signing():
        return
    new = replace(cfg, identity=Identity(), signing=Signing())
    nothing_left = dumps(new) == dumps(IdentityConfig(state="current"))
    if nothing_left:  # the file held only the identity: the file goes too (the backup stays)
        if not dry:
            stamp = datetime.now(UTC).strftime(STAMP_FORMAT)
            backup = backups_dir(base_dir) / stamp / "config.toml"
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup.write_bytes(path.read_bytes())
            backup.chmod(0o600)
            path.unlink()
        report.removed.append(f"{path} (it held only the identity; a copy is in backups/)")
        return
    if not dry:
        stamp = datetime.now(UTC).strftime(STAMP_FORMAT)
        backup = backups_dir(base_dir) / stamp / "config.toml"
        if path.exists() and path.read_text(encoding="utf-8") != dumps(new):
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_config(new, path, backup_to=backup)
    report.removed.append(f"{path}: the [identity] and [identity.signing] parts")


def remove_identity(base_dir: Path | None = None, *, dry_run: bool = False) -> RemoveReport:
    report = RemoveReport(dry_run=dry_run)
    carter = mirror_io.carter_dir(base_dir)
    cfg_path = carter / "config.toml"
    read = load_or_empty_readonly(guard_state_path(base_dir))
    if read.status in ("corrupt", "newer"):
        report.kept.append(
            f"{guard_state_path(base_dir)} ({read.status}: nothing recorded can be proven Carter's)"
        )
    state = read.state
    try:
        cfg: IdentityConfig | None = load_identity(cfg_path)
    except ConfigError:
        cfg = None
    _stop_key(cfg, base_dir, report, dry_run)
    _config(cfg, cfg_path, base_dir, report, dry_run)
    _owned_file(carter / "bin" / "carter-ssh-sign", state, report, dry_run)
    _owned_file(carter / "hooks" / "allowed_signers", state, report, dry_run)
    _socket_dir(base_dir, report, dry_run)
    main = carter / "gitconfig"
    if dry_run:
        if mirror_io.split(mirror_io.read_entries(main))[0]:
            report.removed.append(f"{main}: the hook tier and its workspace caps")
        return report
    if read.status in ("corrupt", "newer"):
        return report  # nothing recorded can be proven Carter's: the mirror stays too
    res = mirror_io.remove_mirror(base_dir, state)
    report.removed += res.fragments_removed
    if res.status in ("updated", "removed"):
        report.removed.append(
            f"{main}: the hook tier" + (" (file removed)" if res.status == "removed" else "")
        )
    report.kept += [f"{name} (edited since Carter wrote it)" for name in res.kept]
    if res.status == "edited-kept":
        report.kept.append(f"{main} (edited since Carter wrote it)")
    if read.status == "ok":
        if state == GuardState():
            guard_state_path(base_dir).unlink(missing_ok=True)
        else:
            save(state, guard_state_path(base_dir))
    return report
