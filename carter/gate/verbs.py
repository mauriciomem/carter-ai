"""git rules (RFC-0007 App C.4.1 rows 1-3, 5-7; C.4.2 rules 6-7).

Global options are consumed before the subcommand, flags are scoped per subcommand (``-n`` means
``--no-verify`` only for ``commit`` and ``am``; ``-s`` means sign-off only where git says so), and
every list comes from the data file. A dynamic word before the subcommand is refused
(``dynamic-command``); a dynamic word after it is not (only command positions count, rule 5).
"""

from __future__ import annotations

import os
import re

from carter.gate import aliases
from carter.gate.data import glob, rules
from carter.gate.words import Word

TYPE_CHECKING = False
if TYPE_CHECKING:
    from carter.gate.words import Judge

MAX_ALIAS_DEPTH = 5
SHA = re.compile(r"[0-9a-f]{7,64}\Z")
DENIED_LONG_GATE = ("--no-verify", "--no-gpg-sign", "--signoff", "--reset-author", "--author")
GLOBAL_WITH_VALUE = frozenset(
    {"--git-dir", "--work-tree", "--namespace", "--super-prefix", "--attr-source"}
)
VALUED_SHORT = {
    "commit": "mFCct",
    "merge": "msX",
    "rebase": "sXxC",
    "cherry-pick": "mX",
    "revert": "mX",
    "pull": "sX",
    "am": "",
    "add": "",
}
VALUED_LONG = frozenset(
    {
        "--message",
        "--file",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--template",
        "--cleanup",
        "--date",
        "--trailer",
        "--pathspec-from-file",
        "--strategy",
        "--strategy-option",
        "--onto",
        "--exec",
        "--into-name",
    }
)
CONFIG_WRITE = frozenset(
    {
        "--add",
        "--unset",
        "--unset-all",
        "--replace-all",
        "--rename-section",
        "--remove-section",
        "-e",
        "--edit",
    }
)
CONFIG_READ = frozenset(
    {
        "--get",
        "--get-all",
        "--get-regexp",
        "--get-urlmatch",
        "-l",
        "--list",
        "--get-color",
        "--get-colorbool",
    }
)
CONFIG_VALUED = frozenset({"-f", "--file", "--blob", "--type", "--default", "--comment"})


def key_is_forbidden(key: str) -> bool:
    k = key.strip().lower()
    return any(glob(p, k) for p in rules()["config_keys"])


def check(eng: Judge, words: list[Word], depth: int = 0) -> None:
    """Judge ``git [global options] <subcommand> ...`` (``words[0]`` is the git binary)."""
    i, where = 1, eng.cwd
    extra_alias: dict[str, str] = {}
    while i < len(words):
        w = words[i]
        a = w.text
        if not w.static:
            eng.deny("dynamic-command", "a git option or subcommand is computed by the shell")
        if not a.startswith("-") or a == "-":
            break
        nxt = words[i + 1] if i + 1 < len(words) else None
        if a in ("-C", "-c", "--config-env") or a in GLOBAL_WITH_VALUE:
            if nxt is None:
                return
            if not nxt.static and a in ("-c", "--config-env"):
                eng.deny("dynamic-command", "a git -c value is computed by the shell")
            if a == "-C":
                known = nxt.static and (where or nxt.text.startswith("/"))
                where = os.path.normpath(os.path.join(where or "", nxt.text)) if known else None
            elif a == "-c":
                set_key(eng, nxt.text, extra_alias)
            elif a == "--config-env":
                config_env(eng, nxt.text)
            i += 2
        elif a.startswith("-c") and not a.startswith("--") and len(a) > 2:
            set_key(eng, a[2:], extra_alias)
            i += 1
        elif a.startswith("-C") and len(a) > 2:
            where = (
                os.path.normpath(os.path.join(where or "", a[2:]))
                if (where or a[2:].startswith("/"))
                else None
            )
            i += 1
        elif a.startswith("--config-env="):
            config_env(eng, a.split("=", 1)[1])
            i += 1
        elif a.startswith("--exec-path="):
            eng.deny("env-overrides", "--exec-path= sets GIT_EXEC_PATH")
        else:
            i += 1  # --no-pager, -p, --bare, --git-dir=..., --version, ...
    if i >= len(words):
        return
    run_sub(eng, words[i].text, words[i + 1 :], where, extra_alias, depth)


def set_key(eng: Judge, kv: str, extra_alias: dict[str, str]) -> None:
    key, _, value = kv.partition("=")
    if key_is_forbidden(key):
        eng.deny("config-flags", "-c of a protected key")
    if key.lower().startswith("alias."):
        extra_alias[key[6:]] = value


def config_env(eng: Judge, spec: str) -> None:
    if key_is_forbidden(spec.partition("=")[0]):
        eng.deny("config-flags", "--config-env of a protected key")


