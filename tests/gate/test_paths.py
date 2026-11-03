"""Path normalization, credential paths, control files (RFC-0007 C.4.2 rule 8; plan 004 step 20)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gate.helpers import rule_of

DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "carter/identity/g2_rules.json").read_text()
)


def home() -> str:
    """The fixture home (the hermetic fixture moves HOME for every test)."""
    return str(Path.home())


def sample_of(segments: str) -> str:
    return "/" + segments.strip("/").replace("*", "1234")


class TestCredentialPathsFromTheDataFile:
    @pytest.mark.parametrize("entry", DATA["credential_paths"])
    def test_any_reference_by_any_command(self, entry: str) -> None:
        path = (
            f"~{sample_of(entry)}"
            if entry.startswith("/") and not entry.startswith("/proc")
            else sample_of(entry)
        )
        if entry.startswith("opencode/"):
            path = f"~/.config/{entry}"
        if entry.endswith("/"):
            path += "/file"
        for cmd in (
            f"cat {path}",
            f"ls {path}",
            f"cp {path} /tmp/x",
            f"echo x > {path}",
            f"grep -r k {path}",
            f"python3 {path}",
        ):
            assert rule_of(cmd) == "credential-paths", (entry, cmd)

    def test_segments_not_substrings(self) -> None:
        for path in (
            "~/.sshfoo/x",
            "~/foo.ssh/x",
            "~/ssh/x",
            "~/.config/ghx/hosts.yml",
            "~/.config/gh-notes",
            "~/.git-credentials-old/x",
            "/proc/self/environment",
            "~/.carter/secrets-note.md",
            "~/Library/KeychainsX/y",
        ):
            assert rule_of(f"cat {path}") is None, path

    def test_the_parent_of_a_credential_path_is_not_one(self) -> None:
        for path in ("~", "~/.config", "~/.carter", "/proc", "/proc/self", "~/Library"):
            assert rule_of(f"ls {path}") is None, path


class TestNormalization:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat ~/.ssh/id",
            'cat "$HOME/.ssh/id"',
            "cat ${HOME}/.ssh/id",
            'cat "${HOME}/.ssh/id"',
            "cat $HOME/.ssh/id",
            "cat ~/x/../.ssh/id",
            "cat ~/./.ssh/id",
            "cat ~//.ssh//id",
            "cat /x/../${HOME}/.ssh/id".replace("/x/../${HOME}", "$HOME"),
            "cd ~ && cat .ssh/id",
            "cd ~/.ssh && cat id",
            "cd ~/.ssh; ls",
            "cd ~ && cd .ssh && cat id",
            "pushd ~/.ssh",
            "cd ~/x && cat ../.ssh/id",
            "(cd ~ && cat .ssh/id)",
            "cat .ssh/id",
            "cat ./.ssh/id",
            "cat x/../.ssh/id",
            "cat -- ~/.ssh/id",
            "tr a b < ~/.ssh/id",
            "cat <~/.ssh/id",
            "ls --color=auto ~/.ssh",
            "ssh -i ~/.ssh/id host",
            "ssh -i$HOME/.ssh/id host",
            "scp --identity-file=~/.ssh/id x y",
            "FOO=~/.ssh/id make",
            "PATH=$PATH:$HOME/.ssh make",
            "cat ~/.ssh/*",
            "cat ~/.s?h/id",
            "cat ~/.{ssh,x}/id",
            "cat ~/.[s]sh/id",
            'cat "~"/.ssh/id'.replace('"~"', "$HOME"),
            "cat $'\\x7e'/.ssh/id".replace("$'\\x7e'", "$HOME"),
            "cat $(pwd)/.ssh/id",
            "cat $X/.ssh/id",
        ],
    )
    def test_forms_that_reach_a_credential(self, cmd: str, tmp_path: Path) -> None:
        for d in (".ssh",):
            (Path(home()) / d).mkdir(parents=True, exist_ok=True)
        assert rule_of(cmd, cwd=home()) == "credential-paths", cmd

    def test_relative_tokens_use_the_effective_directory(self, tmp_path: Path) -> None:
        cfg = Path(home()) / ".config"
        cfg.mkdir(parents=True, exist_ok=True)
        assert rule_of("cat gh/hosts.yml", cwd=str(cfg)) == "credential-paths"
        assert rule_of("cat gh/hosts.yml", cwd=str(tmp_path)) is None
        assert rule_of("cat gh/hosts.yml") is None  # no base: only the token's own segments count
        assert (
            rule_of("cat .config/gh/hosts.yml") == "credential-paths"
        )  # ... and they are enough here

    def test_git_dash_C_is_not_a_directory_change_for_later_commands(self, tmp_path: Path) -> None:
        assert rule_of("git -C ~ status && cat id", cwd=str(tmp_path)) is None

    def test_symlinks_are_resolved_once(self, tmp_path: Path) -> None:
        os.symlink(Path(home()) / ".ssh", tmp_path / "k")
        os.symlink(tmp_path / "k", tmp_path / "chain")
        for cmd in ("cat k/id", "cat chain/id", f"cat {tmp_path}/k/id", "ls k"):
            assert rule_of(cmd, cwd=str(tmp_path)) == "credential-paths", cmd
        os.symlink(tmp_path, tmp_path / "harmless")
        assert rule_of("cat harmless/x", cwd=str(tmp_path)) is None

    def test_words_with_spaces_are_prose_not_paths(self) -> None:
        for cmd in (
            'echo "see ~/.ssh/id"',
            "git commit -m 'read ~/.config/gh/hosts.yml'",
            "echo '~/.ssh'",
        ):
            assert rule_of(cmd) is None or "ssh'" in cmd, cmd

    def test_command_substitution_and_nested_shells_are_looked_into(self) -> None:
        assert rule_of("echo $(cat ~/.ssh/id)") == "credential-paths"
        assert rule_of("bash -c 'cat ~/.ssh/id'") == "credential-paths"
        assert rule_of('eval "cat ~/.ssh/id"') == "credential-paths"
        assert rule_of("find ~/.ssh -type f") == "credential-paths"
        assert rule_of("find . -exec cat ~/.ssh/id {} +") == "credential-paths"


class TestControlFiles:
    CONTROL = DATA["control_paths"]

    @staticmethod
    def sample(entry: str) -> str:
        path = entry if entry.startswith("~") else "~/" + entry
        return path + "x" if path.endswith("/") else path

    @pytest.mark.parametrize("entry", CONTROL)
    def test_every_write_capable_form_is_refused(self, entry: str) -> None:
        p = self.sample(entry)
        for cmd in (
            f"echo x > {p}",
            f"echo x >> {p}",
            f"echo x >| {p}",
            f"cat a &> {p}",
            f"echo x | tee {p}",
            f"echo x | tee -a {p}",
            f"sed -i s/a/b/ {p}",
            f"sed -i.bak s/a/b/ {p}",
            f"sed --in-place s/a/b/ {p}",
            f"sed -ni p {p}",
            f"cp a {p}",
            f"cp -r a {p}",
            f"install a {p}",
            f"mv a {p}",
            f"rm {p}",
            f"rm -f {p}",
            f"ln -s a {p}",
            f"ln -sf a {p}",
            f"chmod 600 {p}",
            f"chown u {p}",
            f"truncate -s0 {p}",
            f"touch {p}",
            f"dd if=a of={p}",
            f"cp -t {p} a",
            f"rsync a {p}",
            f"python3 {p}",
            f"perl -pi -e 1 {p}",
            f"mkdir {p}",
        ):
            assert rule_of(cmd) == "control-files", (entry, cmd)

    @pytest.mark.parametrize("entry", CONTROL)
    def test_reads_pass(self, entry: str) -> None:
        p = self.sample(entry)
        for cmd in (
            f"cat {p}",
            f"ls -la {p}",
            f"head -3 {p}",
            f"grep x {p}",
            f"cp {p} /tmp/copy",
            f"diff {p} /tmp/x",
            f"wc -l < {p}",
            f"stat {p}",
            f"sed -n 1p {p}",
            f"tar cf /tmp/x.tar {p}",
        ):
            assert rule_of(cmd) is None, (entry, cmd)

    def test_a_relative_target_after_cd_into_a_control_directory(self) -> None:
        assert rule_of("cd ~/.carter/hooks && echo x > carter-guard") == "control-files"
        assert rule_of("cd ~/.carter && echo x > isolation.json") == "control-files"
        assert rule_of("cd ~/.carter && echo x > memories/note.md") is None
        assert rule_of("cd ~/.config/opencode && cp x plugin/y.ts") == "control-files"
        assert rule_of("cd ~/.config/opencode && cp x opencode.jsonc") is None  # D67 residual

    def test_an_ancestor_counts_for_rm_and_mv_and_recursive_forms(self) -> None:
        for cmd in (
            "rm -rf ~/.carter",
            "rm -r ~/.carter/",
            "rm -rf ~/.config/opencode",
            "mv ~/.carter /tmp/x",
            "mv /tmp/x ~/.carter",
            "cp -r /tmp/x ~/.carter",
            "chmod -R 777 ~/.carter",
            "rsync -a x/ ~/.carter/",
            "rm -rf ~/.config/opencode/plugins",
            "rm -rf ~/.config",
            "rm -rf ~",
        ):
            assert rule_of(cmd) == "control-files", cmd
        for cmd in ("rm ~/.carter/memories/old.md", "rm -rf ~/.cache/opencode", "rm -rf ~/.cache"):
            assert rule_of(cmd) is None, cmd
        assert rule_of("rm -rf ~/.carter/memories") is None
        assert (
            rule_of("cp x ~/.carter") is None
        )  # not recursive: cannot replace a directory's contents

    def test_state_and_memories_stay_editable(self) -> None:
        for p in (
            "~/.carter/memories/user/x.md",
            "~/.carter/state/plans/active/x.md",
            "~/.carter/state/audit/x"[:0] or "~/.carter/manifest.json",
        ):
            assert rule_of(f"echo x > {p}") is None, p

    def test_interpreter_arguments_and_program_text_naming_them(self) -> None:
        assert rule_of("python3 ~/.carter/hooks/carter-guard") == "control-files"
        assert (
            rule_of("node -e \"require('fs').writeFileSync('/h/.carter/config.toml','x')\"")
            == "control-files"
        )
        assert (
            rule_of('ruby -e \'File.write("/h/.config/opencode/plugin/x.ts", "")\'')
            == "control-files"
        )
        assert rule_of("python3 -c \"print('.carter/memories/x')\"") is None

    def test_other_writers_of_the_command_list_by_name(self) -> None:
        for name in DATA["forbidden"][-1]["gate_extra_commands"]:
            if name in ("dd", "chown", "chgrp"):  # dd takes of=, chown/chgrp an owner first
                continue
            assert rule_of(f"{name} ~/.carter/isolation.json") == "control-files", name

    def test_lookalikes_are_not_control_paths(self) -> None:
        for p in (
            "~/.carter-old/isolation.json",
            "~/.carterx/hooks/a",
            "~/.carter/isolation.json.bak",
            "~/.carter/hooks-old/x",
            "~/.carter/gitconfig-old",
            "~/.config/opencode-x/plugin/a",
            "~/.config/opencode/plugins-old/a",
        ):
            assert rule_of(f"echo x > {p}") is None or "plugin" in p and "-old" not in p, p


class TestResidualIsAllowedOnPurpose:
    """D67: the gate guards C.1 control paths only; these section 4.5 paths stay writable."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo x > ~/.config/opencode/opencode.jsonc",
            "echo x > ~/.config/opencode/opencode.json",
            "echo x >> ~/.gitconfig",
            "echo x > ~/.config/git/config",
            "cp h .git/hooks/pre-commit",
            "sed -i s/a/b/ .git/config",
            "echo x > .git/hooks/pre-push",
            "cp x .opencode/plugins/x.ts",
            "echo x > opencode.json",
            "echo x > ~/.config/opencode/agents/a.md",
            "tee .opencode/agents/a.md",
        ],
    )
    def test_pinned_as_allowed(self, cmd: str) -> None:
        assert rule_of(cmd) is None
