"""``carter identity show``: a read-only picture of the LLM identity.

Everything is looked at, nothing is written, started or prompted: the config (a defect is
``E-CONFIG``, never defaults), the resolved role and tier with the workspace cap, the commit shape
that follows, the signing key's custody (the agent probe and the shim), whether the tier
mirror the guard reads agrees with ``config.toml``, and the guard and policy coverage for the
current directory (the ``check --host`` helpers, not a second implementation). Output names
only: logins, ids, fingerprints, states and file names.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from carter import hostcheck, hostcheck_g2
from carter.checkitems import Item
from carter.guard import consent, repohooks
from carter.guard.configwrite import Reader
from carter.guard.state import load_or_empty_readonly
from carter.human_items import dco_items, human_items
from carter.identity import agent_paths, mirror
from carter.identity.agent_probe import Probe, probe
from carter.identity.agent_setup import Setup, setup_from_config
from carter.identity.config import ConfigError, default_path, load_identity
from carter.identity.env import workspace_for
from carter.identity.errors import E_CONFIG, IdentityError
from carter.identity.payload import shim_path, shim_state
from carter.identity.resolve import Resolution, resolve
from carter.identity.schema import IdentityConfig
from carter.install.paths import carter_gitconfig_path, guard_state_path

ROLE_TEXT = {
    "co-author": "co-author: the human is the author, the LLM is credited with a trailer",
    "author": "author: the LLM is author and committer, you are credited by a trailer (T2 only)",
}
SHAPES = {
    ("co-author", "t0"): "author and committer are you; trailer `Assisted-by: Carter`; unsigned",
    ("co-author", "t1"): "author and committer are you; trailer `Co-authored-by`; unsigned",
    (
        "co-author",
        "t2",
    ): "author is you, committer and signer are the LLM; trailer `Co-authored-by`",
    ("author", "t2"): "author, committer and signer are the LLM; trailer `Co-authored-by: <you>`",
}
PROBE_TEXT: dict[str, tuple[str, str, str]] = {
    "ok": ("ok", "the LLM key is loaded in the agent", ""),
    "empty": ("warn", "locked: the agent holds no key", "Run `carter identity unlock`."),
    "none": ("warn", "locked: Carter's agent is not running", "Run `carter identity unlock`."),
    "wrong-key": (
        "red",
        "the agent holds other keys, not the configured one",
        "Run `carter identity lock --all`, then `carter identity unlock`.",
    ),
    "stale": (
        "red",
        "the agent socket does not answer (stale or hung)",
        "Run `carter identity lock --all`, then `carter identity unlock`.",
    ),
    "bad": (
        "red",
        "something that is not our agent socket is at the socket path; left alone",
        "Remove it yourself, then run `carter identity unlock`.",
    ),
}
SOCK_LINE = re.compile(r"^AGENT_SOCK=(.*)$", re.M)


def load_config(config_path: Path | None = None) -> IdentityConfig:
    try:
        return load_identity(config_path or default_path())
    except ConfigError as exc:
        raise IdentityError(E_CONFIG, detail=exc.detail) from exc


def expected_socket(cfg: IdentityConfig, home: Path) -> str:
    """The socket the shim must name: the password manager's, none for a program, else ours."""
    s = cfg.signing
    return s.agent_socket or ("" if s.program else str(agent_paths.socket_path(home)))


def shim_socket(home: Path) -> str | None:
    """``AGENT_SOCK`` as written in the installed shim (read as text, never executed)."""
    try:
        found = SOCK_LINE.search(shim_path(home).read_text(encoding="utf-8"))
    except OSError:
        return None
    if found is None:
        return None
    parts = shlex.split(found.group(1))
    return parts[0] if parts else ""


def probe_setup(setup: Setup, cfg: IdentityConfig) -> Probe:
    sock = Path(cfg.signing.agent_socket) if cfg.signing.agent_socket else setup.sock
    return probe(sock, setup.ssh_bin_dir, setup.fingerprint, home=setup.home)


