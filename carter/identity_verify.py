"""``carter identity verify``: does the whole signing chain work? (App B; plan 005 step 16).

Local: a throwaway repository, a throwaway ``allowed_signers`` (the current key and the
``previous_public_keys``), one commit made with the real shim and the loaded key through the same
signing block the plugin sends, then ``git log`` with ``%G?`` and ``%GF`` and a look at the shape
(role co-author: author is not the LLM; role author: author is the LLM and the human's
``Co-authored-by`` is in the message; the committer is the LLM and the fingerprint the stored
one). A locked or wrong agent is reported before anything is attempted; the shim never
prompts. The temporary directory is removed on every path. Nothing reads the private key.

``--remote``: GitHub's own verdict for one commit through the unauthenticated client; an
unreachable GitHub is an error, never a pass.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from carter.checkitems import Item
from carter.identity import coauthor, github
from carter.identity.agent_setup import setup_from_config
from carter.identity.env import answer
from carter.identity.errors import (
    E_GITHUB_UNREACHABLE,
    E_HUMAN_IDENTITY,
    E_SIGN_LOCKED,
    IdentityError,
    registry,
)
from carter.identity.payload import fingerprint_of, public_blob, shim_path, to_git_env
from carter.identity.resolve import resolve
from carter.identity.schema import IdentityConfig
from carter.identity.trailer import coauthor_trailer, noreply_email
from carter.identity_show import key_items, probe_setup

HUMAN = "carter-verify <verify@invalid.example>"


def _git(repo: Path, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def allowed_signers_text(cfg: IdentityConfig) -> str:
    s = cfg.signing
    keys = [public_blob(k) for k in (s.public_key, *s.previous_public_keys)]
    return "".join(f'{cfg.identity.email} namespaces="git" {k}\n' for k in keys if k)


def _shape(
    repo: Path,
    env: Mapping[str, str],
    cfg: IdentityConfig,
    signers: Path,
    home: Path,
    role: str = "co-author",
) -> list[Item]:
    verify = [
        "-c",
        "gpg.format=ssh",
        "-c",
        f"gpg.ssh.allowedSignersFile={signers}",
        "-c",
        f"gpg.ssh.program={shim_path(home)}",
    ]
    fmt = "%G?|%GF|%an <%ae>|%ce"
    done = _git(repo, env, *verify, "log", "-1", f"--format={fmt}", "HEAD")
    status, fpr, author, committer = (done.stdout.strip().split("|") + ["", "", "", ""])[:4]
    body = _git(repo, env, "log", "-1", "--format=%B", "HEAD").stdout
    items: list[Item] = []
    if status == "G" and fpr == cfg.signing.fingerprint:
        items.append(
            Item("ok", "signature", f"good signature by {fpr} (git verify against allowed_signers)")
        )
    elif status == "G":
        items.append(
            Item(
                "red",
                "signature",
                f"signed by {fpr}, not the configured {cfg.signing.fingerprint}",
                "Run `carter identity add` again, then `carter identity unlock`.",
            )
        )
    else:
        items.append(
            Item("red", "signature", f"the test commit's signature is `{status or '?'}`, not good")
        )
    llm_authored = cfg.identity.email in author
    if role == "author":
        items.append(
            Item("ok", "author", "the author is the LLM (role author)")
            if llm_authored
            else Item("red", "author", "the author is not the LLM; role author expects the LLM")
        )
    else:
        items.append(
            Item("ok", "author", "the author is not the LLM")
            if not llm_authored
            else Item("red", "author", "the author is the LLM; role co-author expects you")
        )
    items.append(
        Item("ok", "committer", "the committer is the LLM")
        if committer == cfg.identity.email
        else Item("red", "committer", "the committer is not the LLM identity")
    )
    wanted = (
        coauthor.human_identity(repo, noreply_email(cfg)).trailer
        if role == "author"
        else coauthor_trailer(cfg, resolve(cfg, workspace=None, env={}))
    )
    items.append(
        Item("ok", "trailer", wanted)
        if wanted and wanted in body
        else Item("red", "trailer", "the trailer is not in the test commit's message")
    )
    return items


def verify_commit(
    rev: str, cfg: IdentityConfig, home: Path, base_env: Mapping[str, str], cwd: Path | None = None
) -> tuple[bool, str]:
    """Is ``rev`` signed by the configured LLM key? Checked against Carter's own ``allowed_signers``
    (not the user's git config), so no ``allowedSignersFile`` error and no bogus ``N`` (D68 i).
    Returns ``(good, reason)``; ``reason`` is empty when good."""
    if not cfg.signing.public_key:
        return False, "no LLM signing key is configured"
    if not rev or rev.startswith("-"):
        return False, "not a commit"
    signers = home / ".carter" / "hooks" / "allowed_signers"
    if not signers.is_file():
        return False, "allowed_signers is missing; run `carter identity add` again"
    env = {
        "PATH": base_env.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    flags = [
        "-c", "gpg.format=ssh",
        "-c", f"gpg.ssh.allowedSignersFile={signers}",
        "-c", f"gpg.ssh.program={shim_path(home)}",
    ]  # fmt: skip
    done = _git(cwd or Path.cwd(), env, *flags, "log", "-1", "--format=%G?|%GF", rev, "--")
    status, _, fpr = done.stdout.strip().partition("|")
    if done.returncode != 0:
        return False, f"{rev} is not a commit here"
    if status != "G":
        return False, f"{rev} is not signed by the LLM key (signature `{status or '?'}`)"
    if fpr != cfg.signing.fingerprint:
        return False, f"{rev} is signed by another key"
    return True, ""


def verify_local(
    cfg: IdentityConfig, home: Path, base_env: Mapping[str, str], config_path: Path
) -> list[Item]:
    if not cfg.signing.public_key:
        return [
            Item(
                "red",
                "verify",
                "no signing key is configured (tier below T2)",
                "Run `carter identity add --login ... --ssh-public-key ...`.",
            )
        ]
    if fingerprint_of(public_blob(cfg.signing.public_key)) != cfg.signing.fingerprint:
        return [
            Item(
                "red",
                "verify",
                "the configured fingerprint is not the public key's",
                "Run `carter identity add` again.",
            ),
        ]
    items = key_items(cfg, home)
    if any(i.level == "red" for i in items):
        return items
    setup = setup_from_config(cfg, home)
    if (
        not cfg.signing.program
        and not setup.file_mode
        and (state := probe_setup(setup, cfg).state) != "ok"
    ):
        locked = registry()[E_SIGN_LOCKED]
        return [
            *items,
            Item(
                "red",
                "verify",
                f"locked ({state}): {locked.message}",
                "Run `carter identity unlock`.",
            ),
        ]
    scratch = Path(tempfile.mkdtemp(prefix="carter-verify-"))
    try:
        scratch.chmod(0o700)
        repo, signers = scratch / "repo", scratch / "allowed_signers"
        signers.write_text(allowed_signers_text(cfg))
        repo.mkdir()
        block = answer(str(repo), {}, str(config_path), home)
        if block.get("reason") == "human-identity-invalid":
            return [
                *items,
                Item(
                    "red",
                    "verify",
                    f"{E_HUMAN_IDENTITY}: role author needs a usable git user.name and user.email",
                    "Set them in your own git config, then run `carter identity verify` again.",
                ),
            ]
        if not block.get("signing"):
            return [
                *items,
                Item(
                    "red",
                    "verify",
                    f"no signing block ({block.get('reason')})",
                    "Run `carter check --host`.",
                ),
            ]
        env = to_git_env(
            {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(home),
                "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": HUMAN.split(" <")[0],
                "GIT_AUTHOR_EMAIL": "verify@invalid.example",
            },
            block["signing"],
        ).env
        res = resolve(cfg, workspace=None, env={})
        trailer = coauthor_trailer(cfg, res)
        if res.role == "author":
            trailer = coauthor.human_identity(repo, noreply_email(cfg)).trailer
        if _git(repo, env, "init", "-q").returncode != 0:
            return [*items, Item("red", "verify", "git could not create the test repository")]
        made = _git(
            repo, env, "commit", "-q", "--allow-empty", "-m", f"carter identity verify\n\n{trailer}"
        )
        if made.returncode != 0:
            first = (made.stderr.strip().splitlines() or ["git commit failed"])[0][:200]
            return [
                *items,
                Item(
                    "red",
                    "signing",
                    f"the test commit could not be signed: {first}",
                    "Run `carter identity unlock`, or `carter identity add` again.",
                ),
            ]
        return [*items, *_shape(repo, env, cfg, signers, home, res.role)]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify_remote(owner_repo: str, sha: str, env: Mapping[str, str] | None = None) -> list[Item]:
    """GitHub's verdict for ``sha``. ``ValueError`` for a malformed ``owner/repo`` or id."""
    owner, _, repo = owner_repo.partition("/")
    try:
        got = github.get_commit_verification(owner, repo, sha, env)
    except github.GitHubError as exc:
        text = registry()[E_GITHUB_UNREACHABLE].message.replace("<detail>", f"{exc.kind}: {exc}")
        raise IdentityError(E_GITHUB_UNREACHABLE, text) from None
    if got.verified:
        return [Item("ok", "github", f"{sha[:12]} is Verified on GitHub ({got.reason})")]
    hint = {
        "unknown_key": "register the key as a signing key on the account",
        "unsigned": "the commit has no signature",
    }
    return [
        Item("red", "github", f"{sha[:12]} is not verified: {got.reason}", hint.get(got.reason, ""))
    ]
