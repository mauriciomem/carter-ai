#!/bin/sh
# Run the opt-in OpenCode e2e/contract suite in one command, for CI and for a human.
#
#   tests/e2e/run.sh                       # the OpenCode on PATH (the tested 2.1.4)
#   tests/e2e/run.sh --version 2.1.2       # the warn band: installs @opencode/cli@2.1.2 under $BASE
#   tests/e2e/run.sh --version latest      # informational
#   tests/e2e/run.sh --opencode /path/to/opencode [-- pytest args...]
#
# Everything runs in isolated HOMEs under $CARTER_E2E_BASE (default /tmp/carter-e2e: short paths,
# macOS sockets need < 104 bytes), on their own ports, with a mock model only. Nothing touches your
# real ~/.config/opencode or ~/.carter. POSIX sh; needs node/npm only for --version.
set -eu

base=${CARTER_E2E_BASE:-/tmp/carter-e2e}
version=""
binary=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version=$2; shift 2 ;;
    --opencode) binary=$2; shift 2 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) break ;;
  esac
done

if [ -n "$version" ] && [ -z "$binary" ]; then
  prefix="$base/oc-$version"
  mkdir -p "$prefix"
  if [ ! -x "$prefix/node_modules/.bin/opencode" ]; then
    if [ "$version" = latest ]; then spec="@opencode/cli"; else spec="@opencode/cli@$version"; fi
    (cd "$prefix" && npm init -y >/dev/null 2>&1 && npm install --no-audit --no-fund "$spec" >/dev/null)
  fi
  binary="$prefix/node_modules/.bin/opencode"
fi

if [ -n "$binary" ]; then
  CARTER_E2E_OPENCODE=$binary
  export CARTER_E2E_OPENCODE
fi
if [ -z "${CARTER_E2E_NETNS:-}" ] && ! unshare -rn true >/dev/null 2>&1; then
  echo "run.sh: 'unshare -rn' is not available; running without a network namespace (mock provider only)." >&2
  echo "run.sh: on Ubuntu 24.04 you may need: sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0" >&2
  CARTER_E2E_NETNS=0
  export CARTER_E2E_NETNS
fi

CARTER_E2E=1
export CARTER_E2E
exec uv run pytest tests/e2e -p no:cacheprovider -q "$@"
