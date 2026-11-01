"""Carter identity: schema-2 config reader and the pure tier/role resolver.

Stdlib-only on purpose (later slices import it from the gate and the plugin entry).
"""

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
