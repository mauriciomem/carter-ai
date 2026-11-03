"""``carter push``: validated push of the current branch to ``origin`` (RFC-0007 C.6.6, A+).

Human terminal only; the click layer (``carter.aplus.cli``) enforces that before anything here
runs. There is no passthrough: the only choices are ``--dry-run`` and ``--set-upstream``.
Nothing can be forced, no tag, other branch or other remote can be named, and the refspec is
always ``HEAD:refs/heads/<current branch>`` on ``origin``.

Order (nothing touches the network before the local checks, because ``fetch`` itself would
run a repository-configured credential helper or SSH command):

1. branch and push URL; 2. repo config (hooks, helpers, URL rewrites) and SSH config: findings
are shown in red and you decide (the broker refuses them, A+ does not); 3. fetch the target ref;
4. the commit range; 5. signature check of LLM-committed commits (a failure is shown with the
commit list and refuses); 6. the commits, files, sensitive paths and GitHub's protection notes;
7. ask (``y``, or the typed branch name on the default branch); 8. push.

``fetch`` and ``push`` use the human's own credentials (``run.network_git``) but never run
repository hooks.

I/O goes through ``Io`` so this module imports no click.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from carter.aplus import protection, rangecalc, repocfg, run, sigcheck, sshcfg
from carter.aplus.findings import Finding, mask_userinfo
from carter.aplus.handoff import OWN_TERMINAL
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.identity import load_identity
from carter.identity.errors import E_APLUS_ARGS, IdentityError
from carter.identity.schema import IdentityConfig
from carter.install.paths import carter_config_path, guard_state_path

MAX_COMMITS_SHOWN = 50
MAX_CHANGES_SHOWN = 20
REMOTE = "origin"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SSH_URL = re.compile(r"(?:git\+)?ssh://(?:[^@/]+@)?(\[[^\]]+\]|[^:/]+)(?::\d+)?/")
_SCP_URL = re.compile(r"(?:[^@/\s]+@)?([^:/\s]+):(?!//)")


@dataclass(frozen=True)
class Options:
    dry_run: bool = False
    set_upstream: bool = False


@dataclass
class Io:
    echo: Callable[[str], None]
    ask: Callable[[str], str]  # raises EOFError at end of input
    red: Callable[[str], str] = field(default=lambda text: text)


def _args(detail: str) -> IdentityError:
    return IdentityError(E_APLUS_ARGS, detail=detail)


def clean(text: str, limit: int = 100) -> str:
    return _CONTROL.sub("?", text)[:limit]


def ssh_host(url: str) -> str | None:
    """The host an ssh transport would connect to, or ``None`` if ``url`` does not use ssh."""
    if "://" in url:
        match = _SSH_URL.match(url)
        return match.group(1).strip("[]") if match else None
    if url.startswith(("/", ".", "~")):
        return None
    match = _SCP_URL.match(url)
    return match.group(1) if match else None


def _out(repo: Path, args: list[str]) -> str | None:
    proc = run.git(args, repo, harden=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _fetch_target(repo: Path, branch: str) -> None:
    refspec = f"+refs/heads/{branch}:refs/remotes/{REMOTE}/{branch}"
    proc = run.network_git(["fetch", "--no-tags", "--no-recurse-submodules", REMOTE, refspec], repo)
    if proc.returncode == 0 or "couldn't find remote ref" in proc.stderr:
        return  # the branch does not exist on origin yet: a new branch
    raise _args(f"cannot fetch from origin ({mask_userinfo(clean(proc.stderr.strip(), 300))})")


def _default_branch(repo: Path) -> str | None:
    ref = _out(repo, ["symbolic-ref", "--short", "-q", f"refs/remotes/{REMOTE}/HEAD"])
    return ref.removeprefix(f"{REMOTE}/") if ref else None


def _commit_lines(
    repo: Path, commits: tuple[str, ...], unsigned: set[str], red: Callable[[str], str]
) -> list[str]:
    lines = []
    for sha in commits[:MAX_COMMITS_SHOWN]:
        raw = run.git(["cat-file", "commit", sha], repo).stdout
        head, _, body = raw.partition("\n\n")
        signed = any(ln.startswith("gpgsig") for ln in head.splitlines())
        mark = "signed  " if signed else "unsigned"
        text = f"  {sha[:12]}  {mark}  {clean(body.split(chr(10), 1)[0], 72)}"
        lines.append(red(text + "   <- LLM commit, not verifiable") if sha in unsigned else text)
    if len(commits) > MAX_COMMITS_SHOWN:
        lines.append(f"  ... and {len(commits) - MAX_COMMITS_SHOWN} more")
    return lines


def confirmed(io: Io, prompt: str, *, expect: str = "y") -> bool:
    """Did the human type ``expect`` (``y`` in any case, or the exact branch name)? EOF is no."""
    try:
        answer = io.ask(prompt).strip()
    except EOFError:
        return False
    return answer == expect if expect != "y" else answer.lower() == "y"


def _prompt(branch: str, typed: bool) -> str:
    if typed:
        return f"`{branch}` is the default branch. Type its name to push to {REMOTE}: "
    return f"Push {branch} to {REMOTE}? [y/N] "


def _identity_and_owned(base_dir: Path | None) -> tuple[IdentityConfig, repocfg.CarterOwned]:
    cfg = load_identity(carter_config_path(base_dir))  # a broken file refuses (E-CONFIG)
    read = load_or_empty_readonly(guard_state_path(base_dir))
    owned = repocfg.CarterOwned.from_state(read.state if read.status == "ok" else GuardState())
    return cfg, owned


def _local_checks(
    repo: Path, url: str, base_dir: Path | None, home: Path
) -> tuple[IdentityConfig, list[Finding]]:
    cfg, owned = _identity_and_owned(base_dir)
    try:
        findings = repocfg.check_repo_config(repo, origin_url=url, owned=owned)
    except repocfg.RepoCheckError as exc:
        raise _args(f"cannot inspect the repository ({exc})") from exc
    host = ssh_host(url)
    if host:
        findings += sshcfg.check_ssh_config(home, ssh_bin_dir=cfg.signing.ssh_bin_dir, host=host)
    return cfg, findings


def vet_local(
    repo: Path, url: str, io: Io, *, base_dir: Path | None, home: Path, dry_run: bool = False
) -> tuple[IdentityConfig, int | None]:
    """Repo-config and SSH-config checks before anything touches the network.

    Findings are shown in red and you decide, as in RFC-0007 C.6.6 (the broker refuses them).
    Returns the identity config and ``None`` to go on, or an exit code to stop with."""
    cfg, found = _local_checks(repo, url, base_dir, home)
    if not found:
        return cfg, None
    io.echo(io.red("These settings could run code with your credentials or reroute the push:"))
    for finding in found:
        io.echo(io.red(f"  {finding.render()}"))
    if dry_run:
        io.echo("Dry run: nothing was fetched or pushed (fetching would run them). Review them.")
        return cfg, 0
    if not confirmed(io, f"Fetch from and push to {REMOTE} anyway? [y/N] "):
        io.echo("Aborted: nothing was fetched or pushed.")
        return cfg, 1
    return cfg, None


def run_push(
    repo: Path,
    opts: Options,
    io: Io,
    *,
    base_dir: Path | None = None,
    home: Path | None = None,
    notes: Callable[[str, str], list[str]] | None = None,
) -> int:
    """Run the flow in ``repo``; 0 = pushed, dry run or nothing to push, 1 = declined or failed."""
    try:
        return _flow(repo, opts, io, base_dir, home or Path.home(), notes or _notes(base_dir))
    except (run.RunError, sigcheck.SigCheckError) as exc:
        raise _args(str(exc)) from exc


def _notes(base_dir: Path | None) -> Callable[[str, str], list[str]]:
    return lambda url, branch: protection.branch_notes(url, branch, base_dir)


def _flow(
    repo: Path,
    opts: Options,
    io: Io,
    base_dir: Path | None,
    home: Path,
    notes: Callable[[str, str], list[str]],
) -> int:
    branch = _out(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if not branch:
        raise _args("detached HEAD: check out the branch you want to push")
    url = _out(repo, ["remote", "get-url", "--push", REMOTE])
    if url is None:
        raise _args(f"no remote named {REMOTE}")
    cfg, stop = vet_local(repo, url, io, base_dir=base_dir, home=home, dry_run=opts.dry_run)
    if stop is not None:
        return stop
    _fetch_target(repo, branch)
    rng = rangecalc.compute_range(repo)
    if not rng.new_branch and not rng.fast_forward:
        raise _args(
            f"non-fast-forward: {REMOTE}/{branch} has commits you do not have; "
            "fetch and rebase (carter push never forces)"
        )
    io.echo(f"carter push: {branch} -> {REMOTE} ({mask_userinfo(url)})")
    if not rng.commits:
        io.echo(f"Nothing to push: no commits beyond {rng.base_ref}.")
        return 0
    failed = sigcheck.check_signatures(repo, rng.commits, sigcheck.SigIdentity.from_config(cfg))
    io.echo(f"{len(rng.commits)} commit(s), {rng.base_label}:")
    for line in _commit_lines(repo, rng.commits, {f.key for f in failed}, io.red):
        io.echo(line)
    _show_changes(rng, io)
    for note in notes(url, branch):
        io.echo(note)
    if error := sigcheck.to_error(failed):
        raise error
    default = _default_branch(repo)
    typed = default is None or default == branch
    if opts.dry_run:
        io.echo(f"Dry run: nothing was pushed. It would ask: {_prompt(branch, typed)}".rstrip())
        return 0
    if not confirmed(io, _prompt(branch, typed), expect=branch if typed else "y"):
        io.echo("Aborted: nothing was pushed.")
        return 1
    return _push(repo, branch, opts, io)


def _show_changes(rng: rangecalc.RangeInfo, io: Io) -> None:
    io.echo(f"{len(rng.changes)} file(s) changed:")
    for change in rng.changes[:MAX_CHANGES_SHOWN]:
        io.echo(f"  {change.status} {clean(change.path)}")
    if len(rng.changes) > MAX_CHANGES_SHOWN:
        io.echo(f"  ... and {len(rng.changes) - MAX_CHANGES_SHOWN} more")
    if rng.sensitive:
        io.echo(io.red("These paths can run code on someone's machine or in CI; read them:"))
        for change in rng.sensitive:
            old = f" (was {clean(change.old_path)})" if change.old_path else ""
            io.echo(io.red(f"  {change.status} {clean(change.path)}{old}"))


def _push(repo: Path, branch: str, opts: Options, io: Io) -> int:
    args = ["push", "--recurse-submodules=no"]
    if opts.set_upstream:
        args.append("--set-upstream")
    args += [REMOTE, f"HEAD:refs/heads/{branch}"]
    proc = run.network_git(args, repo)
    for line in (proc.stdout + proc.stderr).splitlines():
        io.echo(f"  git: {mask_userinfo(clean(line, 300))}")
    if proc.returncode != 0:
        io.echo(f"git push failed (exit {proc.returncode}). Nothing was forced.")
        return 1
    io.echo(f"Pushed {branch} to {REMOTE}. Next: `carter pr` (it uses the agent's handoff).")
    return 0


__all__ = ["OWN_TERMINAL", "Io", "Options", "run_push", "ssh_host"]
