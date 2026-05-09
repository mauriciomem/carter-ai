#!/usr/bin/env bash
set -euo pipefail
exec uv run "$(dirname "$0")/install.py" "$@"
