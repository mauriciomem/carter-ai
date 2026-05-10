# /// script
# requires-python = ">=3.11"
# ///
"""Carter-ops attribution helpers.

Provides git author string construction and Jira comment footer injection.
"""
from __future__ import annotations

from config import Config


def git_author(cfg: Config) -> str:
    """Return the --author string for git commit."""
    return f"{cfg.bot_name} <{cfg.bot_email}>"


def git_author_flag(cfg: Config) -> list[str]:
    """Return the CLI flags for git commit author override."""
    return [f"--author={git_author(cfg)}"]


def jira_footer(cfg: Config) -> str:
    """Return the Jira comment footer."""
    return f"\n\n{cfg.footer}"


def append_jira_footer(body: str, cfg: Config) -> str:
    """Append the carter-bot footer to a Jira comment body."""
    return body.rstrip() + jira_footer(cfg)


def attribution_summary(cfg: Config, domain: str) -> str:
    """Return a human-readable attribution summary for dry-run output."""
    if domain == "git":
        return f"Author: {cfg.bot_name}, Signed-by: user ({cfg.signing_key})"
    elif domain == "jira":
        return f"Footer: {cfg.footer}"
    return f"Bot: {cfg.bot_name}"
