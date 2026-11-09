"""The decision engine: walk parsed commands and apply the rules in a fixed order.

Order per simple command (the first hit wins): substitutions inside its words, environment
overrides, a dynamic command position, nested command strings (``sh -c``, ``eval``), the command's
own rules (git, gh, other verbs, human-only Carter verbs, interpreters), credential paths, control
files. Rule ids are the 11 ``forbidden`` ids plus the 4 gate-only ids of the data file; a rule whose
consent group was declined (``--skip-groups``) is skipped, not weakened.
"""

from __future__ import annotations

import os

from carter.gate import envrules, others, paths, tokenize, verbs
from carter.gate.data import rules
from carter.gate.unwrap import Eff, base, unwrap
from carter.gate.words import Cmd, ParseError, Word

MAX_DEPTH = 8
CD = frozenset({"cd", "pushd"})


class Denied(Exception):
    def __init__(self, rule: str, hint: str) -> None:
        super().__init__(rule)
        self.rule, self.hint = rule, hint


class Engine:
    def __init__(self, home: str, cwd: str | None, skip_groups: frozenset[str]) -> None:
        self.home, self.cwd, self.skip = home, cwd, skip_groups
        self.paths = paths.Paths(home, cwd)

    def deny(self, rule: str, hint: str | None = None, item_group: str | None = None) -> None:
        r = rules()
        group = item_group or r["group_of"].get(rule, "g2")
        if group in self.skip:
            return
        text = hint or r["hints"][rule]
        raise Denied(rule, text if text.endswith((".", ")")) else text + ".")

    # ---- entry points ---------------------------------------------------------------------
    def run_text(self, text: str, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise ParseError("nesting too deep")
        for cmd in tokenize.parse(text, self.home):
            self.run_cmd(cmd, depth)

    def run_words(self, words: list[Word], depth: int) -> None:
        if words:
            self.run_cmd(Cmd(words=list(words)), depth)

    def scan_code_paths(self, text: str) -> None:
        if self.paths.code_mentions_credential(text):
            self.deny("credential-paths")
        if self.paths.code_mentions_control(text):
            self.deny("control-files")

    # ---- one simple command ---------------------------------------------------------------
    def run_cmd(self, cmd: Cmd, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ParseError("nesting too deep")
        for sub in cmd.subcommands():
            self.run_cmd(sub, depth + 1)
        eff = unwrap(cmd)
        if envrules.check(eff):
            self.deny("env-overrides")
        if eff.dynamic:
            self.deny(
                "dynamic-command",
                "the command to run is computed by the shell (variable, glob, brace).",
            )
        for text in eff.nested_text:
            if text.dynamic:
                self.deny(
                    "dynamic-command",
                    "a shell command string is computed at run time; write it out literally.",
                )
            self.run_text(text.text, depth + 1)
        for argv in eff.nested_argv:
            self.run_words(argv, depth + 1)
        self.shell_input(eff, cmd, depth)
        if eff.argv:
            self.command(eff, cmd, depth)
        self.path_rules(eff, cmd)

    def shell_input(self, eff: Eff, cmd: Cmd, depth: int) -> None:
        if not eff.stdin_shell:
            return
        if eff.script_subst or cmd.pipe_in:
            self.deny(
                "dynamic-command",
                "a shell is fed its script by another command; write the commands out directly.",
            )
        for hd in cmd.heredocs:
            self.run_text(hd.body, depth + 1)

    def command(self, eff: Eff, cmd: Cmd, depth: int) -> None:
        argv, name = eff.argv, base(eff.argv[0])
        if name in CD:
            self.change_dir(argv[1:])
        elif name == "git" or name.startswith("git-"):
            verbs.check(
                self, argv if name == "git" else [argv[0], Word(text=name[4:]), *argv[1:]], depth
            )
        elif name == "gh":
            others.gh(self, argv)
        elif name == "carter":
            others.carter(self, argv)
        else:
            others.other_verb(self, name, argv)
            others.interpreter(self, name, argv, cmd)

    def change_dir(self, args: list[Word]) -> None:
        targets = [a for a in args if not a.text.startswith("-")]
        if not targets:
            new: str | None = self.home
        elif targets[0].static and targets[0].text != "-":
            text = targets[0].text
            new = (
                os.path.normpath(
                    text if text.startswith("/") else os.path.join(self.cwd or "", text)
                )
                if (text.startswith("/") or self.cwd)
                else None
            )
        else:
            new = None
        self.cwd = self.paths.cwd = new

    # ---- paths ------------------------------------------------------------------------------
    def path_rules(self, eff: Eff, cmd: Cmd) -> None:
        p = self.paths
        own = {id(w) for w in cmd.words}
        words = list(cmd.parts()) + [w for w in eff.argv if id(w) not in own] + eff.assigns
        for word in words:
            if p.is_credential(word):
                self.deny("credential-paths")
        for op, target in cmd.redirs:
            if op in paths.WRITE_REDIRS and p.is_control_write(target):
                self.deny("control-files")
        for word, recursive in paths.write_targets(eff):
            if p.is_control_write(word, recursive):
                self.deny("control-files")
        for word in paths.interpreter_args(eff):
            if p.is_control_write(word):
                self.deny("control-files")


def rules_hint(rule: str) -> str:
    return rules()["hints"][rule]
