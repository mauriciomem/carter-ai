"""gh, the other gated verbs, human-only Carter verbs and interpreters.

RFC-0007 C.4.1 rows 3, 8, 9 and C.4.2 rules 2 and 5. ``gh`` is deny-by-default with the read
allowlist from the data file; ``gh api`` and a leading ``-R/--repo`` never pass. Interpreters
(``python``, ``perl``, ``ruby``, ``node``...) are judged on their *program text* (``-c``/``-e``
arguments and heredoc bodies), not on a script path, which stays an accepted residual.
"""

from __future__ import annotations

import re

from carter.gate.data import rules
from carter.gate.unwrap import CODE_FLAGS, base, interpreter_kind
from carter.gate.words import Cmd, Word

TYPE_CHECKING = False
if TYPE_CHECKING:
    from carter.gate.words import Judge

GH_HINT = (
    "gh is read-only for agents: use the allowlisted forms (pr view|list|diff|checks, "
    "issue view|list, "
    "run view|list, repo view, search); `gh api` is never allowed. Ask the human for anything else."
)
GIT_WORD = re.compile(r"(?<![\w.-])(git|gh)(?![\w-])")
SUDO_WORD = re.compile(r"(?<![\w.-])(sudo|docker|podman)(?![\w-])")


def gh(eng: Judge, argv: list[Word]) -> None:
    args = argv[1:]
    if not args:
        eng.deny("other-verbs", GH_HINT)
    first = args[0].text
    if (
        first in ("-R", "--repo")
        or first.startswith(("--repo=", "-R"))
        and len(first) > 2
        or first == "-R"
    ):
        eng.deny(
            "other-verbs",
            "put `-R` after the subcommand (`gh pr view 12 -R o/r`); a leading -R is refused.",
        )
    if not any(
        len(args) >= len(e) and all(args[i].text == e[i] for i in range(len(e)))
        for e in rules()["gh_allow"]
    ):
        eng.deny("other-verbs", GH_HINT)


def other_verb(eng: Judge, name: str, argv: list[Word]) -> None:
    r = rules()
    group = r["item_groups"].get(name)
    if name in r["other_single"]:
        eng.deny("other-verbs", item_group=group)
    if name == "opencode" and any(a.text in r["opencode_verbs"] for a in argv[1:2]):
        eng.deny("other-verbs", "starting OpenCode from an agent shell is refused (run or serve).")
    if name == "security" and len(argv) > 1 and f"security {argv[1].text}" in r["security_items"]:
        eng.deny("credential-paths", "reading keychain passwords is refused.")


def carter(eng: Judge, argv: list[Word]) -> None:
    words = [w.text for w in argv[1:] if not w.text.startswith("-")]
    if not words:
        return
    for verb, subs in rules()["human_only"]:
        if words[0] == verb and (subs is None or (len(words) > 1 and words[1] in subs)):
            eng.deny("human-only-carter")


def code_args(kind: str, argv: list[Word]) -> list[Word]:
    """Words of ``argv`` that are program text for interpreter ``kind``."""
    letters = CODE_FLAGS.get(kind)
    found: list[Word] = []
    skip = False
    args = argv[1:]
    for i, w in enumerate(args):
        a = w.text
        if skip:
            skip = False
            found.append(w)
        elif kind in ("awk", "gawk", "mawk", "nawk") and not a.startswith("-"):
            found.append(w)
            break
        elif (
            letters
            and a.startswith("--")
            and a.split("=", 1)[0] in ("--eval", "--print", "--command")
        ):
            if "=" in a:
                found.append(Word(text=a.split("=", 1)[1], quoted=True))
            else:
                skip = True
        elif letters and a.startswith("-") and not a.startswith("--") and len(a) > 1:
            for pos, ch in enumerate(a[1:], start=1):
                if ch in letters:
                    if a[pos + 1 :]:
                        found.append(Word(text=a[pos + 1 :], quoted=True))
                    else:
                        skip = i + 1 < len(args)
                    break
        elif not a.startswith("-"):
            break  # a script path or module: the program text is in the file
    return found


def interpreter(eng: Judge, name: str, argv: list[Word], cmd: Cmd) -> None:
    kind = interpreter_kind(name)
    if kind is None:
        return
    # python -m carter ...: the carter command in disguise
    for i, w in enumerate(argv[1:-1], start=1):
        if w.text == "-m" and argv[i + 1].text == "carter":
            return carter(eng, [argv[i + 1], *argv[i + 2 :]])
    texts = [w.text for w in code_args(kind, argv)] + [hd.body for hd in cmd.heredocs]
    for text in texts:
        scan_code(eng, text)


def scan_code(eng: Judge, text: str) -> None:
    if GIT_WORD.search(text):
        eng.deny("interpreter-git")
    if SUDO_WORD.search(text):
        eng.deny(
            "other-verbs",
            "an interpreter program may not start sudo, docker or podman.",
            item_group="sudo-docker",
        )
    eng.scan_code_paths(text)


def is_interpreter_name(argv: list[Word]) -> bool:
    return bool(argv) and argv[0].static and interpreter_kind(base(argv[0])) is not None
