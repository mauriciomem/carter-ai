"""Carter installer package.

The installer was split from a single 1199-LOC ``carter/installer.py`` module into
this package along its internal seams, mirroring the ``carter/ops/`` layout.
``carter/installer.py`` remains the public entry point: it imports
these leaf modules and defines the orchestration + the handful of helpers that tests
monkeypatch through the ``carter.installer`` namespace. Import from ``carter.installer``
(or ``carter install``) — not from these submodules directly.
"""

from __future__ import annotations