def key_items(cfg: IdentityConfig, home: Path) -> list[Item]:
    """Custody of the signing key: agent state, shim, shim <-> socket agreement."""
    out = [Item("info", "signing key", cfg.signing.fingerprint)]
    try:
        setup = setup_from_config(cfg, home)
    except ValueError as exc:
        return [
            *out,
            Item("red", "signing key", f"incomplete: {exc}", "Run `carter identity add`."),
        ]
    if cfg.signing.program:
        out.append(Item("info", "agent", "managed by the signing program; not probed"))
    elif setup.file_mode:
        out.append(Item("ok", "agent", "no passphrase: the shim signs from the key file"))
    else:
        level, text, fix = PROBE_TEXT[probe_setup(setup, cfg).state]
        out.append(Item(level, "agent", text, fix))  # type: ignore[arg-type]
    if shim_state(home).ok:
        out.append(Item("ok", "shim", f"{shim_path(home)} is Carter's (hash matches)"))
    else:
        out.append(
            Item(
                "red",
                "shim",
                f"{shim_path(home)} is missing, not executable or changed",
                "Run `carter identity add` again.",
            )
        )
    named, want = shim_socket(home), expected_socket(cfg, home)
    if named is not None and named != want:
        out.append(
            Item(
                "red",
                "shim",
                "the shim names a different agent socket than config.toml",
                "Run `carter identity add` again.",
            )
        )
    elif named is not None:
        out.append(Item("ok", "shim", "the shim and the agent socket agree"))
    return out


def mirror_items(cfg: IdentityConfig, home: Path, workspace: str | None, cwd: Path) -> list[Item]:
    """The tier the guard reads from Carter's git file against what ``config.toml`` allows."""
    from carter.guard import gitconfig

    path = carter_gitconfig_path(None)
    done = gitconfig.run_git(
        ["config", "--file", str(path), "--includes", "--get", "carter.tier"], cwd=cwd
    )
    seen = done.stdout.strip() if done.returncode == 0 else None
    state = mirror.mirror_state(cfg, {"tier": seen}, workspace)
    if state == "in-sync":
        return [
            Item("ok", "tier mirror", f"the guard reads {seen or 't0'} here, as config.toml says")
        ]
    why = "above" if state == "stale-added" else "below"
    return [
        Item(
            "warn",
            "tier mirror",
            f"the guard reads {seen or 't0'}, {why} config.toml",
            "Run `carter update`.",
        )
    ]


def guard_items(cwd: Path) -> list[Item]:
    state = load_or_empty_readonly(guard_state_path(None)).state
    accepted = consent.accepted_groups(state)
    if "hooks" in accepted:
        return hostcheck_g2.hook_scope_items(state, cwd)
    if "repo_hooks" in accepted:
        top = repohooks.toplevel(cwd)
        found = repohooks.scan([top] if top else [], state, None)
        return [Item("ok" if s.state == "guarded" else "warn", "guards", s.line()) for s in found]
    return [
        Item(
            "warn",
            "guards",
            "no commit or push guards installed (unguarded)",
            "Run `carter guard install` in your terminal.",
        )
    ]


def policy_items(reader: Reader | None) -> list[Item]:
    state = load_or_empty_readonly(guard_state_path(None)).state
    if "g2" not in consent.accepted_groups(state):
        return [Item("info", "policies", "none installed")]
    items = hostcheck._policies(state, reader, None)
    # a missing OpenCode is not a defect of the identity: introspection stays readable
    return [
        Item("warn", i.area, i.text, i.fix) if i.text.startswith("cannot read") else i
        for i in items
    ]


def show_items(
    cwd: Path,
    env: Mapping[str, str],
    *,
    home: Path | None = None,
    config_path: Path | None = None,
    reader: Reader | None = None,
) -> tuple[list[Item], Resolution]:
    base = home or Path.home()
    cfg = load_config(config_path)
    workspace = workspace_for(cfg, str(cwd))
    res = resolve(cfg, workspace=workspace, env=env)
    ident = cfg.identity
    items = [
        Item("info", "identity", f"{ident.login} (id {ident.id}, {ident.email})")
        if ident.login
        else Item("info", "identity", "none configured: tier t0", "Run `carter identity add`."),
        Item("info", "role", f"{ROLE_TEXT[res.role]} (source: {res.role_source})"),
        Item(
            "info",
            "tier",
            f"configured {res.configured_tier}, cap {res.cap or 'none'}, effective {res.tier}",
        ),
        Item(
            "info",
            "commits",
            SHAPES.get((res.role, res.tier), "refused")
            if res.commits == "allowed"
            else f"refused ({res.refusal_reason})",
        ),
    ]
    items += [Item("warn", "role", w) for w in res.warnings]
    if res.role == "author" and res.tier == "t2":
        items += human_items(cfg, cwd, home=base, env=env) + dco_items(cwd)
    if res.configured_tier == "t2":
        items += key_items(cfg, base)
    items += mirror_items(cfg, base, workspace, cwd)
    items += guard_items(cwd)
    items += policy_items(reader)
    return items, res
