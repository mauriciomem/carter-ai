"""Identity errors. Codes and wording follow RFC-0007 Appendix B §2 verbatim.

Slice 1 needs two codes. Plan 002 step 14 grows this module into the full registry
(and the skill error-table parity test); until then these are the only ``E-*`` strings.
"""

from __future__ import annotations

E_CONFIG = "E-CONFIG"
MSG_CONFIG = "config.toml is invalid; agent commits are disabled until fixed."

E_ROLE_B_TIER = "E-ROLE-B-TIER"
MSG_ROLE_B_TIER = "Role `author` needs a signing key; refusing (no downgrade)."


class IdentityError(Exception):
    """An identity failure with a stable ``code``.

    ``str(error)`` is the user-facing registry message. ``detail`` is a short technical
    hint (a path, a key name, a TOML line); it never contains values read from the
    config, so a secret cannot leak through an error.
    """

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
