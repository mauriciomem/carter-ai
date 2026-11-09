"""git rules of the gate."""

from __future__ import annotations

import pytest

from gate.helpers import rule_of

SIGNOFF_VERBS = ["commit", "cherry-pick", "revert", "am"]
COMMIT_VERBS = ["commit", "merge", "rebase", "cherry-pick", "revert", "am", "pull"]


class TestGlobalOptionsComeFirst:
    @pytest.mark.parametrize(
        "prefix",
        [
            "-C .",
            "-C /tmp",
            "-C sub/dir",
            "-C. ",
            "-c a.b=c",
            "-c color.ui=false",
            "--no-pager",
            "-p",
            "--paginate",
            "--bare",
            "--git-dir=/x/.git",
            "--git-dir /x/.git",
            "--work-tree=/x",
            "--work-tree /x",
            "--namespace=n",
            "--no-optional-locks",
            "--literal-pathspecs",
            "-C . -c a.b=c --no-pager",
        ],
    )
    def test_push_is_found_behind_any_global_option(self, prefix: str) -> None:
        assert rule_of(f"git {prefix} push") == "push-verbs", prefix

    def test_global_options_do_not_hide_the_flag_checks_either(self) -> None:
        assert rule_of("git -C . commit --no-verify -m x") == "commit-flags"
        assert rule_of("git --no-pager add -A") == "staging"
        assert rule_of("git -c core.quotepath=off config user.name x") == "git-config-writes"

    def test_version_and_help_without_a_subcommand_pass(self) -> None:
        for cmd in ("git --version", "git -h", "git --help", "git --html-path", "git"):
            assert rule_of(cmd) is None, cmd


class TestCommitFlags:
    @pytest.mark.parametrize("verb", COMMIT_VERBS)
    @pytest.mark.parametrize(
        "flag",
        [
            "--no-verify",
            "--no-gpg-sign",
            "--signoff",
            "--reset-author",
            "--author=a",
            "--gpg-sign=K",
        ],
    )
    def test_long_flags_are_refused_on_every_commit_creating_verb(
        self, verb: str, flag: str
    ) -> None:
        assert rule_of(f"git {verb} {flag}") == "commit-flags", (verb, flag)

    @pytest.mark.parametrize("verb", COMMIT_VERBS)
    def test_bare_gpg_sign_and_dash_S_are_allowed(self, verb: str) -> None:
        assert rule_of(f"git {verb} -S") is None
        assert rule_of(f"git {verb} --gpg-sign") is None

    @pytest.mark.parametrize("verb", COMMIT_VERBS)
    def test_dash_S_with_a_key_is_refused(self, verb: str) -> None:
        assert rule_of(f"git {verb} -SKEY") == "commit-flags"

    @pytest.mark.parametrize("verb", ["commit", "am"])
    def test_dash_n_is_no_verify_only_for_commit_and_am(self, verb: str) -> None:
        assert rule_of(f"git {verb} -n") == "commit-flags"
        assert rule_of(f"git {verb} -qn") == "commit-flags"

    @pytest.mark.parametrize(
        "cmd",
        [
            "git merge -n x",
            "git rebase -n main",
            "git pull -n",
            "git cherry-pick -n abc",
            "git revert -n abc",
            "git add -n a",
            "git push -n",
        ],
    )
    def test_dash_n_means_something_else_elsewhere(self, cmd: str) -> None:
        assert rule_of(cmd) in (None, "push-verbs")  # push is refused for being push, not for -n
        if "push" not in cmd:
            assert rule_of(cmd) is None

    @pytest.mark.parametrize("verb", SIGNOFF_VERBS)
    def test_dash_s_is_signoff_where_git_says_so(self, verb: str) -> None:
        assert rule_of(f"git {verb} -s") == "commit-flags"

    @pytest.mark.parametrize(
        "cmd", ["git merge -s ours x", "git rebase -s ours main", "git pull -s recursive"]
    )
    def test_dash_s_is_a_strategy_elsewhere(self, cmd: str) -> None:
        assert rule_of(cmd) is None

    @pytest.mark.parametrize(
        "abbrev",
        [
            "--no-ver",
            "--no-verif",
            "--sign",
            "--signo",
            "--auth",
            "--author",
            "--reset",
            "--no-gpg",
        ],
    )
    def test_unambiguous_long_option_abbreviations_are_refused(self, abbrev: str) -> None:
        assert rule_of(f"git commit {abbrev} -m x") == "commit-flags", abbrev

    def test_option_values_are_not_flags(self) -> None:
        assert rule_of("git commit -m --no-verify") is None
        assert rule_of("git commit -m '-n -s --signoff'") is None
        assert rule_of("git commit --message=--no-verify") is None
        assert rule_of("git commit -F -n") is None
        assert rule_of("git commit -m n -m s") is None

    def test_double_dash_ends_the_flags(self) -> None:
        assert rule_of("git commit -m x -- --no-verify") is None

    def test_flags_are_judged_per_subcommand(self) -> None:
        assert rule_of("git log --author=bob") is None
        assert rule_of("git log --signoff") is None
        assert rule_of("git diff --no-verify") is None


