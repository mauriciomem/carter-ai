"""``carter identity add``: derive, check and write a BYO LLM identity (plan 005 step 15, App B).

The user brings the key. Carter never registers a key and never reads a private key: a public key
comes from a ``.pub`` file or a ``key::`` literal (only ``type blob`` is kept, the literal is never
``expanduser``'d); a file that starts like a private key is refused after reading 64 bytes; the
private key is stored as a *path* and is not opened. The checks are unauthenticated GitHub reads.

``plan_add`` does every check and every network call and writes nothing; ``apply_add`` writes
(config.toml through the D55 writer with a backup, the shim, ``allowed_signers``, the mirror) and
puts every file back if a write fails, so a failure leaves the tree as it was. Output names only the
login, the id, the fingerprint and file names.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from carter.guard import gitconfig, mirror_io
from carter.guard.state import GuardState, load_or_empty_readonly, save
from carter.identity import agent_paths, github, shim
from carter.identity.config import ConfigError, load_identity
from carter.identity.errors import (
    E_CONFIG,
    E_GITHUB_UNREACHABLE,
    E_IDENTITY_CHECK,
    E_STATE_INVALID,
    IdentityError,
    registry,
)
from carter.identity.isolation import resolve_false
from carter.identity.payload import fingerprint_of, public_blob, shim_path
from carter.identity.schema import IdentityConfig
from carter.identity.writer import dumps, write_config
from carter.install.paths import backups_dir, guard_state_path

PRIVATE_MARK = b"-----BEGIN"
MAX_PUB_BYTES = 16 * 1024


def fail(code: str, reason: str) -> IdentityError:
    """An error whose registry text carries ``reason`` where it has ``<reason>``."""
    return IdentityError(
        code, registry()[code].message.replace("<reason>", reason).replace("<detail>", reason)
    )


@dataclass(frozen=True)
class AddRequest:
    login: str
    ssh_public_key: str | None = None
    private_key: str | None = None
    agent_socket: str | None = None
    signing_program: str | None = None


@dataclass
class AddPlan:
    cfg: IdentityConfig
    login: str
    uid: int
    fingerprint: str  # "" at T1
    rotated_from: str  # fingerprint of the key moved to previous_public_keys, or ""
    files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    shim_data: bytes = b""
    allowed: str = ""


# -- reading the key ---------------------------------------------------------------------------


def read_public_key(value: str) -> str:
    """``"type blob"`` from a ``key::`` literal or a ``.pub`` file. Private keys are refused."""
    if value.startswith("key::"):
        text = value[len("key::") :].encode()
    else:
        path = Path(value).expanduser()  # a literal is never expanduser'd; a path is
        try:
            if not path.is_file() or path.stat().st_size > MAX_PUB_BYTES:
                raise fail(E_IDENTITY_CHECK, "the public key is not a readable, small file")
            with path.open("rb") as handle:
                text = handle.read(MAX_PUB_BYTES)
        except OSError:
            raise fail(E_IDENTITY_CHECK, "the public key file cannot be read") from None
    head = text.lstrip()[: len(PRIVATE_MARK)]
    if head == PRIVATE_MARK or b"PRIVATE KEY" in text:
        raise fail(E_IDENTITY_CHECK, "that is a PRIVATE key; pass the public key (.pub)")
    for line in text.decode("utf-8", "replace").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            blob = public_blob(line)
            if blob:
                return blob
            break
    raise fail(E_IDENTITY_CHECK, "the value is not a public key (a type and a base64 blob)")


def human_key_blobs(env: Mapping[str, str] | None = None) -> set[str]:
    """The blobs of the human's own ``user.signingkey``: a literal, or a ``.pub`` file. A path
    without ``.pub`` is only tried as ``<path>.pub``; a private key file is never opened."""
    done = gitconfig.run_git(["config", "--includes", "--get", "user.signingkey"], env=env)
    value = done.stdout.strip() if done.returncode == 0 else ""
    if not value:
        return set()
    try:
        if value.startswith("key::"):
            return {read_public_key(value)}
        path = Path(value).expanduser()
        pub = path if path.suffix == ".pub" else path.with_name(path.name + ".pub")
        return {read_public_key(str(pub))} if pub.is_file() else set()
    except IdentityError:
        return set()


def ssh_fingerprint(blob: str, bin_dir: str) -> str:
    """``ssh-keygen -l -f`` on a private temp copy of the blob, cross-checked with the pure code."""
    with tempfile.TemporaryDirectory(prefix="carter-fp-") as scratch:
        pub = Path(scratch) / "key.pub"
        pub.write_text(blob + "\n")
        done = subprocess.run(
            [os.path.join(bin_dir, "ssh-keygen"), "-l", "-f", str(pub)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            start_new_session=True,
            timeout=15,
            check=False,
        )
    parts = done.stdout.split()
    if done.returncode != 0 or len(parts) < 2 or parts[1] != fingerprint_of(blob):
        raise fail(E_IDENTITY_CHECK, "ssh-keygen does not accept this public key")
    return parts[1]


# -- the plan ------------------------------------------------------------------------------------


def _github(call, *args):  # type: ignore[no-untyped-def]
    try:
        return call(*args)
    except github.GitHubError as exc:
        if exc.kind in ("not-found", "not-a-user"):
            raise fail(E_IDENTITY_CHECK, str(exc)) from None
        raise fail(E_GITHUB_UNREACHABLE, f"{exc.kind}: {exc}") from None


def plan_add(
    req: AddRequest, *, env: Mapping[str, str] | None = None, home: Path | None = None
) -> AddPlan:
    """All checks, no writes. Raises ``IdentityError`` naming the failed check."""
    home = home or Path.home()
    read = load_or_empty_readonly(guard_state_path(None))
    if read.status in ("corrupt", "newer"):
        raise IdentityError(E_STATE_INVALID, detail=read.detail)
    try:
        current = load_identity(home / ".carter" / "config.toml")
    except ConfigError as exc:
        raise IdentityError(E_CONFIG, detail=exc.detail) from None
    if current.needs_migration:
        raise IdentityError(E_CONFIG, detail="config.toml is schema 1; run `carter install` first")
    user = _github(github.get_user, req.login, env)
    ident = current.identity
    base_url = github.api_base(env)
    api_notes = (
        [f"GitHub API: {base_url} (not api.github.com; set by GITHUB_API_URL)"]
        if base_url != github.DEFAULT_API
        else []
    )
    if ident.login and ident.login.lower() != user.login.lower():
        raise fail(
            E_IDENTITY_CHECK, "another LLM identity is configured; `carter identity remove` first"
        )
    if ident.id and ident.id != user.id:
        raise fail(E_IDENTITY_CHECK, "the GitHub id differs from the configured one")
    email = f"{user.id}+{user.login}@users.noreply.github.com"
    new_ident = replace(
        ident, login=user.login, id=user.id, email=email, name=ident.name or user.login
    )
    old = current.signing
    has_old = bool(old.public_key)
    managed = bool(req.agent_socket or req.signing_program)
    if req.ssh_public_key is None:
        if has_old or managed or req.private_key:
            raise fail(
                E_IDENTITY_CHECK, "a signing key is configured; pass --ssh-public-key to change it"
            )
        return _finish(
            AddPlan(
                replace(current, identity=new_ident, state="current"),
                user.login,
                user.id,
                "",
                "",
                notes=api_notes,
            ),
            home,
        )
    bin_dir = old.ssh_bin_dir
    shim.check_git()
    shim.check_openssh(bin_dir)
    blob = read_public_key(req.ssh_public_key)
    fingerprint = ssh_fingerprint(blob, bin_dir)
    if blob in human_key_blobs(env):
        raise fail(E_IDENTITY_CHECK, "that is your own signing key; the LLM needs its own key")
    if blob not in [k.blob for k in _github(github.get_signing_keys, user.login, env)]:
        raise fail(E_IDENTITY_CHECK, "not registered as an SSH signing key on the account")
    if blob in _github(github.get_auth_keys, user.login, env):
        raise fail(
            E_IDENTITY_CHECK, "registered as an authentication key; register a signing-only key"
        )
    notes = list(api_notes)
    private = os.path.abspath(os.path.expanduser(req.private_key)) if req.private_key else ""
    if private and not os.path.isfile(private):
        notes.append("the private key file does not exist yet (checked with stat only)")
    previous = tuple(
        dict.fromkeys(
            [
                *old.previous_public_keys,
                *([old.public_key] if has_old and public_blob(old.public_key) != blob else []),
            ]
        )
    )
    signing = replace(
        old,
        public_key=blob,
        fingerprint=fingerprint,
        private_key_path=private,
        agent_socket=req.agent_socket or "",
        program=req.signing_program or "",
        previous_public_keys=tuple(p for p in previous if p != blob),
    )
    rotated = (
        fingerprint_of(public_blob(old.public_key))
        if has_old and public_blob(old.public_key) != blob
        else ""
    )
    if not managed and not private:
        raise fail(
            E_IDENTITY_CHECK, "pass --private-key (a path), or --agent-socket / --signing-program"
        )
    plan = AddPlan(
        replace(current, identity=new_ident, signing=signing, state="current"),
        user.login,
        user.id,
        fingerprint,
        rotated,
        notes=notes,
    )
    return _finish(plan, home)


def _finish(plan: AddPlan, home: Path) -> AddPlan:
    cfg, carter = plan.cfg, home / ".carter"
    plan.files = [str(carter / "config.toml")]
    if cfg.signing.public_key:
        s = cfg.signing
        sock = s.agent_socket or ("" if s.program else str(agent_paths.socket_path(home)))
        plan.shim_data = shim.render(
            shim.ShimParams(
                key=public_blob(s.public_key),
                sock=sock,
                false_path=resolve_false(),
                keygen=os.path.join(s.ssh_bin_dir, "ssh-keygen"),
                run_dir=str(carter / "run"),
                signer=s.program,
            )
        )
        keys = [public_blob(k) for k in (s.public_key, *s.previous_public_keys)]
        plan.allowed = "".join(f'{cfg.identity.email} namespaces="git" {k}\n' for k in keys if k)
        plan.files += [str(shim_path(home)), str(shim.allowed_signers_path(home))]
    plan.files += [str(carter / "gitconfig")]
    return plan


# -- writing -------------------------------------------------------------------------------------


def apply_add(plan: AddPlan, *, home: Path | None = None) -> list[str]:
    """Write everything; put every touched file back if anything fails. Returns notices."""
    home = home or Path.home()
    carter = home / ".carter"
    touched = [
        carter / "config.toml",
        shim_path(home),
        shim.allowed_signers_path(home),
        carter / "gitconfig",
        guard_state_path(None),
    ]
    snapshot = {p: p.read_bytes() if p.is_file() else None for p in touched}
    frag_dir = carter / "gitconfig.d"
    frags_before = {p: p.read_bytes() for p in frag_dir.glob("*")} if frag_dir.is_dir() else {}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    notices: list[str] = []
    try:
        read = load_or_empty_readonly(guard_state_path(None))
        state: GuardState = read.state
        backup = backups_dir(None) / stamp / "config.toml"
        existing = carter / "config.toml"
        if existing.exists() and existing.read_text(encoding="utf-8") != dumps(plan.cfg):
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_config(plan.cfg, existing, backup_to=backup)
        (carter / "run").mkdir(parents=True, exist_ok=True, mode=0o700)
        if plan.shim_data:
            shim.write(shim_path(home), plan.shim_data)
            state.record_file(shim_path(home), plan.shim_data)
            status = gitconfig.install_file(
                shim.allowed_signers_path(home),
                plan.allowed,
                state,
                overwrite_edited=True,
                mode=0o600,
            )
            shim.allowed_signers_path(home).parent.chmod(0o700)
            notices.append(f"allowed_signers: {status}")
        sync = mirror_io.sync(None, state, plan.cfg)
        notices += [f"kept {k}: edited since Carter wrote it" for k in sync.kept]
        save(state, guard_state_path(None))
        if not state.consents:
            notices.append("guards not installed: `carter check --host` shows G2 off")
    except BaseException:
        for path, data in snapshot.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        if frag_dir.is_dir():
            for p in frag_dir.glob("*"):
                if p not in frags_before:
                    p.unlink()
            for p, data in frags_before.items():
                p.write_bytes(data)
            if not any(frag_dir.iterdir()):
                frag_dir.rmdir()
        raise
    return notices
