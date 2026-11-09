"""The identity mode: interactive, or a review-only CI run.

Stdlib-only and pure, like the resolver that imports it: no file, no process, only the
environment mapping and the ``[identity] mode`` string the caller passes in.

Precedence: ``CARTER_IDENTITY_MODE`` > ``[identity] mode`` > ``auto`` (an empty value is unset).
``auto`` is ``review`` when a CI is detected and ``interactive`` otherwise. Carter never infers
that it may commit in CI: inside a detected CI an explicit ``interactive`` is refused too (that
is context C, not built), and so are the unbuilt contexts C and D (``commit``, ``scheduled``).
No CI context is ever derived from a workflow file. An error never echoes the offending value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

ENV_MODE = "CARTER_IDENTITY_MODE"
MODES = ("auto", "interactive", "review")
UNBUILT = ("commit", "scheduled", "ci", "c", "d")  # CI contexts C and D: deferred
_TRUE = ("1", "true", "yes", "on")


def in_ci(env: Mapping[str, str]) -> bool:
    """Is this a CI run? ``GITHUB_ACTIONS=true`` or a truthy ``CI``; nothing else counts."""
    return env.get("GITHUB_ACTIONS", "").lower() == "true" or env.get("CI", "").lower() in _TRUE


@dataclass(frozen=True)
class ModeResolution:
    """``mode`` is ``interactive`` or ``review``, or empty when ``error`` is set."""

    mode: str
    source: str
    error: str = ""


def _fail(source: str, text: str) -> ModeResolution:
    return ModeResolution("", source, text)


def resolve_mode(configured: str, env: Mapping[str, str]) -> ModeResolution:
    """Resolve the mode for ``[identity] mode`` = ``configured`` and the environment ``env``."""
    from_env = env.get(ENV_MODE, "")
    value, source = (
        (from_env, "env") if from_env else (configured, "config") if configured else ("", "")
    )
    where = ENV_MODE if source == "env" else "[identity] mode"
    ci = in_ci(env)
    if value.lower() in UNBUILT:
        return _fail(
            source,
            f"{where} asks for a CI context that is not built (contexts C and D);"
            " only `review` exists in CI",
        )
    if value and value not in MODES:
        return _fail(source, f"{where} is not one of {list(MODES)}")
    if value == "interactive" and ci:
        return _fail(
            source,
            f"{where} = interactive inside CI would be context C (commits), which is not built; "
            "a CI run is `review`",
        )
    if value in ("interactive", "review"):
        return ModeResolution(value, source)
    # unset or `auto`
    return ModeResolution("review", "auto") if ci else ModeResolution("interactive", "default")
