#!/bin/sh
# Managed by Carter (`carter identity`). Do not edit: `carter check --host` compares this file with
# the hash recorded in ~/.carter/guard-state.json, and the plugin refuses to sign without it.
#
# git calls this as gpg.ssh.program (RFC-0007 App C.3). It signs only the configured LLM key, through
# the configured agent, and it never asks for a passphrase. Everything else is refused.
# POSIX sh only; the environment of the caller is not trusted and PATH is not used for the tools.
KEY=@@KEY@@
AGENT_SOCK=@@SOCK@@
NO_ASKPASS=@@FALSE@@
KEYGEN=@@KEYGEN@@
SIGNER=@@SIGNER@@
RUN_DIR=@@RUN_DIR@@

refuse() {
  printf '%s\n' @@REFUSAL@@ >&2
  printf 'carter-ssh-sign: %s\n' "$1" >&2
  exit 1
}

[ "${1-}" = "-Y" ] || refuse 'only ssh-keygen -Y operations are accepted'
op=${2-}

if [ -n "$AGENT_SOCK" ]; then
  SSH_AUTH_SOCK=$AGENT_SOCK
  export SSH_AUTH_SOCK
fi
SSH_ASKPASS=$NO_ASKPASS
SSH_ASKPASS_REQUIRE=force
export SSH_ASKPASS SSH_ASKPASS_REQUIRE

case $op in
  @@ALLOWED@@)
    # Verification: git pipes the signed payload on stdin, so stdin stays as it is.
    exec "$KEYGEN" "$@"
    ;;
  sign) ;;
  *) refuse 'this ssh-keygen -Y operation is not allowed' ;;
esac

# git's exact signing argv: -Y sign -n git -f <file holding the key> -U <buffer>. Nothing else.
[ $# -eq 8 ] || refuse 'sign takes exactly: -n git -f <key file> -U <buffer>'
[ "$3" = "-n" ] && [ "$4" = "git" ] && [ "$5" = "-f" ] && [ "$7" = "-U" ] ||
  refuse 'sign takes exactly: -n git -f <key file> -U <buffer> (-U is required)'
keyfile=$6
buffer=$8
[ -f "$keyfile" ] || refuse 'the key file is not a regular file'

line1=
line2=
{ IFS= read -r line1 || :; IFS= read -r line2 || :; } < "$keyfile" || refuse 'cannot read the key file'
[ -z "$line2" ] || refuse 'the key file holds more than one line'
set -f
set -- $line1
[ $# -ge 2 ] && [ "$1 $2" = "$KEY" ] || refuse 'the key is not the configured LLM key'

# Sign with a copy that this script wrote: the file git left in a shared temp directory is not
# trusted after the check above.
tmp=$(/usr/bin/mktemp -d "$RUN_DIR/sign.XXXXXX") || refuse 'cannot create a private directory'
trap '/bin/rm -rf "$tmp"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' "$KEY" > "$tmp/key.pub" || refuse 'cannot write the key copy'
"$SIGNER" -Y sign -n git -f "$tmp/key.pub" -U "$buffer" < /dev/null
exit $?