def run_sub(
    eng: Judge,
    sub: str,
    args: list[Word],
    where: str | None,
    extra_alias: dict[str, str],
    depth: int,
) -> None:
    r = rules()
    if sub in r["push_verbs"]:
        eng.deny("push-verbs")
    first = next((a.text for a in args if not a.text.startswith("-")), "")
    if (sub, first) in r["push_pairs"]:
        eng.deny("push-verbs")  # git subtree push, git lfs push, ...: other ways to send commits
    if sub in r["plumbing"]:
        if sub != "update-ref" or any(SHA.match(a.text) for a in args):
            eng.deny("plumbing")
        return
    if not aliases.is_builtin(sub):
        resolve_alias(eng, sub, args, where, extra_alias, depth)
        return
    if sub == "config":
        config(eng, args)
    elif sub in r["commit_verbs"] or sub == "add":
        flags(eng, sub, args)
    if sub == "rebase":
        nested(eng, exec_values(args, "-x", "--exec"), depth)
    elif sub == "bisect" and args and args[0].text == "run":
        eng.run_words(args[1:], depth + 1)
    elif sub == "submodule" and args and args[0].text == "foreach":
        nested(eng, [a.text for a in args[1:] if not a.text.startswith("-")][:1], depth)


def exec_values(args: list[Word], short: str, long: str) -> list[str]:
    out = []
    for i, a in enumerate(args):
        if a.text in (short, long) and i + 1 < len(args):
            out.append(args[i + 1].text)
        elif a.text.startswith(long + "="):
            out.append(a.text.split("=", 1)[1])
    return out


def nested(eng: Judge, texts: list[str], depth: int) -> None:
    for text in texts:
        eng.run_text(text, depth + 1)


def resolve_alias(
    eng: Judge,
    sub: str,
    args: list[Word],
    where: str | None,
    extra_alias: dict[str, str],
    depth: int,
) -> None:
    seen: list[str] = []
    name, rest = sub, list(args)
    table = None
    while True:
        if aliases.is_builtin(name):
            return run_sub(eng, name, rest, where, {}, depth)
        if where is None:
            eng.deny("git-alias", "no directory is known to look the alias up in")
            return
        table = aliases.lookup(where, extra_alias) if table is None else table
        value = table.get(name.lower())
        if value is None:
            return  # not an alias: an external git-<name> helper, harmless to judge here
        if value.lstrip().startswith("!") or len(seen) >= MAX_ALIAS_DEPTH or name in seen:
            eng.deny("git-alias")
        seen.append(name)
        parts = value.split()
        if not parts:
            return
        if parts[0].startswith("-"):
            eng.deny("git-alias", "an alias that starts with git options cannot be resolved safely")
            return
        name, rest = parts[0], [Word(text=p) for p in parts[1:]] + rest


def flags(eng: Judge, sub: str, args: list[Word]) -> None:
    r = rules()
    valued = VALUED_SHORT.get(sub, "")
    skip = False
    for idx, w in enumerate(args):
        a = w.text
        if skip:
            skip = False
            continue
        if a == "--":
            if sub == "add" and any(x.text in (".", "./") for x in args[idx + 1 :]):
                eng.deny("staging")
            return
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            has_value = "=" in a
            if name in VALUED_LONG and not has_value:
                skip = True
            if sub in r["commit_verbs"]:
                long_flag(eng, name, has_value)
            if sub in ("add", "commit") and len(name) >= 4 and "--all".startswith(name):
                eng.deny("staging")
        elif a.startswith("-") and len(a) > 1:
            short_cluster(eng, sub, a[1:], valued, r)
            skip = cluster_wants_value(a[1:], valued)
        elif sub == "add" and a in (".", "./"):
            eng.deny("staging")


def cluster_wants_value(cluster: str, valued: str) -> bool:
    for pos, ch in enumerate(cluster):
        if ch in valued:
            return pos == len(cluster) - 1
    return False


def long_flag(eng: Judge, name: str, has_value: bool) -> None:
    for denied in DENIED_LONG_GATE:
        if name == denied or (len(name) >= 4 and denied.startswith(name)):
            eng.deny("commit-flags", f"{denied} is not allowed")
    if "--gpg-sign".startswith(name) and len(name) >= 5 and has_value:
        eng.deny("commit-flags", "--gpg-sign=<key> is not allowed (bare --gpg-sign is)")


def short_cluster(eng: Judge, sub: str, cluster: str, valued: str, r: dict) -> None:
    for pos, ch in enumerate(cluster):
        if ch == "S":
            if cluster[pos + 1 :]:
                eng.deny("commit-flags", "-S<key> is not allowed (bare -S is)")
            return
        if ch in valued:
            return  # the rest of the cluster (or the next word) is this option's value
        if ch == "n" and sub in r["no_verify_short"]:
            eng.deny("commit-flags", "-n means --no-verify here")
        if ch == "s" and sub in r["signoff_short"]:
            eng.deny("commit-flags", "-s means --signoff here")
        if (sub, f"-{ch}") in r["staging"]:
            eng.deny("staging")


def config(eng: Judge, args: list[Word]) -> None:
    positional, read, skip = 0, False, False
    for w in args:
        a = w.text
        if skip:
            skip = False
        elif a in CONFIG_WRITE:
            eng.deny("git-config-writes")
        elif a in CONFIG_READ:
            read = True
        elif a in CONFIG_VALUED:
            skip = True
        elif not a.startswith("-"):
            positional += 1
    if not read and positional >= 2:
        eng.deny("git-config-writes")
