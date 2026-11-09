"""``carter identity unlock | lock``.

The only code that makes the user type a passphrase, and it refuses everywhere an agent or a
non-terminal could be: an AD1 agent signal or ``OPENCODE_TERMINAL`` (set in every OpenCode-spawned
shell, the integrated PTY included: ``E-UNLOCK-OPENCODE``), and no terminal on stdin or stderr
(``E-UNLOCK-TTY``). The checks run before any process starts. ``ssh-add`` gets the terminal
directly, with no wrapper and no retry cap; Carter's process never sees the passphrase.

The rest of the ``identity`` group (``add``, ``show``, ``verify``, ``remove``, ``env``) is added
by later steps to the same group.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace

import click

from carter import ui
from carter.checkitems import Item
from carter.cliguard import guarded, verbose_option
from carter.identity import agent
from carter.identity.agent_setup import Setup
from carter.identity.errors import E_UNLOCK_OPENCODE, E_UNLOCK_TTY, IdentityError
from carter.identity.rules import is_agent, load_rules
from carter.identity.schema import tier_words
from carter.terminal import stdin_is_tty

OPENCODE_TERMINAL = "OPENCODE_TERMINAL"
MANAGED = "Your signing key is managed by your password manager; there is nothing to {verb} here."


def require_unlock_terminal(env: Mapping[str, str] | None = None, *, need_tty: bool = True) -> None:
    """Raise ``E-UNLOCK-OPENCODE`` or ``E-UNLOCK-TTY`` (in that order). Names only, no values."""
    environment = os.environ if env is None else env
    rules = load_rules()
    present = [n for n in (*rules.agent_signals, *rules.human_signals) if n in environment]
    if OPENCODE_TERMINAL in environment:
        present.append(OPENCODE_TERMINAL)
    if is_agent(environment) or OPENCODE_TERMINAL in environment:
        raise IdentityError(E_UNLOCK_OPENCODE, detail="seen: " + ", ".join(sorted(set(present))))
    if need_tty and not (stdin_is_tty() and _stderr_is_tty()):
        raise IdentityError(E_UNLOCK_TTY, detail="stdin and stderr must be a terminal")


def _stderr_is_tty() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except (ValueError, OSError):
        return False


def _terminal_runner(argv: list[str], env: dict[str, str]) -> int:
    """Run ``ssh-add`` on the user's terminal: stdio inherited, nothing captured."""
    return subprocess.run(argv, env=env, check=False).returncode


def _setup() -> tuple[Setup, str]:
    """(Setup, login) from ``config.toml``, or an error that says what is missing."""
    from carter.identity import ConfigError, load_identity
    from carter.identity.agent_setup import setup_from_config

    try:
        cfg = load_identity()
    except ConfigError as exc:
        raise IdentityError(exc.code, detail=exc.detail) from exc
    try:
        return setup_from_config(cfg), cfg.identity.login
    except ValueError as exc:
        raise click.ClickException(
            f"No LLM signing key is configured ({exc}). Run `carter identity add` first."
        ) from exc


@click.group("identity")
def identity() -> None:
    """The LLM identity: set it up, check it, unlock its key."""


def perform_unlock(ttl: str | None, extend: bool) -> int:
    """The body of ``identity unlock``; ``carter commit`` calls it for its one unlock offer."""
    require_unlock_terminal()
    setup, _login = _setup()
    if setup.managed_externally:
        ui.ok(MANAGED.format(verb="unlock"))
        return 0
    if setup.file_mode:
        ui.ok("nothing to unlock", "the key has no passphrase")
        return 0
    if ttl is not None:
        try:
            setup = replace(setup, ttl=agent.parse_ttl(ttl))
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--ttl") from exc
    problem = agent.check_key_file(setup.private_key)
    if problem:
        ui.fail(
            f"the private key file is {problem.replace('-', ' ')}",
            "it must be a regular file readable only by you",
        )
        return 1
    result = agent.unlock(setup, _terminal_runner, extend=extend)
    if result.status == "already-unlocked":
        ui.ok("already unlocked", "use --extend to renew")
        return 0
    if result.status == "failed":
        ui.fail(f"ssh-add exited {result.returncode}; no key was loaded")
        return 1
    ui.ok("unlocked", setup.fingerprint[:19] + "…" + (f" · {setup.ttl}" if setup.ttl else ""))
    return 0


@identity.command("unlock")
@click.option(
    "--ttl", default=None, metavar="TIME", help="Keep the key loaded this long (8h, 30m)."
)
@click.option("--extend", is_flag=True, help="Renew a loaded key's lifetime.")
def unlock_cmd(ttl: str | None, extend: bool) -> None:
    """Load the LLM key (one with a passphrase) into Carter's agent."""

    guarded(lambda: perform_unlock(ttl, extend))


@identity.command("lock")
@click.option("--all", "stop_all", is_flag=True, help="Also stop the agent.")
def lock_cmd(stop_all: bool) -> None:
    """Unload the LLM key from Carter's agent."""

    def run() -> int:
        require_unlock_terminal(need_tty=False)  # a script or a logout hook may lock
        raw, _login = _setup()
        if raw.managed_externally:
            ui.ok(MANAGED.format(verb="lock"))
            return 0
        if raw.file_mode:
            ui.ok("nothing to lock", "the key has no passphrase")
            return 0
        result = agent.lock(raw, stop_all=stop_all)
        if result.status == "failed":
            ui.fail(f"ssh-add exited {result.returncode}")
            return 1
        ui.ok("locked" if result.status == "locked" else "already locked")
        return 0

    guarded(run)


