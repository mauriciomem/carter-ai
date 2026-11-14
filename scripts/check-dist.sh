#!/usr/bin/env bash
# Check the distributions in dist/ (one wheel, one sdist) before they are uploaded or merged.
#
#   bash scripts/check-dist.sh [EXPECTED_VERSION]
#
# Shared by the `build` job of release.yml (EXPECTED_VERSION = the released tag's version) and the
# `dist-check` job of ci.yml (no argument: the version in the wheel's file name), so the first
# run of these checks is never the release itself.
#
#   1. `twine check --strict` and `check-wheel-contents` (tool versions pinned here).
#   2. The wheel AND the sdist are installed into clean environments away from the checkout;
#      `carter --version` must report EXPECTED_VERSION (hatch-vcs read the tag), `carter --help`
#      must run, and the bundled data (skills, knowledge, mcp, templates) must come from the
#      installed package, not from a repository checkout.
# `carter` itself never reads or writes the user's Carter files here (no `carter install`).
# uv does use its own directories: it may download a Python into its data directory if none is
# found (CI has one), and reads its settings. Without an argument the version check only proves
# that the wheel's file name and `carter --version` agree; the tag check is the argument form.
# The sdist is built with the pins of `[tool.uv] build-constraint-dependencies` because uv reads
# them from pyproject.toml in the current directory, which is the repository root here.
set -euo pipefail

export UV_NO_CACHE=1 # nothing is restored from or saved to a cache

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

shopt -s nullglob
wheels=(dist/*.whl)
sdists=(dist/*.tar.gz)
if [ "${#wheels[@]}" -ne 1 ] || [ "${#sdists[@]}" -ne 1 ]; then
  echo "::error::expected exactly one wheel and one sdist in dist/" >&2
  exit 1
fi

expected="${1:-}"
if [ -z "$expected" ]; then
  name="${wheels[0]##*/}" # carter_ai-<version>-py3-none-any.whl
  name="${name#carter_ai-}"
  expected="${name%%-*}"
fi
echo "expected version: $expected"

uvx --from twine==7.0.0 twine check --strict "${wheels[0]}" "${sdists[0]}"
uvx --from check-wheel-contents==0.6.3 check-wheel-contents "${wheels[0]}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

for file in "${wheels[0]}" "${sdists[0]}"; do
  kind="wheel"
  case "$file" in *.tar.gz) kind="sdist" ;; esac
  venv="$work/$kind"
  uv venv --quiet "$venv"
  uv pip install --quiet --python "$venv/bin/python" "$root/$file"
  (
    cd "$work" # away from the checkout: the repository's own carter/ must not be importable
    shown="$("$venv/bin/carter" --version)"
    echo "$kind: $shown"
    if [ "${shown##* }" != "$expected" ]; then
      echo "::error::the $kind reports '$shown', expected version $expected" >&2
      exit 1
    fi
    "$venv/bin/carter" --help > /dev/null
    "$venv/bin/python" -I -c '
import pathlib

import carter
from carter.resources import data_dir

package = pathlib.Path(carter.__file__).resolve().parent
data = data_dir().resolve()
assert data == package / "_data", f"the data comes from {data}, not from the package"
for name in ("skills", "knowledge", "mcp", "templates"):
    assert any((data / name).iterdir()), f"no bundled {name}"
print("bundled data ok:", data)
'
  )
done
echo "dist ok"
