"""``carter commit``, the core (RFC-0007 §4.3; D26, D36, D57, D64; H14; plan 005 step 21).
Click-free and process-free until ``run_git``: ``plan_commit`` turns the user's ``git commit``
arguments and the config into one git invocation. It builds the same signing block as the plugin
(``payload``) and signs through the same shim and agent; it never reads or uses the human's key.

* **T2, key loaded (K1):** committer and signer are the LLM (the block's env and ``GIT_CONFIG_*``
  entries), author is the human's git identity (``GIT_AUTHOR_*`` is stripped, so a polluted shell
  cannot pick it), ``--trailer`` always.
* **T2, key not loaded:** in an agent shell it refuses (``E-SIGN-AGENT-REFUSE``, nothing is run);
  at a human terminal ``offer_unlock`` is asked once, and on no or failure the commit is made
  **unsigned** with the trailer and ``E-SIGN-HUMAN-FALLBACK`` (never with the human's own key).
* **T1, T0, a cap, the fallback:** unsigned, human as author and committer. ``commit.gpgsign=false``
  and the four ``gpg.*program=<false>`` go in as ``-c``, so even a bare ``-S`` cannot reach the
  human's key. T1 warns ``E-COMMIT-T1``; T0 uses ``Assisted-by: Carter``.

Refused (``REFUSED_FLAGS``): flags that skip a hook, change the signature or pick an identity. A
bare ``-S``/``--gpg-sign`` is dropped with a note; ``-a`` and ``--reset-author`` pass. The role is
ignored (D26, K9); a broken config or unmet ``require_tier`` refuses. Stdlib-only.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from carter.identity.agent_probe import probe
from carter.identity.agent_setup import setup_from_config
from carter.identity.env import workspace_for
from carter.identity.errors import (
    E_COMMIT_T1,
    E_SIGN_AGENT_REFUSE,
    E_SIGN_HUMAN_FALLBACK,
    E_TIER_REQUIRED,
    IdentityError,
    registry,
)
from carter.identity.isolation import GPG_PROGRAMS, resolve_false
from carter.identity.payload import build_payload, shim_state, to_git_env
from carter.identity.resolve import resolve
from carter.identity.schema import TIERS, IdentityConfig
from carter.identity.scrub import scrub_git_env
from carter.identity.trailer import coauthor_trailer

REFUSED_FLAGS = (
    "--no-verify",
    "-n",
    "--no-gpg-sign",
    "-S<arg>",
    "--gpg-sign=<arg>",
    "-s",
    "--signoff",
    "--author",
)
VALUE_SHORT = frozenset("mFcCt")  # short options whose value is the next argument
VALUE_LONG = frozenset({
    "--message", "--file", "--reuse-message", "--reedit-message", "--template", "--fixup",
    "--squash", "--date", "--cleanup", "--trailer", "--pathspec-from-file",
})  # fmt: skip
LONG_REFUSED = ("--no-verify", "--no-gpg-sign", "--signoff", "--author")
BARE_S = "dropped a bare -S/--gpg-sign: the LLM signs by itself, and your key is never used"


class CommitRefused(Exception):
    """Refused before git runs; the message says why and what to do."""


@dataclass
class Plan:
    shape: str  # k1 | unsigned
    argv: list[str]
    env: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def screen_args(args: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(kept arguments, notes)``; ``CommitRefused`` naming every refused flag."""
    kept, notes, _ = _screen(args)
    return kept, notes


def _screen(args: Sequence[str]) -> tuple[list[str], list[str], int]:
    """Like ``screen_args`` plus where the real ``--`` is (``len(kept)`` when there is none): an
    option such as ``--trailer`` must go before it, or git reads it as a path."""
    kept: list[str] = []
    notes: list[str] = []
    bad: list[str] = []
    after, skip, sep = False, False, -1
    for tok in args:
        if after or skip:
            kept.append(tok)
            skip = False
        elif tok == "--":
            after, sep = True, len(kept)
            kept.append(tok)
        elif tok.startswith("--"):
            name = tok.split("=", 1)[0]
            if _refused_long(name):  # git accepts any unambiguous prefix: --no-verif, --auth=x
                bad.append(name)
            elif name == "--gpg-sign":
                bad.append("--gpg-sign=<arg>") if "=" in tok else notes.append(BARE_S)
            else:
                skip = "=" not in tok and name in VALUE_LONG
                kept.append(tok)
        elif tok.startswith("-") and len(tok) > 1:
            out, skip = _short_cluster(tok, bad, notes)
            if out != "-":
                kept.append(out)
        else:
            kept.append(tok)
    if bad:
        names = ", ".join(dict.fromkeys(bad))
        raise CommitRefused(
            f"carter commit does not accept {names}: it signs, verifies and attributes the "
            "commit itself. Use `git commit` yourself for those."
        )
    return kept, notes, len(kept) if sep < 0 else sep


