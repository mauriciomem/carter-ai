"""Keep generated blocks in text files (the carter-ops skill) equal to their data files.

The skill embeds two blocks rendered from data, never typed by hand: the forbidden list
(``g2_rules.json``) and the error table (``errors.py``). ``expected_blocks`` renders them,
``check_text`` reports drift together with the expected block, and ``sync_text`` rewrites
them. Developers refresh a file with ``python -m carter.identity.blocks <path>``; CI runs
the parity tests, which use ``check_text``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from carter.identity import errors, rules


def expected_blocks() -> dict[str, tuple[str, str, str]]:
    """name -> (begin marker, end marker, rendered block including both markers)."""
    return {
        "forbidden": (rules.BEGIN_MARK, rules.END_MARK, rules.render_forbidden_block()),
        "errors": (errors.ERRORS_BEGIN, errors.ERRORS_END, errors.render_error_table()),
    }


def extract(text: str, begin: str, end: str) -> str | None:
    """The block from ``begin`` to ``end`` inclusive, plus its newline; ``None`` if absent."""
    start = text.find(begin)
    stop = text.find(end, start + len(begin)) if start >= 0 else -1
    if start < 0 or stop < 0:
        return None
    stop += len(end)
    return text[start : stop + 1] if text[stop : stop + 1] == "\n" else text[start:stop]


def check_text(text: str) -> list[str]:
    """One message per missing or drifted block, each carrying the expected rendering."""
    problems = []
    for name, (begin, end, expected) in expected_blocks().items():
        actual = extract(text, begin, end)
        if actual is None:
            problems.append(f"{name}: markers {begin} ... {end} not found")
        elif actual != expected:
            problems.append(
                f"{name}: block differs from its data file. Run "
                f"`python -m carter.identity.blocks <file>` or paste this:\n{expected}"
            )
    return problems


def sync_text(text: str) -> str:
    """Replace every block between its markers with the expected rendering."""
    for name, (begin, end, expected) in expected_blocks().items():
        actual = extract(text, begin, end)
        if actual is None:
            raise ValueError(f"{name}: markers {begin} ... {end} not found")
        text = text.replace(actual, expected, 1)
    return text


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m carter.identity.blocks <file> [--check]", file=sys.stderr)
        return 2
    path, check = Path(args[0]), "--check" in args[1:]
    text = path.read_text(encoding="utf-8")
    if check:
        problems = check_text(text)
        print("\n".join(problems))
        return 1 if problems else 0
    path.write_text(sync_text(text), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
