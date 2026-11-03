"""Deterministic secret scan of a PR's title, branch name and body (RFC-0007 App C.5).

``carter pr`` runs this before anything leaves the machine. The rules are fixed regexes plus
one entropy rule, so the same text always gives the same answer:

- token shapes (a *prefix followed by token characters*, so prose that merely mentions
  ``ghp_`` passes): ``github_pat_``, ``gh[pousr]_``, ``AKIA``, ``sk-``, ``xox[bp]-``;
- PEM **private key** headers (public certificates and keys are fine);
- every segment of ``credential_paths`` in ``g2_rules.json`` (``/.ssh/``, ``/.config/gh/``, ...);
- ``high-entropy``: a run of at least ``ENTROPY_MIN_LENGTH`` (32) characters from
  ``[A-Za-z0-9+=_-]`` whose Shannon entropy is at least ``ENTROPY_BITS_PER_CHAR`` (4.5 bits
  per character: random base64/alphanumeric secrets score about 4.7-5.3, English words, paths
  and identifiers stay below 4; an all-hex run is skipped because git SHAs and checksums are
  not secrets).

Text is NFKC-normalised and format/control characters (zero-width, bidi) are removed first,
so fullwidth or invisibly-padded lookalikes cannot hide a token. A finding carries the rule
id, the field, and at most 4 characters of the match: the secret never leaves this module.
Pure: no I/O, no click.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from carter.identity.errors import E_SECRET_SCAN, IdentityError, registry
from carter.identity.rules import load_rules

ENTROPY_MIN_LENGTH = 32
ENTROPY_BITS_PER_CHAR = 4.5
HINT_CHARS = 4

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("api-key-sk", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}")),
    ("pem-private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")),
)
_CANDIDATE = re.compile(rf"[A-Za-z0-9+=_-]{{{ENTROPY_MIN_LENGTH},}}")
_HEX = re.compile(r"[0-9a-fA-F]+")


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str  # "title" | "branch" | "body"
    hint: str  # at most 4 characters of the match

    def __str__(self) -> str:
        return f"{self.where}: {self.rule}"


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(c for c in folded if unicodedata.category(c) not in ("Cf", "Cc") or c in "\n\t")


def _entropy(token: str) -> float:
    counts = Counter(token)
    return -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())


def _credential_patterns() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for segment in load_rules().credential_paths:
        pattern = re.escape(segment).replace(r"\*", r"[^/\s]+")
        out.append(("credential-path", re.compile(pattern)))
    return out


def _scan_field(where: str, raw: str) -> list[Finding]:
    text = _normalise(raw)
    found: list[Finding] = []
    for rule, pattern in (*_RULES, *_credential_patterns()):
        for match in pattern.finditer(text):
            found.append(Finding(rule, where, match.group(0)[:HINT_CHARS]))
    covered = [m.span() for _, p in _RULES for m in p.finditer(text)]
    for match in _CANDIDATE.finditer(text):
        token = match.group(0)
        inside_known = any(a <= match.start() and match.end() <= b for a, b in covered)
        if inside_known or _HEX.fullmatch(token):
            continue
        if _entropy(token) >= ENTROPY_BITS_PER_CHAR:
            found.append(Finding("high-entropy", where, token[:HINT_CHARS]))
    return found


def scan(title: str, branch: str, body: str) -> list[Finding]:
    """Findings in ``title``, ``branch`` and ``body`` (empty = clean), in a stable order."""
    findings: list[Finding] = []
    for where, text in (("title", title), ("branch", branch), ("body", body)):
        findings += _scan_field(where, text)
    seen: set[tuple[str, str]] = set()
    unique = []
    for f in findings:
        if (f.where, f.rule) not in seen:
            seen.add((f.where, f.rule))
            unique.append(f)
    return unique


def to_error(findings: list[Finding]) -> IdentityError | None:
    """``E-SECRET-SCAN`` naming the rules and fields (never the text), or ``None`` if clean."""
    if not findings:
        return None
    rules = ", ".join(sorted({f.rule for f in findings}))
    message = registry()[E_SECRET_SCAN].message.replace("`<rule>`", f"`{rules}`")
    return IdentityError(E_SECRET_SCAN, message, detail="; ".join(str(f) for f in findings))
