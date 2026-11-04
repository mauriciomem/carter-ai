#!/bin/sh
# Managed by Carter (`carter guard`). Do not edit: a changed file is detected,
# kept as you left it, and reported by `carter guard status`.
# carter-guard @@VERSION@@: git hook backstop for agent shells (RFC-0007 section 4.4, C.6.4).
# POSIX sh only. The human path runs no external command and makes no git call.

@@IS_AGENT@@

@@BLOCK@@

event=${1-}
case "$event" in
  is-agent)
    # Used by tests and diagnostics: exit 0 = agent shell, 1 = anything else.
    is_agent
    exit $?
    ;;
  pre-push)
    if is_agent; then
      block
      exit 1
    fi
    exit 0
    ;;
  *)
    # commit-msg, prepare-commit-msg and post-commit arrive in slice 2b.
    exit 0
    ;;
esac
