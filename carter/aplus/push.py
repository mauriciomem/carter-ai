"""``carter push``: validated push of the current branch to ``origin``.

Runs for a human: in their terminal, or in OpenCode's ``!`` shell when the plugin tagged it human
(AD1; the click layer enforces that before anything here runs). It asks nothing. There is no
passthrough: the only choices are ``--dry-run`` and ``--set-upstream``. Nothing can be forced, no
tag, other branch or other remote can be named, and the refspec is always
``HEAD:refs/heads/<current branch>`` on ``origin``.

Order (nothing touches the network before the local checks, because ``fetch`` itself would
run a repository-configured credential helper or SSH command):

1. branch and push URL; 2. repo config (hooks, helpers, URL rewrites) and SSH config: findings
are one warning line (the broker refuses them, `carter push` does not); 3. fetch the target
ref; 4. the
commit range; 5. signature check of LLM-committed commits (a failure refuses, with the commits);
6. push. A normal run ends in one line; ``-v`` adds the commits, the files and git's own output.

``fetch`` and ``push`` use the human's own credentials (``run.network_git``) but never run
repository hooks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from carter import ui
from carter.aplus import rangecalc, repocfg, run, sigcheck, sshcfg
from carter.aplus.findings import Finding, mask_userinfo
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.identity import load_identity
from carter.identity.errors import E_APLUS_ARGS, IdentityError
from carter.identity.schema import IdentityConfig
from carter.install.paths import carter_config_path, guard_state_path

# The one sentence that says who pushes and where (templates, skills and the global rule use it).
# the human may also run it in OpenCode's `!` shell (no TTY needed), never through an agent.
OWN_TERMINAL = (
    "Run `carter push` yourself, in your terminal or as `!carter push` in OpenCode, "
    "not through an agent."
)
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


def _commit_lines(repo: Path, commits: tuple[str, ...]) -> list[str]:
    lines = []
    for sha in commits[:MAX_COMMITS_SHOWN]:
        raw = run.git(["cat-file", "commit", sha], repo).stdout
        head, _, body = raw.partition("\n\n")
        signed = any(ln.startswith("gpgsig") for ln in head.splitlines())
        mark = "signed  " if signed else "unsigned"
        lines.append(f"{sha[:12]}  {mark}  {clean(body.split(chr(10), 1)[0], 72)}")
    if len(commits) > MAX_COMMITS_SHOWN:
        lines.append(f"... and {len(commits) - MAX_COMMITS_SHOWN} more")
    return lines


def _signed_count(repo: Path, commits: tuple[str, ...]) -> int:
    count = 0
    for sha in commits:
        head = run.git(["cat-file", "commit", sha], repo).stdout.partition("\n\n")[0]
        count += any(ln.startswith("gpgsig") for ln in head.splitlines())
    return count


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
    repo: Path, url: str, *, base_dir: Path | None, home: Path, dry_run: bool = False
) -> tuple[IdentityConfig, int | None]:
    """Repo-config and SSH-config checks before anything touches the network.

    Findings are one warning line (the broker refuses them; `carter push` goes on, as the user's own
    command). With ``--dry-run`` nothing is fetched, because fetching would run them. Returns the
    identity config and ``None`` to go on, or an exit code to stop with."""
    cfg, found = _local_checks(repo, url, base_dir, home)
    if not found:
        return cfg, None
    names = ", ".join(dict.fromkeys(f"{f.scope} {f.key}" for f in found[:3]))
    more = f" (+{len(found) - 3})" if len(found) > 3 else ""
    ui.warn(f"settings could run code with your credentials or reroute the push: {names}{more}")
    for finding in found:
        ui.detail(finding.render())
    if dry_run:
        ui.info("dry run: nothing was fetched or pushed (fetching would run those settings)")
        return cfg, 0
    return cfg, None


def run_push(
    repo: Path, opts: Options, *, base_dir: Path | None = None, home: Path | None = None
) -> int:
    """Run the flow in ``repo``; 0 = pushed, dry run or nothing to push, 1 = failed."""
    try:
        return _flow(repo, opts, base_dir, home or Path.home())
    except (run.RunError, sigcheck.SigCheckError) as exc:
        raise _args(str(exc)) from exc


def _flow(repo: Path, opts: Options, base_dir: Path | None, home: Path) -> int:
    branch = _out(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if not branch:
        raise _args("detached HEAD: check out the branch you want to push")
    url = _out(repo, ["remote", "get-url", "--push", REMOTE])
    if url is None:
        raise _args(f"no remote named {REMOTE}")
    cfg, stop = vet_local(repo, url, base_dir=base_dir, home=home, dry_run=opts.dry_run)
    if stop is not None:
        return stop
    _fetch_target(repo, branch)
    rng = rangecalc.compute_range(repo)
    if not rng.new_branch and not rng.fast_forward:
        raise _args(
            f"non-fast-forward: {REMOTE}/{branch} has commits you do not have; "
            "fetch and rebase (carter push never forces)"
        )
    ui.detail(f"{branch} -> {REMOTE} ({mask_userinfo(url)})")
    where = f"{branch} → {REMOTE}"
    if not rng.commits:
        ui.summary(where, f"up to date, no commits beyond {rng.base_ref}")
        return 0
    failed = sigcheck.check_signatures(repo, rng.commits, sigcheck.SigIdentity.from_config(cfg))
    for line in _commit_lines(repo, rng.commits):
        ui.detail(line)
    _show_changes(rng)
    if error := sigcheck.to_error(failed):
        raise error
    count = len(rng.commits)
    ui.detail(f"{count} commit(s), {rng.base_label}")
    noun = f"{count} commit{'s' if count != 1 else ''}"
    if opts.dry_run:
        ui.summary(where, noun, "dry run: nothing pushed")
        return 0
    return _push(repo, branch, opts, where, noun, _signed_count(repo, rng.commits), count)


def _show_changes(rng: rangecalc.RangeInfo) -> None:
    for change in rng.changes[:MAX_CHANGES_SHOWN]:
        ui.detail(f"{change.status} {clean(change.path)}")
    if len(rng.changes) > MAX_CHANGES_SHOWN:
        ui.detail(f"... and {len(rng.changes) - MAX_CHANGES_SHOWN} more files")
    if rng.sensitive:
        shown = ", ".join(clean(c.path, 60) for c in rng.sensitive[:3])
        more = f" (+{len(rng.sensitive) - 3})" if len(rng.sensitive) > 3 else ""
        ui.warn(f"changes paths that can run code on someone's machine or in CI: {shown}{more}")


def _push(
    repo: Path, branch: str, opts: Options, where: str, noun: str, signed: int, count: int
) -> int:
    args = ["push", "--recurse-submodules=no"]
    if opts.set_upstream:
        args.append("--set-upstream")
    args += [REMOTE, f"HEAD:refs/heads/{branch}"]
    proc = run.network_git(args, repo)
    lines = [mask_userinfo(clean(ln, 300)) for ln in (proc.stdout + proc.stderr).splitlines()]
    for line in lines:
        ui.detail(f"git: {line}")
    if proc.returncode != 0:
        why = " | ".join(ln.strip() for ln in lines if ln.strip())[-300:]
        ui.fail(f"git push failed (exit {proc.returncode}): {why}", "nothing was forced")
        return 1
    state = (
        "signed" if signed == count else "unsigned" if not signed else f"{count - signed} unsigned"
    )
    ui.summary(where, f"{noun} ({state})")
    return 0


__all__ = ["OWN_TERMINAL", "Options", "run_push", "ssh_host"]
