# /// script
# requires-python = ">=3.11"
# ///
"""Carter AI Assistant Installer (legacy bootstrap shim).

The installation logic now lives in the ``carter`` package
(``carter.installer``) and is the same code used by the ``carter install``
CLI command. This shim is kept so the historical entry points keep working:

    ./install.sh [OPTIONS]
    uv run install.py [OPTIONS]

For the modern workflow, install the CLI and use it directly:

    uv tool install git+https://github.com/mauriciomem/carter-ai.git
    carter install [OPTIONS]

All options are forwarded unchanged to ``carter.installer.main``:

    --target {copilot,opencode,all}   Install target (default: all)
    --mcp                             Install and configure MCP servers
    --bot-name NAME                   Git commit author name (default: carter-bot)
    --uninstall                       Remove Carter installation
    --base-dir PATH                   Override install base directory (for testing)
    --quiet, -q                       Errors only
    --verbose, -v                     Detailed output
    --debug, -vv                      Debug output
    --help, -h                        Show this help
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the local package is importable when run directly from a checkout
# (e.g. `uv run install.py`), without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from carter.installer import main

if __name__ == "__main__":
    main()
