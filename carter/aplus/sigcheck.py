"""The shared signature choke point.

Every LLM-committed commit in the pushed range must carry a valid signature by a key Carter
stored: ``%G?`` = ``G`` and ``%GF`` (the signing key's fingerprint) among the stored
fingerprints. Human-committed commits are not looked at. With no LLM signing key configured
 there is nothing to check and the check passes: those tiers never sign.

How it verifies, with no unlocked agent and no trust in the repository's own settings:

- a temporary ``allowed_signers`` file (0600, in a 0700 temp directory, deleted afterwards
  even on an error) with one line per stored key, ``<llm email> namespaces="git" <type> <blob>``,
  for the current key and every ``previous_public_keys`` entry (so a rotation does not strand
  earlier commits);
- git run with ``-c gpg.format=ssh -c gpg.ssh.program=<ssh_bin_dir>/ssh-keygen
  -c gpg.ssh.allowedSignersFile=<temp>`` on top of the hardening in ``carter.aplus.run``;
  command-line ``-c`` beats whatever the repository configures;
- ``ssh_bin_dir`` (default ``/usr/bin``) is the only place ``ssh-keygen`` is looked up.

A failure is a ``Finding`` with code ``E-B-UNSIGNED`` whose key is the commit sha.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from carter.aplus import run
from carter.aplus.findings import Finding, to_error
from carter.identity.errors import E_B_UNSIGNED
from carter.identity.resolve import configured_tier
from carter.identity.schema import IdentityConfig
from carter.identity.trailer import noreply_email

__all__ = ["SigCheckError", "SigIdentity", "build_allowed_signers", "check_signatures", "to_error"]

CHUNK = 200
_FINGERPRINT = re.compile(r"SHA256:\S+")
_RECORD, _FIELD = "\x1e", "\x1f"


class SigCheckError(Exception):
    """The check itself could not run (no ssh-keygen, git failed); it is never a pass."""


@dataclass(frozen=True)
class SigIdentity:
    email: str  # the LLM committer email
    public_keys: tuple[str, ...]  # "type blob", current first, then previous_public_keys
    ssh_bin_dir: str = "/usr/bin"
    fingerprints: tuple[str, ...] = ()  # extra, as stored in config.toml

    @classmethod
    def from_config(cls, cfg: IdentityConfig) -> SigIdentity | None:
        """The LLM signing identity at T2, else ``None`` (nothing to check at T0/T1)."""
        if configured_tier(cfg) != "t2":
            return None
        signing = cfg.signing
        keys = (signing.public_key, *signing.previous_public_keys)
        return cls(
            email=noreply_email(cfg),
            public_keys=tuple(k for k in keys if k),
            ssh_bin_dir=signing.ssh_bin_dir,
            fingerprints=(signing.fingerprint,) if signing.fingerprint else (),
        )


def _key_lines(public_keys: Sequence[str]) -> list[str]:
    lines = []
    for key in public_keys:
        parts = key.split()
        if len(parts) >= 2:  # "type blob [comment]"; a comment would end up as extra columns
            lines.append(f"{parts[0]} {parts[1]}")
    return lines


def build_allowed_signers(identity: SigIdentity) -> str:
    """The ``allowed_signers`` text: one line per stored key (newline-terminated)."""
    if any(c.isspace() for c in identity.email) or not identity.email:
        raise ValueError("the LLM email must be a single token")
    lines = [f'{identity.email} namespaces="git" {k}' for k in _key_lines(identity.public_keys)]
    return "".join(f"{line}\n" for line in lines)


def _fingerprints(identity: SigIdentity, scratch: Path) -> set[str]:
    keygen = Path(identity.ssh_bin_dir) / "ssh-keygen"
    found = set(identity.fingerprints)
    for i, key in enumerate(_key_lines(identity.public_keys)):
        pub = scratch / f"stored-{i}.pub"
        pub.write_text(key + "\n")
        try:
            proc = run.run([str(keygen), "-l", "-f", str(pub)])
        except run.RunError as exc:
            raise SigCheckError(f"cannot run ssh-keygen in {identity.ssh_bin_dir}: {exc}") from exc
        match = _FINGERPRINT.search(proc.stdout) if proc.returncode == 0 else None
        if match:
            found.add(match.group(0))
    return found


def check_signatures(
    repo: Path,
    commits: Sequence[str],
    identity: SigIdentity | None,
    *,
    tmp_root: Path | None = None,
) -> list[Finding]:
    """Findings for LLM-committed commits among ``commits`` that do not verify. Read-only."""
    if identity is None or not commits:
        return []
    keygen = Path(identity.ssh_bin_dir) / "ssh-keygen"
    with tempfile.TemporaryDirectory(prefix="carter-signers-", dir=tmp_root) as scratch_name:
        scratch = Path(scratch_name)
        scratch.chmod(0o700)
        signers = scratch / "allowed_signers"
        signers.touch(mode=0o600)
        signers.write_text(build_allowed_signers(identity))
        stored = _fingerprints(identity, scratch)
        config = [
            "gpg.format=ssh",
            f"gpg.ssh.program={keygen}",
            f"gpg.ssh.allowedSignersFile={signers}",
        ]
        fmt = f"%H{_FIELD}%ce{_FIELD}%G?{_FIELD}%GF{_RECORD}"
        findings: list[Finding] = []
        for i in range(0, len(commits), CHUNK):
            chunk = list(commits[i : i + CHUNK])
            try:
                proc = run.git(
                    ["log", "--no-walk=unsorted", f"--format={fmt}", *chunk], repo, config=config
                )
            except run.RunError as exc:
                raise SigCheckError(f"git log failed: {exc}") from exc
            if proc.returncode != 0:
                raise SigCheckError(f"git log failed ({proc.returncode})")
            findings += _judge(proc.stdout, identity.email, stored)
        return findings


def _judge(output: str, llm_email: str, stored: set[str]) -> list[Finding]:
    found = []
    for record in output.split(_RECORD):
        fields = record.strip("\n").split(_FIELD)
        if len(fields) != 4:
            continue
        sha, committer, status, fingerprint = fields
        if committer.lower() != llm_email.lower():
            continue
        if status == "N":
            reason = "not signed"
        elif status != "G":
            reason = f"signature does not verify (status {status})"
        elif fingerprint not in stored:
            reason = "signed by a key Carter did not store"
        else:
            continue
        found.append(Finding(E_B_UNSIGNED, "commit", sha, "", reason))
    return found
