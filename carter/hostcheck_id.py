"""The identity items of ``carter check --host``: the LLM identity and role author.

Read-only and names only: logins, fingerprints, states and file names; never a key, a token, a
socket path or an environment value. A RED item makes agent commits fail (or lets a wrong key
stand); a WARN item is drift that ``carter update`` or ``identity add`` fixes. ``fetch`` reads the
account's public key lists without credentials; with no reader, or offline, those items are INFO.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from carter.checkitems import Item, Level
from carter.guard import consent, gitconfig, hooks, mirror_io, repohooks
from carter.guard.state import GuardState
from carter.human_items import dco_items, human_items
from carter.identity import mirror, shim
from carter.identity.agent_setup import setup_from_config
from carter.identity.errors import E_GIT_OLD, E_ROLE_B_TIER, registry
from carter.identity.payload import public_blob, shim_path, shim_state
from carter.identity.resolve import Resolution, configured_tier, effective_tier, resolve
from carter.identity.schema import IdentityConfig
from carter.identity_show import PROBE_TEXT, expected_socket, probe_setup, shim_socket
from carter.install.paths import carter_gitconfig_path

MIN_GIT_T2 = (2, 40)
UPDATE = "Run `carter update`."
AGAIN = "Run `carter identity add` again."
AGENT_LEVEL: dict[str, Level] = {
    "ok": "ok", "empty": "info", "none": "info", "wrong-key": "warn", "stale": "warn", "bad": "red",
}  # fmt: skip


@dataclass(frozen=True)
class KeyLists:
    """What GitHub shows publicly for the LLM account (``None``: could not be read)."""

    signing: list[str] | None
    auth: list[str] | None


Fetch = Callable[[str], KeyLists]


def live_fetch(login: str) -> KeyLists:
    """The unauthenticated client; any failure leaves a list unread."""
    from carter.identity import github  # noqa: PLC0415

    def blobs(call: Callable[[str], list], pick: Callable[[object], str]) -> list[str] | None:
        try:
            return [pick(x) for x in call(login)]
        except Exception:  # noqa: BLE001 - offline (or blocked) is "not checked", not a failure
            return None

    return KeyLists(
        blobs(github.get_signing_keys, lambda k: k.blob),  # type: ignore[attr-defined]
        blobs(github.get_auth_keys, str),
    )


def _git_value(path: Path, key: str, cwd: Path) -> str | None:
    done = gitconfig.run_git(["config", "--file", str(path), "--includes", "--get", key], cwd=cwd)
    return done.stdout.strip() if done.returncode == 0 else None


def _crosses_t2(seen: str, expected: str) -> bool:
    """Opposite sides of T2 make agent commits fail; t0 vs t1 only changes the trailer."""
    return (seen == "t2") != (expected == "t2")


def mirror_items(
    cfg: IdentityConfig, cwd: Path, workspace: str | None, base_dir: Path | None
) -> list[Item]:
    path = carter_gitconfig_path(base_dir)
    if not path.exists():
        text = "~/.carter/gitconfig is missing: the guard reads t0"
        return [Item("red", "tier mirror", text, UPDATE)]
    out = [
        Item("red", "tier mirror", f"{key} differs from config.toml", UPDATE)
        for key, want in mirror.base_entries(cfg)
        if key != "carter.tier" and _git_value(path, key, cwd) != want
    ]
    seen = _git_value(path, "carter.tier", cwd) or "t0"
    ws = cfg.workspaces.get(workspace) if workspace else None
    want_tier = effective_tier(configured_tier(cfg), ws.max_tier if ws else "")
    if mirror.mirror_state(cfg, {"tier": seen}, workspace) == "in-sync":
        out.append(Item("ok", "tier mirror", f"the guard reads {seen} here, as config.toml says"))
        return out
    text = f"the guard reads {seen} but config.toml allows {want_tier}"
    if _crosses_t2(seen, want_tier):
        out.append(Item("red", "tier mirror", text + ": agent commits fail", UPDATE))
    else:
        out.append(Item("warn", "tier mirror", text, UPDATE))
    return out


def fragment_items(cfg: IdentityConfig, state: GuardState, base_dir: Path | None) -> list[Item]:
    out: list[Item] = []
    for path, text in mirror.fragments(cfg, mirror_io.carter_dir(base_dir)).items():
        if not path.exists():
            out.append(
                Item("red", "cap fragment", f"{path.name} is missing: no cap applies", UPDATE)
            )
        elif not gitconfig.parses(path):
            out.append(
                Item(
                    "red",
                    "cap fragment",
                    f"{path.name} is malformed: git fails in that workspace",
                    f"Delete {path} and run `carter update`.",
                )  # fmt: skip
            )
        elif path.read_text(encoding="utf-8") != text or not state.owned_unchanged(path):
            out.append(
                Item("warn", "cap fragment", f"{path.name} differs from what Carter wrote", UPDATE)
            )
        else:
            out.append(Item("ok", "cap fragment", f"{path.name} is in sync"))
    return out


def worktree_items(cfg: IdentityConfig) -> list[Item]:
    out: list[Item] = []
    for key, ws in cfg.workspaces.items():
        if not ws.max_tier:
            continue
        gaps = mirror.worktree_cap_gaps(key)
        for path in gaps.fail_open:
            text = f"{path} is inside the capped workspace but its main repository is outside"
            out.append(Item("warn", "worktree", text + ": the cap does NOT apply there"))
        for path in gaps.capped_outside:
            text = f"{path} is outside the capped workspace but its main repository is inside"
            out.append(Item("warn", "worktree", text + ": the cap applies there"))
    return out


def key_items(cfg: IdentityConfig, home: Path) -> list[Item]:
    try:
        setup = setup_from_config(cfg, home)
    except ValueError as exc:
        return [Item("red", "signing key", f"incomplete: {exc}", AGAIN)]
    out: list[Item] = []
    if cfg.signing.program:
        out.append(
            Item("info", "agent", "managed by the signing program; not probed, no shim check")
        )
    elif setup.file_mode:
        out.append(Item("ok", "agent", "no passphrase: the shim signs from the key file"))
    else:
        state = probe_setup(setup, cfg).state
        _, text, fix = PROBE_TEXT[state]
        level = AGENT_LEVEL[state]
        if level == "info":
            text = "agent commits will fail until you unlock: " + text
        out.append(Item(level, "agent", text, "" if level == "ok" else fix))
    if shim_state(home).ok:
        out.append(Item("ok", "shim", "the signing shim is Carter's (hash matches guard state)"))
    else:
        text = f"{shim_path(home)} is missing, not executable or changed: agent commits fail"
        out.append(Item("red", "shim", text, AGAIN))
    named = shim_socket(home)
    if named is not None and named != expected_socket(cfg, home):
        out.append(
            Item("red", "shim", "the shim names another agent socket than config.toml", AGAIN)
        )
    if not shim.allowed_signers_path(home).exists():
        text = "allowed_signers is missing: post-commit and verify cannot check signatures"
        out.append(Item("warn", "allowed_signers", text, AGAIN))
    return out


def hygiene_items(cfg: IdentityConfig, fetch: Fetch | None) -> list[Item]:
    if fetch is None:
        return [Item("info", "key hygiene", "not checked (no reader)")]
    lists = fetch(cfg.identity.login)
    blob = public_blob(cfg.signing.public_key)
    out: list[Item] = []
    if lists.auth is None:
        out.append(
            Item("info", "key hygiene", "authentication keys not read (offline): not checked")
        )
    elif blob in lists.auth:
        text = "the LLM key is an AUTHENTICATION key on the account: it could log in as the LLM"
        out.append(Item("red", "key hygiene", text, "Register it as a signing key only."))
    else:
        out.append(Item("ok", "key hygiene", "the key is absent from the account's login keys"))
    if lists.signing is None:
        out.append(Item("info", "key hygiene", "signing keys not read (offline): not checked"))
    elif blob not in lists.signing:
        text = "the key is not an SSH signing key on the account: commits show Unverified"
        out.append(Item("warn", "key hygiene", text, "Register it as a signing key on GitHub."))
    return out


def guard_items(state: GuardState, git: tuple[int, int] | None) -> list[Item]:
    out: list[Item] = []
    if not {"hooks", "repo_hooks"} & set(consent.accepted_groups(state)):
        text = "T2 is configured but no commit guard is installed (only the plugin stands)"
        out.append(Item("red", "guards", text, "Run `carter guard install` in your terminal."))
    else:
        text = (
            "without the hooks, the plugin alone keeps agent commits from degrading (fail closed)"
        )
        out.append(Item("info", "guards", text))
        for old, version in repohooks.other_old_gits():
            text = f"an older git is also installed ({old}, {version}): no config hook through it"
            out.append(Item("warn", "git", text))
    if git is not None and git < MIN_GIT_T2:
        out.append(Item("red", "git", f"{E_GIT_OLD}: {registry()[E_GIT_OLD].message}"))
    return out


def group_items(cfg: IdentityConfig, state: GuardState) -> list[Item]:
    alias = state.consents.get("alias", {}).get("decision") or "not installed (optional)"
    return [Item("info", "consent", f"alias (git ai-commit): {alias}")]


def role_items(
    cfg: IdentityConfig,
    res: Resolution,
    cwd: Path,
    base_dir: Path | None,
    home: Path | None,
    env: Mapping[str, str],
    *,
    ask: bool,
) -> list[Item]:
    """Role ``author``. Below T2 it is refused, never downgraded; at T2
    the human identity, the address link, the DCO file and the age of the guard script matter.
    ``ask`` is a live run: the link may be looked up (human terminal only; the cache otherwise)."""
    out = [Item("warn", "role", w) for w in res.warnings]
    if res.role != "author":
        return out
    if res.tier != "t2":
        why = "a workspace cap" if res.cap else f"the configured tier is {res.configured_tier}"
        out.append(
            Item(
                "red",
                "role",
                f"role author needs T2 and {why}: agent commits are refused ({E_ROLE_B_TIER}), "
                "never made as role co-author",
                "Remove the cap or add the signing key (`carter identity add`), or choose "
                "`--role co-author`.",
            )
        )
        return out
    out += human_items(cfg, cwd, home=home, env=env, refresh=ask) + dco_items(cwd)
    installed = hooks.script_path(base_dir)
    if installed.is_file() and installed.read_text(encoding="utf-8") != hooks.render_script():
        out.append(
            Item(
                "red",
                "guards",
                "the commit hook script is from an older Carter and does not know role author: "
                "it would credit the LLM, not you",
                "Run `carter guard install` in your terminal.",
            )
        )
    return out


def identity_items(
    cfg: IdentityConfig,
    state: GuardState,
    *,
    cwd: Path,
    base_dir: Path | None = None,
    home: Path | None = None,
    git: tuple[int, int] | None = None,
    fetch: Fetch | None = None,
    workspace: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Item]:
    """Everything the identity adds to ``check --host``; empty when none is configured."""
    if not cfg.identity.login:
        return []
    tier = configured_tier(cfg)
    env = os.environ if env is None else env
    out = group_items(cfg, state)
    out += role_items(
        cfg,
        resolve(cfg, workspace=workspace, env=env),
        cwd,
        base_dir,
        home,
        env,
        ask=fetch is not None,
    )
    if tier != "t0":
        out += mirror_items(cfg, cwd, workspace, base_dir)
        out += fragment_items(cfg, state, base_dir) + worktree_items(cfg)
    if tier == "t2":
        out += key_items(cfg, home or Path.home()) + hygiene_items(cfg, fetch)
        out += guard_items(state, git)
    return out


__all__ = ["Fetch", "KeyLists", "identity_items", "live_fetch"]
