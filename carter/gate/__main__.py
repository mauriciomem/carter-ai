"""``python -I -m carter.gate --json [--cwd DIR] [--skip-groups CSV]`` (freeze G6).

The command line to judge arrives on stdin as UTF-8. One JSON object goes to stdout:
``{"decision": "allow"|"deny", "rule": str|null, "message": str|null}``; exit 0 = allow, exit 1 =
deny. Input over 1 MiB, NUL bytes and invalid UTF-8 are a deny of rule ``gate-input``. Any internal
error prints no JSON and exits 3 (the plugin treats every other outcome as ``E-GATE-FAIL`` and
refuses the command); the error text never contains the command.
"""

from __future__ import annotations

import json
import sys

from carter.gate import MAX_BYTES, check, refuse


def parse_args(argv: list[str]) -> tuple[bool, str | None, tuple[str, ...]] | None:
    as_json, cwd, i = False, None, 0
    skip: tuple[str, ...] = ()
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            as_json = True
        elif a in ("--cwd", "--skip-groups") and i + 1 < len(argv):
            i += 1
            if a == "--cwd":
                cwd = argv[i]
            else:
                skip = tuple(s for s in argv[i].split(",") if s)
        else:
            return None
        i += 1
    return as_json, cwd, skip


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(sys.argv[1:] if argv is None else argv)
    if parsed is None:
        sys.stderr.write(
            "usage: python -I -m carter.gate --json [--cwd DIR] [--skip-groups CSV] < command\n"
        )
        return 2
    as_json, cwd, skip = parsed
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        try:
            text = data.decode("utf-8") if len(data) <= MAX_BYTES else ""
            decision = check(text, cwd, skip) if len(data) <= MAX_BYTES else None
        except UnicodeDecodeError:
            decision = None
        if decision is None:
            from carter.gate.rules import rules_hint  # noqa: PLC0415

            decision = refuse("gate-input", rules_hint("gate-input"))
    except Exception:  # noqa: BLE001 - fail closed without echoing anything of the command
        sys.stderr.write("carter.gate: internal error\n")
        return 3
    if as_json:
        sys.stdout.write(
            json.dumps(
                {"decision": decision.decision, "rule": decision.rule, "message": decision.message}
            )
            + "\n"
        )
    elif decision.message:
        sys.stdout.write(decision.message + "\n")
    return 0 if decision.decision == "allow" else 1


if __name__ == "__main__":
    raise SystemExit(main())
