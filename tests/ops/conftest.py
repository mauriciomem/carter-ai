"""Shared fixtures for carter-ops tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure ops directory is on path for imports
OPS_DIR = Path(__file__).resolve().parent.parent.parent / "ops"
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))
