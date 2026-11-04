"""B's context and the checks it runs before any credential is used (RFC-0007 App C.5).

B reuses the A+ checks in **refuse** mode (A+ shows the same findings and asks):

1. the repo-config check (``carter.aplus.repocfg``): ``git config --list --show-scope
   --show-origin --includes`` judged by scope, Carter's own ``include.path`` and hooks allowed;
2. the SSH client config (``carter.aplus.sshcfg``): the passwd-home ``~/.ssh/config`` pre-scan for
   ``Match ... exec`` (including ``!exec`` and ``exec=``), then ``<ssh_bin_dir>/ssh -G
   git@github.com`` and the ``ProxyCommand`` / ``LocalCommand`` / ``PermitLocalCommand yes`` /
   ``KnownHostsCommand`` rule;
3. the signature choke point (``carter.aplus.sigcheck``) for LLM-committed commits.

Every git/ssh call here runs inside ``run.forced_env``: its base is the from-scratch environment
of B, never the OpenCode server's. Each is hardened (``GIT_CONFIG_NOSYSTEM``, ``core.fsmonitor``,
an empty ``core.hooksPath``, no credential helper, no pager). The two inert reads that precede the
config listing (``rev-parse``, ``remote get-url``) cannot run repository code under that
hardening; nothing networked or signature-related runs before the listing passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from carter.aplus import repocfg, run, sshcfg
from carter.aplus.findings import Finding, to_error
from carter.broker import refusal
from carter.broker.env import Tools, account_home
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.identity import load_identity
from carter.identity.errors import E_B_ARGS, IdentityError
from carter.identity.schema import IdentityConfig
from carter.install.paths import carter_config_path, guard_state_path, run_dir

__all__ = ["Context", "load_context", "require_clean", "vet"]


@dataclass(frozen=True)
class Context:
    cfg: IdentityConfig
    owned: repocfg.CarterOwned
    tools: Tools
    home: Path  # the account home: child HOME and the ~/.ssh/config scan
    base_dir: Path | None = None

    @property
    def carter_dir(self) -> Path:
        return run_dir(self.base_dir).parent


def load_context(*, git: str, gh: str, base_dir: Path | None = None) -> Context:
    """Config, ownership and tools. A broken ``config.toml`` refuses (``E-CONFIG``)."""
    cfg = load_identity(carter_config_path(base_dir))
    read = load_or_empty_readonly(guard_state_path(base_dir))
    owned = repocfg.CarterOwned.from_state(read.state if read.status == "ok" else GuardState())
    tools = Tools(git=git, gh=gh, ssh_bin_dir=cfg.signing.ssh_bin_dir)
    return Context(cfg, owned, tools, account_home(), base_dir)


def vet(repo: Path, url: str, ctx: Context) -> list[Finding]:
    """Repo-config and SSH-config findings for pushing ``repo`` to ``url`` (empty = clean)."""
    try:
        found = repocfg.check_repo_config(repo, origin_url=url, owned=ctx.owned)
    except repocfg.RepoCheckError as exc:
        raise refusal(E_B_ARGS, f"cannot inspect the repository ({exc})") from exc
    found += sshcfg.check_ssh_config(ctx.home, ssh_bin_dir=ctx.tools.ssh_bin_dir)
    return found


def require_clean(findings: list[Finding]) -> None:
    """Raise the registry error for the first finding (``E-B-REPOCFG`` or ``E-B-UNSIGNED``)."""
    error: IdentityError | None = to_error(findings)
    if error is not None:
        raise error


def forced(env: dict[str, str]):  # type: ignore[no-untyped-def]
    """``run.forced_env`` re-exported so callers import one module."""
    return run.forced_env(env)
