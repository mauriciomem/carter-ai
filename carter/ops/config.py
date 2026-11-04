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
from carter.identity.config import DEFAULT_FOOTER, default_path
from carter.identity.trailer import coauthor_trailer
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
        return cls(
            **common,
            author="llm" if res.role == "author" and res.tier == "t2" else "human",
            committer="llm" if res.tier == "t2" and res.commits == "allowed" else "human",
            signer_fpr=parsed.signing.fingerprint if res.tier == "t2" else "",
            coauthor_linked=trailer.startswith("Co-authored-by:"),
            tier=res.tier,
            role=res.role,
            role_source=res.role_source,
            commits=res.commits,
            refusal_reason=res.refusal_reason,
            coauthor_trailer=trailer,
            warnings=res.warnings,
        )
