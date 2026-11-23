"""Write a whole ``config.toml`` for a test.

Carter never writes that file any more (``carter.identity.writer`` owns only
``config-managed.toml``). A test that needs a configured home builds the human file here;
the derived values in it are what an older install left, so they exercise the legacy read.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path
from typing import Any

from carter.identity.schema import (
    SCHEMA_VERSION,
    SECTIONS,
    TABLE_ACCESS,
    TABLE_WORKSPACES,
    IdentityConfig,
)
from carter.identity.writer import _str, _value

_BARE = re.compile(r"[A-Za-z0-9_-]+")


def _body(obj: Any) -> list[str]:
    return [
        f"{f.name} = {_value(getattr(obj, f.name))}"
        for f in fields(obj)
        if getattr(obj, f.name) != f.default
    ]


def dumps(cfg: IdentityConfig) -> str:
    """``cfg`` as a schema-2 ``config.toml``: only what differs from the defaults."""
    out = ["# a test config", f"schema = {SCHEMA_VERSION}"]
    for attr, path, _cls in SECTIONS:
        body = _body(getattr(cfg, attr))
        if body:
            out += ["", "[" + ".".join(path) + "]", *body]
    if cfg.access:
        keys = [(k if _BARE.fullmatch(k) else _str(k), v) for k, v in cfg.access]
        out += ["", f"[{TABLE_ACCESS}]", *(f"{k} = {_value(v)}" for k, v in keys)]
    for ws_path, ws in cfg.workspaces.items():
        out += ["", f"[{TABLE_WORKSPACES}.{_str(ws_path)}]", *_body(ws)]
    return "\n".join(out) + "\n"


def write_config(cfg: IdentityConfig, path: Path, **_ignored: Any) -> bool:
    """Write ``cfg`` to ``path`` as a human ``config.toml``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(cfg)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return True