def _refused_long(name: str) -> bool:
    """A refused long option, spelled out or abbreviated (any prefix, ambiguous ones included:
    git would refuse those itself). ``--gpg-sign`` in full is handled by the caller."""
    bare = name[2:]
    if not bare:
        return False
    abbreviated_gpg = "gpg-sign".startswith(bare) and bare != "gpg-sign"
    return abbreviated_gpg or any(full[2:].startswith(bare) for full in LONG_REFUSED)


def _short_cluster(tok: str, bad: list[str], notes: list[str]) -> tuple[str, bool]:
    """``(cluster without the refused letters, the next argument is a value)``."""
    out = "-"
    for i, ch in enumerate(tok[1:], 1):
        if ch in "ns":
            bad.append(f"-{ch}")
        elif ch == "S":
            if i == len(tok) - 1:
                notes.append(BARE_S)
            else:
                bad.append("-S<arg>")
                break
        elif ch == "u":  # -u[<mode>]: the rest of the cluster is the mode, not more flags
            return out + tok[i:], False
        else:
            out += ch
            if ch in VALUE_SHORT:
                rest = tok[i + 1 :]
                return out + rest, not rest
    return out, False


def key_state(cfg: IdentityConfig, home: Path, env: Mapping[str, str] | None = None) -> str:
    """``ok`` or the probe state (``none``, ``empty``, ``wrong-key``, ``stale``, ``bad``)."""
    if cfg.signing.program:
        return "ok"  # the program brings its own agent; the shim reports a locked key when signing
    setup = setup_from_config(cfg, home, env)
    sock = Path(cfg.signing.agent_socket) if cfg.signing.agent_socket else setup.sock
    return probe(sock, setup.ssh_bin_dir, setup.fingerprint, home=home).state


def _clean_env(env: Mapping[str, str]) -> dict[str, str]:
    clean = scrub_git_env(env)
    clean.pop("SSH_AUTH_SOCK", None)  # the human's agent is never used
    return clean


def plan_commit(
    args: Sequence[str],
    *,
    cfg: IdentityConfig,
    env: Mapping[str, str],
    cwd: str,
    home: Path,
    agent: bool,
    human_tty: bool,
    offer_unlock: Callable[[], bool] | None = None,
) -> Plan:
    kept, notes, sep = _screen(args)
    where = workspace_for(cfg, cwd)
    if resolve(cfg, workspace=where, env=env).role == "author":
        notes.append("role not applied (own terminal)")
    res = resolve(cfg, workspace=where, env=env, force_role="co-author")  # D26
    res.ensure_commits_allowed()
    if res.require_tier and TIERS.index(res.tier) < TIERS.index(res.require_tier):
        raise IdentityError(
            E_TIER_REQUIRED, detail=f"effective {res.tier}, required {res.require_tier}"
        )
    trailer = coauthor_trailer(cfg, res)
    opts, paths = kept[:sep], kept[sep:]  # paths start at the real `--`, if any
    tail = ["--trailer", trailer]
    clean = _clean_env(env)
    warnings: list[str] = []
    if res.tier == "t2":
        built = build_payload(cfg, res, shim_state(home))
        if built.block is None:
            raise CommitRefused(f"cannot sign ({built.reason}); run `carter identity show`")
        state = key_state(cfg, home, env)
        if state != "ok" and agent:
            raise IdentityError(E_SIGN_AGENT_REFUSE, registry()[E_SIGN_AGENT_REFUSE].message)
        if state != "ok" and human_tty and offer_unlock is not None and offer_unlock():
            state = key_state(cfg, home, env)
        if state == "ok":
            return Plan(
                "k1", ["commit", *kept, *tail], to_git_env(clean, built.block).env, notes=notes
            )
        warnings.append(f"{E_SIGN_HUMAN_FALLBACK}: {registry()[E_SIGN_HUMAN_FALLBACK].remediation}")
    elif res.tier == "t1":
        warnings.append(f"{E_COMMIT_T1}: {registry()[E_COMMIT_T1].message}")
    else:
        notes.append("T0: no LLM identity; the commit credits `Assisted-by: Carter`")
    off = ["-c", "commit.gpgsign=false"]
    off += [x for p in GPG_PROGRAMS for x in ("-c", f"{p}={resolve_false()}")]
    return Plan("unsigned", [*off, "commit", *opts, *tail, *paths], clean, warnings, notes)


def run_git(plan: Plan, cwd: str | None = None) -> int:
    """Run the planned commit on the user's terminal (an editor needs it); git's exit code."""
    return subprocess.run(["git", *plan.argv], env=plan.env, cwd=cwd, check=False).returncode