class TestStaging:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git add -A",
            "git add --all",
            "git add -vA",
            "git add .",
            "git add ./",
            "git add -- .",
            "git add a b .",
            "git commit -a",
            "git commit --all",
            "git commit -am x",
            "git commit -qa",
            "git commit --al",
        ],
    )
    def test_refused(self, cmd: str) -> None:
        assert rule_of(cmd) == "staging", cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "git add a.py",
            "git add -u",
            "git add -p",
            "git add .gitignore",
            "git add ..",
            "git add src/.",
            "git commit -m a",
            "git commit --amend",
            "git add -n .x",
        ],
    )
    def test_allowed(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd


class TestPushAndPlumbing:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git push",
            "git push -n",
            "git push --dry-run origin x",
            "git send-pack x",
            "git http-push x",
            "git-push",
            "git-send-pack x",
        ],
    )
    def test_every_form_of_push(self, cmd: str) -> None:
        assert rule_of(cmd) == "push-verbs"

    @pytest.mark.parametrize(
        "sub", ["commit-tree", "fast-import", "filter-branch", "filter-repo", "replace"]
    )
    def test_plumbing(self, sub: str) -> None:
        assert rule_of(f"git {sub} x") == "plumbing"

    def test_update_ref_only_with_a_raw_sha(self) -> None:
        assert rule_of("git update-ref refs/heads/x abcdef1234567") == "plumbing"
        assert rule_of("git update-ref refs/heads/x HEAD") is None
        assert rule_of("git update-ref -d refs/heads/x") is None

    def test_commands_that_run_other_commands(self) -> None:
        assert rule_of("git rebase --exec 'git push' main") == "push-verbs"
        assert rule_of("git rebase -x 'ls' main") is None
        assert rule_of("git bisect run ./test.sh") is None
        assert rule_of("git submodule foreach 'ls'") is None


class TestConfig:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git config a.b c",
            "git config --global a.b c",
            "git config --local a.b c",
            "git config --worktree a.b c",
            "git config --system a.b c",
            "git config -f x a.b c",
            "git config --file x a.b c",
            "git config --add a.b c",
            "git config --replace-all a.b c",
            "git config --unset a.b",
            "git config --unset-all a.b",
            "git config -e",
            "git config --edit",
            "git config --rename-section a b",
            "git config --remove-section a",
            "git config --global --edit",
        ],
    )
    def test_writes_at_every_scope(self, cmd: str) -> None:
        assert rule_of(cmd) == "git-config-writes", cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "git config a.b",
            "git config --get a.b",
            "git config --global --get a.b",
            "git config --get-all a.b",
            "git config --get-regexp x",
            "git config -l",
            "git config --list",
            "git config --show-origin --get a.b",
            "git config --file x --get a.b",
            "git config --get a.b default",
            "git config --type bool a.b",
        ],
    )
    def test_reads_pass(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd


class TestDashC:
    @pytest.mark.parametrize(
        "key",
        [
            "hook.x.command",
            "core.hooksPath",
            "CORE.HOOKSPATH",
            "core.sshCommand",
            "core.askPass",
            "core.fsmonitor",
            "commit.gpgsign",
            "user.name",
            "gpg.program",
            "gpg.ssh.program",
            "alias.x",
            "include.path",
            "includeIf.x.path",
            "credential.helper",
            "url.x.insteadOf",
            "remote.origin.pushurl",
            "http.proxy",
            "protocol.ext.allow",
            "carter.tier",
            "core.pager",
            "core.editor",
            "sequence.editor",
            "diff.external",
            "filter.x.clean",
            "merge.x.driver",
            "diff.x.textconv",
        ],
    )
    def test_protected_keys_in_every_spelling(self, key: str) -> None:
        for form in (
            f"git -c {key}=v status",
            f"git -c{key}=v status",
            f"git --config-env={key}=VAR status",
            f"git --config-env {key}=VAR status",
        ):
            assert rule_of(form) == "config-flags", form

    @pytest.mark.parametrize(
        "key",
        [
            "color.ui",
            "core.quotepath",
            "advice.detachedHead",
            "init.defaultBranch",
            "diff.algorithm",
            "log.date",
            "core.abbrev",
        ],
    )
    def test_harmless_keys_pass(self, key: str) -> None:
        assert rule_of(f"git -c {key}=v status") is None

    def test_a_dynamic_value_cannot_be_checked_and_is_refused(self) -> None:
        assert rule_of('git -c "$KV" status') == "dynamic-command"
        assert rule_of("git -c $K=v status") == "dynamic-command"

    def test_exec_path_is_the_environment_variable_in_disguise(self) -> None:
        assert rule_of("git --exec-path=/x status") == "env-overrides"
        assert rule_of("git --exec-path") is None
