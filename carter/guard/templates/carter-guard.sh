#!/bin/sh
# Managed by Carter (`carter guard`). Do not edit: a changed file is detected,
# kept as you left it, and reported by `carter guard status`.
# carter-guard @@VERSION@@: git hook backstop for agent shells.
# POSIX sh only. The human path runs no external command and makes no git call.
# Events: pre-push (blocks an agent push), prepare-commit-msg (every reject check, then the
# idempotent trailer), commit-msg (the trailer is still there) and post-commit (warn only). The
# script never calls `carter` or Python.
# Roles: the script never reads the role. The committer is always the LLM; when the commit's
# author is the LLM (role author) the trailer is the human's `Co-authored-by: <user.name> <user.email>`
# (read with `git config` in the repo), otherwise the LLM's.

# The messages quote commands in backticks inside single quotes on purpose: nothing expands.
# shellcheck disable=SC2016

@@IS_AGENT@@

@@BLOCK@@

@@MESSAGES@@

@@HUMAN_RULES@@

# Carter's own git file, passed by the hook command; the hook tier is read from it directly
# (`--file ... --includes`), never through the user's global config.
cfg=${CARTER_GUARD_CONFIG-}
[ -n "$cfg" ] || cfg=${HOME-}/.carter/gitconfig
chome=${cfg%/*}
nl='
'

carter_key() { git config --file "$cfg" --includes --get "carter.$1" 2>/dev/null; }

# A usable human identity (the vectors in tests/data/human_identity_vectors.json hold
# this and coauthor.validate to the same answers). Prints nothing when usable, else one problem.
# $1 name, $2 email, $3 the LLM's email. The problem tokens are a fixed set: safe to print.
human_problem() {
  case $1 in *[![:space:]]*) ;; *) printf missing-name; return 0 ;; esac
  case $2 in *[![:space:]]*) ;; *) printf missing-email; return 0 ;; esac
  case $1 in *[[:cntrl:]]* | *'<'* | *'>'* | ' '* | *' ') printf bad-name; return 0 ;; esac
  case $2 in
    *[[:cntrl:]]* | *[[:space:]]* | *'<'* | *'>'* | *@*@* | @* | *@) printf bad-email; return 0 ;;
    *@*) ;;
    *) printf bad-email; return 0 ;;
  esac
  hp_email=$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')
  hp_llm=$(printf '%s' "$3" | tr '[:upper:]' '[:lower:]')
  [ "$hp_email" = "$hp_llm" ] && { printf llm-email; return 0; }
  human_fallback_email "$hp_email" && { printf fallback; return 0; }
  human_fallback_pair "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" "$hp_email" && { printf fallback; return 0; }
  return 0
}

# The email of the commit's author as the hook must judge it: `git var GIT_AUTHOR_IDENT` (for an
# amend or `-C` git exports the commit's real author; for a rebase the picked commit's), except
# during a cherry-pick, where git runs the hook in-process with the shell's author and
# CHERRY_PICK_HEAD names the commit whose author the new commit keeps.
author_email() {
  gd=$(git rev-parse --git-dir 2>/dev/null) || gd=
  if [ -n "$gd" ] && [ -f "$gd/CHERRY_PICK_HEAD" ]; then
    pick=$(cat "$gd/CHERRY_PICK_HEAD" 2>/dev/null)
    pick=${pick%%[!0-9a-f]*}
    [ -n "$pick" ] && git log -1 --format=%ae "$pick" 2>/dev/null && return 0
  fi
  ident=$(git var GIT_AUTHOR_IDENT 2>/dev/null) || return 1
  ident=${ident#*<}
  printf '%s\n' "${ident%%>*}"
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

tier_of() {
  t=$(carter_key tier)
  case $t in t1 | t2) printf '%s' "$t" ;; *) printf t0 ;; esac
}

# sets TRAILER_KEY and TRAILER_LINE: Co-authored-by at T1/T2 (login from the noreply email),
# Assisted-by: Carter at T0 and whenever the email is missing. At T2, when the commit's author is
# the LLM (role author), the line is the human's, from `git config` in the repo; an unusable human
# identity rejects the commit (nothing is ever downgraded to the LLM's own trailer).
trailer_for() {
  TRAILER_KEY=Assisted-by
  TRAILER_LINE='Assisted-by: Carter'
  [ "$1" = t0 ] && return 0
  email=$(carter_key llmEmail)
  [ -n "$email" ] || return 0
  login=${email#*+}
  login=${login%%@*}
  TRAILER_KEY=Co-authored-by
  TRAILER_LINE="Co-authored-by: $login <$email>"
  [ "$1" = t2 ] || return 0
  author=$(author_email) || return 0
  [ "$(lower "$author")" = "$(lower "$email")" ] || return 0
  hname=$(git config --get user.name 2>/dev/null)
  hmail=$(git config --get user.email 2>/dev/null)
  problem=$(human_problem "$hname" "$hmail" "$email")
  [ -z "$problem" ] ||
    reject "$M_HUMAN_0" "$M_HUMAN_1$problem" "$R_HUMAN"
  TRAILER_LINE="Co-authored-by: $hname <$hmail>"
}

reject() {
  printf '%s\n' "$@" >&2
  exit 1
}

signcfg() { reject "carter-guard: commit rejected (@@SIGNCFG_CODE@@): $1" "$R_SIGNCFG"; }

prepare_commit_msg() {
  tier=$(tier_of)
  if [ "$tier" = t2 ]; then
    email=$(carter_key llmEmail)
    [ -n "$email" ] && [ -n "${GIT_COMMITTER_EMAIL-}" ] && [ -n "${CARTER_IDENTITY-}" ] ||
      reject "$M_NOIDENT_0" "$R_NOIDENT" "$STALE_HINT" "$RESTART_HINT"
    ident=$(git var GIT_COMMITTER_IDENT 2>/dev/null) ||
      reject "$M_NOIDENT_0" "$R_NOIDENT" "$STALE_HINT" "$RESTART_HINT"
    got=${ident#*<}
    got=${got%%>*}
    [ "$got" = "$email" ] ||
      reject "$M_COMMITTER_0$got$M_COMMITTER_1$email$M_COMMITTER_2" "$R_COMMITTER" "$RESTART_HINT"
    [ "$(git config --type=bool --get commit.gpgsign 2>/dev/null)" = true ] ||
      signcfg 'commit.gpgsign is not true'
    [ "$(git config --get gpg.format 2>/dev/null)" = ssh ] || signcfg 'gpg.format is not ssh'
    case $(git config --get user.signingkey 2>/dev/null) in
      key::*) ;;
      *) signcfg 'user.signingkey is not a key:: literal' ;;
    esac
    [ "$(git config --get gpg.ssh.program 2>/dev/null)" = "$chome/bin/carter-ssh-sign" ] ||
      signcfg 'gpg.ssh.program is not the Carter shim'
    # An agent may not change a commit's author (--amend --reset-author, --author on an amend, or
    # --amend -C <another commit>): git shows the new author in the hook, the commit being replaced
    # is HEAD. (The source argument $3 is the reused commit, which is not HEAD for -c/-C; comparing
    # with HEAD also stops `--amend -C <the LLM's commit>`. A plain `-C` that changes the author
    # of a human HEAD is refused too: it cannot be told from an amend here.)
    if [ "${2-}" = commit ]; then
      was=$(git log -1 --format=%ae HEAD 2>/dev/null)
      now=$(author_email)
      if [ -n "$was" ] && [ "$(lower "$was")" != "$(lower "$email")" ] &&
        [ "$(lower "$was")" != "$(lower "$now")" ]; then
        reject "$M_AUTHOR_0" "$R_AUTHOR"
      fi
    fi
  elif [ "$(git config --type=bool --get commit.gpgsign 2>/dev/null)" = true ]; then
    reject "$M_NOSIGN_0"
  fi
  trailer_for "$tier"
  git interpret-trailers --in-place --if-exists addIfDifferent --trailer "$TRAILER_LINE" "$1" ||
    reject "$M_TRAILER_0$TRAILER_KEY$M_TRAILER_1" "$R_TRAILER"
}

commit_msg() {
  trailer_for "$(tier_of)"
  parsed=$(git interpret-trailers --parse "$1" 2>/dev/null | tr '[:upper:]' '[:lower:]')
  wanted=$(printf '%s' "$TRAILER_LINE" | tr '[:upper:]' '[:lower:]')
  case "$nl$parsed$nl" in
    *"$nl$wanted$nl"*) ;;
    *) reject "$M_TRAILER_0$TRAILER_KEY$M_TRAILER_1" "$R_TRAILER" ;;
  esac
}

# Warn only: never undoes, and git ignores the exit status of post-commit anyway.
post_commit() {
  tier=$(tier_of)
  head=$(git rev-parse --short HEAD 2>/dev/null) || return 0
  bad=
  if [ "$tier" = t2 ]; then
    want=$(carter_key llmFingerprint)
    got=$(git -c gpg.format=ssh -c "gpg.ssh.allowedSignersFile=$chome/hooks/allowed_signers" \
      -c "gpg.ssh.program=$chome/bin/carter-ssh-sign" log -1 --format=%GF HEAD 2>/dev/null)
    [ -n "$want" ] && [ "$got" = "$want" ] || bad=1
  else
    all=$(git cat-file commit HEAD 2>/dev/null)
    hdr=${all%%"$nl$nl"*}
    case $hdr in *"${nl}gpgsig "*) bad=1 ;; esac
  fi
  [ -n "$bad" ] || return 0
  printf '%s\n%s\n' "$M_UNSIGNED_0$head$M_UNSIGNED_1" "$R_UNSIGNED" >&2
  (
    umask 077
    mkdir -p "$chome/state/audit" &&
      printf '%s @@UNSIGNED_CODE@@ %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$head" >>"$chome/state/audit/guard.log"
  ) 2>/dev/null
  return 0
}

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
  prepare-commit-msg | commit-msg | post-commit)
    shift
    is_agent || exit 0
    case "$event" in
      prepare-commit-msg) prepare_commit_msg "$@" ;;
      commit-msg) commit_msg "$@" ;;
      post-commit) post_commit ;;
    esac
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
