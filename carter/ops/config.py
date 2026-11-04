"""Carter-ops configuration loader.

Identity comes from the schema-2 ``~/.carter/config.toml`` through ``carter.identity``
(tier, role and trailer are resolved at runtime); secrets come from the environment.
Nothing here reads, detects or substitutes the human's signing key, and loading never
writes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carter.identity import ConfigError, load_footer, load_identity, resolve
from carter.identity.coauthor import cached_link, human_identity
from carter.identity.config import DEFAULT_FOOTER, default_path
from carter.identity.errors import E_HUMAN_IDENTITY
from carter.identity.trailer import coauthor_trailer, noreply_email
from carter.identity.workspace import workspace_key


@dataclass(frozen=True)
class Config:
    footer: str = DEFAULT_FOOTER
    footer_warning: str | None = None
    github_token: str = ""

    # Resolved identity. Empty strings mean "no identity": E-CONFIG fails closed.
    tier: str = ""
    role: str = ""
    role_source: str = ""
    commits: str = "refused"
    refusal_reason: str = ""
    coauthor_trailer: str = ""
    author: str = ""  # "human" or "llm": who git records as the author
    committer: str = ""  # "human" below T2, "llm" at T2
    signer_fpr: str = ""  # the LLM key's fingerprint at T2 (public), else ""
    coauthor_linked: bool = False  # a Co-authored-by with a noreply address GitHub credits
    warnings: tuple[str, ...] = ()

    @classmethod
    def load(
        cls,
        config_path: Path | None = None,
        *,
        workspace: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Config:
        """Read the config and resolve the identity. Never writes.

        A defective identity section is ``commits=refused`` with ``E-CONFIG`` (no
        fallback to defaults); the footer is read separately and degrades on its own.
        """
        path = config_path or default_path()
        footer = load_footer(path)
        common: dict[str, Any] = {
            "footer": footer.footer,
            "footer_warning": footer.warning,
            "github_token": os.environ.get("GITHUB_TOKEN", ""),
        }
        try:
            parsed = load_identity(path)
        except ConfigError as exc:
            return cls(**common, refusal_reason=exc.code, warnings=(exc.detail,))
        res = resolve(
            parsed,
            workspace=workspace if workspace is not None else workspace_key(),
            env=os.environ if env is None else env,
        )
        trailer = coauthor_trailer(parsed, res)
        warnings = list(res.warnings)
        refusal, linked = res.refusal_reason, trailer.startswith("Co-authored-by:")
        if res.role == "author" and res.tier == "t2" and res.commits == "allowed":
            # Role b (K11): the trailer credits the human, read from git config in the working
            # directory; `linked` comes from the cache only (no network, no gh here).
            human = human_identity(os.getcwd(), noreply_email(parsed))
            if human.ok:
                trailer = human.trailer
                linked = bool(cached_link(human.email))
                if not linked:
                    warnings.append(
                        "your git email is not known to be linked to a GitHub account: the "
                        "Co-authored-by line may give you no credit (run `carter identity add` "
                        "or `carter check --host` in your own terminal to check)"
                    )
            else:
                trailer, refusal, linked = "", E_HUMAN_IDENTITY, False
                warnings.append(f"human identity: {human.problem}")
        return cls(
            **common,
            author="llm" if res.role == "author" and res.tier == "t2" and not refusal else "human",
            committer="llm" if res.tier == "t2" and not refusal else "human",
            signer_fpr=parsed.signing.fingerprint if res.tier == "t2" else "",
            coauthor_linked=linked,
            tier=res.tier,
            role=res.role,
            role_source=res.role_source,
            commits="refused" if refusal else res.commits,
            refusal_reason=refusal,
            coauthor_trailer=trailer,
            warnings=tuple(warnings),
        )
