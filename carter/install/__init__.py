"""Carter installer package.

The installer was split from a single 1199-LOC ``carter/installer.py`` module into
this package along its internal seams (plan 004 step 8, ADR-0007 layout mirror of
``carter/ops/``). ``carter/installer.py`` remains the public entry point: it imports
these leaf modules and defines the orchestration + the handful of helpers that tests
monkeypatch through the ``carter.installer`` namespace. Import from ``carter.installer``
(or ``carter install`` / ``install.sh``) — not from these submodules directly.
"""

from __future__ import annotations
