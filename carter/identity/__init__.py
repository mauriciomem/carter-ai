"""Carter identity: schema-2 config reader and the pure tier/role resolver.

Stdlib-only on purpose (the gate's neighbours, the plugin's identity entry and the guard import
it). The public names are resolved on first use (PEP 562) so that importing a submodule such as
``carter.identity.rules`` or ``carter.identity.env`` does not load the config reader, the error
registry and ``importlib.resources`` (about 25 ms).
"""

from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from carter.identity.config import ConfigError, FooterResult, load_footer, load_identity
    from carter.identity.errors import IdentityError
    from carter.identity.resolve import (
        Resolution,
        RoleResolution,
        configured_tier,
        effective_tier,
        is_noreply_email,
        resolve,
        resolve_role,
    )
    from carter.identity.schema import IdentityConfig, schema_names

_SOURCES = {
    "ConfigError": "config",
    "FooterResult": "config",
    "load_footer": "config",
    "load_identity": "config",
    "IdentityError": "errors",
    "Resolution": "resolve",
    "RoleResolution": "resolve",
    "configured_tier": "resolve",
    "effective_tier": "resolve",
    "is_noreply_email": "resolve",
    "resolve": "resolve",
    "resolve_role": "resolve",
    "IdentityConfig": "schema",
    "schema_names": "schema",
}

__all__ = [
    "ConfigError",
    "FooterResult",
    "IdentityConfig",
    "IdentityError",
    "Resolution",
    "RoleResolution",
    "configured_tier",
    "effective_tier",
    "is_noreply_email",
    "load_footer",
    "load_identity",
    "resolve",
    "resolve_role",
    "schema_names",
]
assert sorted(_SOURCES) == sorted(__all__)  # the two lists must not drift


class _LazyPackage(ModuleType):
    """``resolve`` is both a submodule and a function. Importing the submodule binds the module
    to the package attribute, so the function is returned explicitly: the same answer the eager
    package gave before names were resolved lazily."""

    def __getattribute__(self, name: str) -> Any:
        if name == "resolve":
            return getattr(import_module("carter.identity.resolve"), "resolve")  # noqa: B009
        return super().__getattribute__(name)


sys.modules[__name__].__class__ = _LazyPackage


def __getattr__(name: str) -> Any:
    module = _SOURCES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"carter.identity.{module}"), name)
    if name != "resolve":
        globals()[name] = value
    return value
