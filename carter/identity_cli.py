"""``carter identity unlock | lock`` (RFC-0007 App B, D50, D54, D58; plan 005 step 11).

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

from carter.checkitems import Item
from carter.cliguard import guarded
from carter.identity import agent
from carter.identity.agent_setup import Setup
from carter.identity.errors import (
    E_UNLOCK_NOPASS,
    E_UNLOCK_OPENCODE,
    E_UNLOCK_TTY,
    IdentityError,
    registry,
)
from carter.identity.rules import is_agent, load_rules
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
    """The LLM identity: signing key custody and (in later steps) setup and checks."""


def perform_unlock(ttl: str | None, extend: bool, allow_no_passphrase: bool) -> int:
    """The body of ``identity unlock``; ``carter commit`` calls it for its one unlock offer."""
    require_unlock_terminal()
    setup, login = _setup()
    if setup.managed_externally:
        click.echo(MANAGED.format(verb="unlock"))
        return 0
    if ttl is not None:
        try:
            setup = replace(setup, ttl=agent.parse_ttl(ttl))
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--ttl") from exc
    problem = agent.check_key_file(setup.private_key)
    if problem:
        raise click.ClickException(
            f"The private key file is {problem.replace('-', ' ')} "
            "(it must be a regular file readable only by you); nothing was started."
        )
    if agent.no_passphrase(setup):
        if not allow_no_passphrase:
            message = registry()[E_UNLOCK_NOPASS].message.replace("<llm-login>", login)
            raise click.ClickException(f"{E_UNLOCK_NOPASS}: {message}")
        click.echo(
            f"Warning: this key has no passphrase: any process of yours can sign as {login} "
            "while it is loaded.",
            err=True,
        )
    result = agent.unlock(setup, _terminal_runner, extend=extend)
    if result.status == "already-unlocked":
        click.echo("The LLM signing key is already unlocked (use --extend to renew it).")
        return 0
    if result.status == "failed":
        click.echo(
            f"Unlock failed: ssh-add exited {result.returncode}; no key was loaded.", err=True
        )
        return 1
    click.echo(f"Unlocked the LLM signing key for {setup.ttl} ({setup.fingerprint}).")
    return 0


@identity.command("unlock")
@click.option(
    "--ttl",
    default=None,
    metavar="DURATION",
    help="Key lifetime, e.g. 8h or 30m (default: [identity.signing] ttl, 8h).",
)
@click.option("--extend", is_flag=True, help="Ask again and replace the lifetime of a loaded key.")
@click.option(
    "--allow-no-passphrase",
    is_flag=True,
    help="Accept a key without a passphrase (any process of yours can then sign as the LLM).",
)
def unlock_cmd(ttl: str | None, extend: bool, allow_no_passphrase: bool) -> None:
    """Load the LLM signing key into Carter's dedicated ssh-agent for a while.

    Run it in your own terminal (not in OpenCode's): it asks for the key's passphrase there and
    nowhere else. Agent commits are signed only while the key is loaded."""

    guarded(lambda: perform_unlock(ttl, extend, allow_no_passphrase))


@identity.command("lock")
@click.option(
    "--all", "stop_all", is_flag=True, help="Also stop Carter's agent and any leftover one."
)
def lock_cmd(stop_all: bool) -> None:
    """Remove the LLM signing key from Carter's agent (idempotent).

    Only that key is removed; the agent is stopped when it is empty. Agent commits fail until the
    next `carter identity unlock`."""

    def run() -> int:
        require_unlock_terminal(need_tty=False)  # a script or a logout hook may lock
        raw, _login = _setup()
        if raw.managed_externally:
            click.echo(MANAGED.format(verb="lock"))
            return 0
        result = agent.lock(raw, stop_all=stop_all)
        if result.status == "failed":
            click.echo(f"Lock failed: ssh-add exited {result.returncode}.", err=True)
            return 1
        word = "Locked" if result.status == "locked" else "Already locked"
        stopped = "; the agent was stopped" if result.agent_stopped else ""
        click.echo(f"{word}: the LLM signing key is not loaded{stopped}.")
        return 0

    guarded(run)


@identity.command("add")
@click.option("--login", required=True, help="The LLM's GitHub login (a User account).")
@click.option(
    "--ssh-public-key",
    default=None,
    metavar="PATH|key::...",
    help="Its signing key: a .pub file or a key:: literal (T2).",
)
@click.option(
    "--private-key",
    default=None,
    metavar="PATH",
    help="Path to its private key (stored as a path, never read).",
)
@click.option(
    "--agent-socket",
    default=None,
    metavar="PATH",
    help="A password manager's agent socket (instead of Carter's agent).",
)
@click.option(
    "--signing-program",
    default=None,
    metavar="PATH",
    help="A signing program such as op-ssh-sign (kept behind the shim).",
)
@click.option(
    "--role",
    type=click.Choice(["co-author", "author"]),
    default=None,
    help="co-author (default): you author, the LLM commits. author: the LLM authors and you are "
    "credited by a trailer (needs T2; not for DCO repositories).",
)
@click.option("--dry-run", is_flag=True, help="Check everything and show the plan; write nothing.")
def add_cmd(
    login: str,
    ssh_public_key: str | None,
    private_key: str | None,
    agent_socket: str | None,
    signing_program: str | None,
    role: str | None,
    dry_run: bool,
) -> None:
    """Set up the LLM identity: T1 with --login, T2 with a public key too.

    Checks the account and the key on GitHub without a token (the key must be a signing key and
    not an authentication key), then writes config.toml, the signing shim, allowed_signers and the
    tier mirror. Writes nothing if any check fails. Registering the key on GitHub is yours."""
    if agent_socket and signing_program:
        raise click.UsageError("--agent-socket and --signing-program exclude each other")

    def run() -> int:
        from carter import identity_add
        from carter.terminal import require_human_terminal

        if not dry_run:
            require_human_terminal("carter identity add")
        try:
            plan = identity_add.plan_add(
                identity_add.AddRequest(
                    login, ssh_public_key, private_key, agent_socket, signing_program, role
                )
            )
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--login") from exc
        tier = "T2" if plan.fingerprint else "T1"
        click.echo(f"Identity: {plan.login} (id {plan.uid}), {tier}")
        if plan.fingerprint:
            click.echo(f"Signing key: {plan.fingerprint}")
        if plan.rotated_from:
            click.echo(f"Rotation: {plan.rotated_from} moves to previous_public_keys")
        for note in plan.notes:
            click.echo(f"Note: {note}")
        if plan.cfg.identity.role == "author":
            from pathlib import Path

            from carter.human_items import dco_items, human_items

            click.echo("Role: author (the LLM authors; you are credited by Co-authored-by)")
            for item in [
                *human_items(plan.cfg, Path.cwd(), refresh=True, record=not dry_run),
                *dco_items(Path.cwd()),
            ]:
                click.echo(item.render())
        click.echo("Files:")
        for name in plan.files:
            click.echo(f"  {name}")
        if dry_run:
            click.echo("Dry run: nothing was written.")
            return 0
        if not click.confirm("Write these files?"):
            click.echo("Nothing was written.")
            return 1
        for notice in identity_add.apply_add(plan):
            click.echo(notice)
        click.echo(f"Done. Next: `carter identity unlock` ({tier} signing needs the key loaded).")
        return 0

    guarded(run)


def _print_items(items: list[Item], head: str, noun: str) -> int:
    from carter.checkitems import exit_code, render

    for line in render(items, head, noun):
        click.echo(line)
    return exit_code(items)


@identity.command("show")
def show_cmd() -> None:
    """Show the LLM identity: role, tier, key custody, shim, tier mirror and guard coverage.

    Read-only and allowed anywhere (an agent shell too); it prints names, ids and fingerprints,
    never a key or a token. A defect in config.toml is E-CONFIG, never a silent default."""

    def run() -> int:
        from pathlib import Path

        from carter import identity_show

        items, _res = identity_show.show_items(Path.cwd(), os.environ)
        return _print_items(items, "carter identity show", "Identity")

    guarded(run)


@identity.command("verify")
@click.option("--remote", default=None, metavar="OWNER/REPO", help="Ask GitHub about one commit.")
@click.option("--sha", default=None, metavar="SHA", help="The commit to ask about (with --remote).")
def verify_cmd(remote: str | None, sha: str | None) -> None:
    """Check that the LLM identity can sign: a test commit in a temporary repository.

    Needs the key unlocked (`carter identity unlock`); no network. With --remote OWNER/REPO --sha
    SHA it asks GitHub whether that commit shows as Verified (an unreachable GitHub is an error)."""
    if (remote is None) != (sha is None):
        raise click.UsageError("--remote and --sha go together")

    def run() -> int:
        from pathlib import Path

        from carter import identity_verify
        from carter.identity.config import default_path
        from carter.identity_show import load_config

        if remote is not None and sha is not None:
            try:
                items = identity_verify.verify_remote(remote, sha)
            except ValueError as exc:
                raise click.BadParameter(str(exc), param_hint="--remote/--sha") from exc
            return _print_items(items, "carter identity verify --remote", "Remote verification")
        items = identity_verify.verify_local(load_config(), Path.home(), os.environ, default_path())
        return _print_items(items, "carter identity verify", "Verification")

    guarded(run)


@identity.command("remove")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Do not ask for confirmation.")
@click.option("--dry-run", is_flag=True, help="Show what would be removed; change nothing.")
def remove_cmd(assume_yes: bool, dry_run: bool) -> None:
    """Remove the LLM identity Carter set up, and only what is still unchanged.

    Takes the key out of Carter's agent and stops it, the identity part of config.toml (backed
    up), the signing shim, allowed_signers, the socket directory and the tier mirror. Guards,
    hooks, policies and the `git ai-commit` alias stay (`carter guard remove`), and so does
    everything on GitHub and your private key file."""

    def run() -> int:
        from carter import identity_remove
        from carter.terminal import require_human_terminal

        if not dry_run:
            require_human_terminal("carter identity remove", need_tty=not assume_yes)
            if not assume_yes and not click.confirm("Remove the LLM identity files?"):
                click.echo("Nothing was removed.")
                return 1
        report = identity_remove.remove_identity(None, dry_run=dry_run)
        for line in report.removed:
            click.echo(f"  {report.verb}: {line}")
        for line in report.kept:
            click.echo(f"  Kept: {line}")
        for line in report.notes:
            click.echo(f"  {line}")
        if not (report.removed or report.kept):
            click.echo("Nothing to remove: no LLM identity files here.")
        click.echo("What stays (not this command's):")
        for line in identity_remove.STAYS:
            click.echo(f"  - {line}")
        return 0

    guarded(run)