@identity.command("add")
@click.option("--login", required=True, help="The LLM's GitHub login.")
@click.option(
    "--ssh-public-key",
    default=None,
    metavar="PATH",
    help="Key file: the .pub or the private key (the other is derived).",
)
@click.option(
    "--private-key", default=None, metavar="PATH", help="Private key, if not next to the .pub."
)
@click.option(
    "--agent-socket", default=None, metavar="PATH", help="A password manager's agent socket."
)
@click.option(
    "--signing-program", default=None, metavar="PATH", help="A signing program (password manager)."
)
@click.option(
    "--role",
    type=click.Choice(["co-author", "author"]),
    default=None,
    help="author: the LLM is the author (needs a key).",
)
@click.option("--dry-run", is_flag=True, help="Check only; write nothing.")
@verbose_option
def add_cmd(
    login: str,
    ssh_public_key: str | None,
    private_key: str | None,
    agent_socket: str | None,
    signing_program: str | None,
    role: str | None,
    dry_run: bool,
) -> None:
    """Set up the LLM identity (--login alone, or with a key)."""
    if agent_socket and signing_program:
        raise click.UsageError("--agent-socket and --signing-program exclude each other")

    def run() -> int:
        from carter import identity_add
        from carter.terminal import require_human_terminal

        if not dry_run:
            require_human_terminal("carter identity add", need_tty=False)
        try:
            plan = identity_add.plan_add(
                identity_add.AddRequest(
                    login, ssh_public_key, private_key, agent_socket, signing_program, role
                )
            )
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--login") from exc
        tier = tier_words("t2" if plan.fingerprint else "t1")
        parts = [plan.login, tier]
        if plan.fingerprint:
            parts.append(plan.fingerprint[:19] + "…")
        if plan.cfg.identity.role == "author":
            parts.append("author")
        if plan.mode == "file":
            parts.append("no passphrase")
        if plan.rotated_from:
            ui.detail(f"rotated: {plan.rotated_from} moves to previous_public_keys")
        for note in plan.notes:
            ui.detail(note)
        if plan.cfg.identity.role == "author":
            from pathlib import Path

            from carter.human_items import dco_items, human_items

            found = [
                *human_items(plan.cfg, Path.cwd(), refresh=True, record=not dry_run),
                *dco_items(Path.cwd()),
            ]
            for item in found:
                if item.level in ("warn", "red"):
                    ui.warn(f"{item.area}: {item.text}", item.fix)
                else:
                    ui.detail(f"{item.area}: {item.text}")
        for name in plan.files:
            ui.detail(name)
        if dry_run:
            ui.ok(" · ".join(parts), "dry run, nothing written")
            return 0
        for notice in identity_add.apply_add(plan):
            ui.detail(notice)
        ui.ok(" · ".join(parts))
        if plan.mode == "agent":
            ui.info("→ next: carter identity unlock")
        return 0

    guarded(run)


def _print_items(items: list[Item], noun: str, *, everything: bool = False) -> int:
    return ui.items(items, noun, all_items=True if everything else None)


@identity.command("show")
@verbose_option
def show_cmd() -> None:
    """Show the LLM identity and its checks."""

    def run() -> int:
        from pathlib import Path

        from carter import identity_show

        items, _res = identity_show.show_items(Path.cwd(), os.environ)
        return _print_items(items, "identity", everything=True)

    guarded(run)


@identity.command("verify")
@click.option(
    "--remote", default=None, metavar="OWNER/REPO", help="Ask GitHub about a commit in this repo."
)
@click.option("--sha", default=None, metavar="SHA", help="The commit (with --remote).")
@click.option(
    "--commit", "rev", default=None, metavar="REV", help="Check a local commit's signature."
)
@click.option("--quiet", "-q", is_flag=True, help="Print nothing; the exit code says it.")
@verbose_option
def verify_cmd(remote: str | None, sha: str | None, rev: str | None, quiet: bool) -> None:
    """Check that the LLM can sign, or that a commit is signed by it."""
    if (remote is None) != (sha is None):
        raise click.UsageError("--remote and --sha go together")

    def run() -> int:
        from pathlib import Path

        from carter import identity_verify
        from carter.identity.config import default_path
        from carter.identity_show import load_config

        if rev is not None:
            good, why = identity_verify.verify_commit(rev, load_config(), Path.home(), os.environ)
            if not quiet:
                ui.ok(f"{rev} is signed by the LLM key") if good else ui.fail(why)
            return 0 if good else 1
        if remote is not None and sha is not None:
            try:
                items = identity_verify.verify_remote(remote, sha)
            except ValueError as exc:
                raise click.BadParameter(str(exc), param_hint="--remote/--sha") from exc
            return _print_items(items, "remote verification")
        items = identity_verify.verify_local(load_config(), Path.home(), os.environ, default_path())
        return _print_items(items, "verified")

    guarded(run)


@identity.command("remove")
@click.option("--yes", "-y", "assume_yes", is_flag=True, hidden=True)
@click.option("--dry-run", is_flag=True, help="Show what would be removed.")
@verbose_option
def remove_cmd(assume_yes: bool, dry_run: bool) -> None:
    """Remove the LLM identity (your key file stays)."""
    del assume_yes  # accepted and ignored: nothing is asked any more

    def run() -> int:
        from carter import identity_remove
        from carter.terminal import require_human_terminal

        if not dry_run:
            require_human_terminal("carter identity remove", need_tty=False)
        report = identity_remove.remove_identity(None, dry_run=dry_run)
        for line in report.removed:
            ui.detail(f"{report.verb.lower()}: {line}")
        for line in report.kept:
            ui.warn(f"kept {line}")
        for line in report.notes:
            ui.detail(line)
        if not (report.removed or report.kept):
            ui.ok("no LLM identity here")
        else:
            ui.ok(
                f"{report.verb.lower()} the LLM identity",
                f"{len(report.removed)} file(s) · guards and your key file stay",
            )
        return 0

    guarded(run)
