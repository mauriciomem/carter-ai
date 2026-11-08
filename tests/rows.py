"""Check rows (``ui.items``) read back as ``OK    area: text`` (many tests are about content)."""

from __future__ import annotations

import re
from typing import Any

from click.testing import CliRunner

LEVELS = {"✓": "OK", "!": "WARN", "✗": "RED", "·": "INFO"}
_ROW = re.compile(r"^([✓!✗·]) ([^:\n]+): ", re.M)


def legacy(text: str) -> str:
    return _ROW.sub(lambda m: f"{LEVELS[m[1]]:<5} {m[2]}: ", text)


class Out:
    """A click ``Result`` whose ``output`` has the rows in the ``LEVEL  area: text`` shape."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.output = legacy(result.output)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._result, name)


def invoke(*args: str, env: dict[str, str] | None = None) -> Out:
    from carter.cli import main

    return Out(CliRunner().invoke(main, list(args), env=env, catch_exceptions=False))


def check_host(*args: str) -> Out:
    return invoke("check", "--host", "-v", *args)
