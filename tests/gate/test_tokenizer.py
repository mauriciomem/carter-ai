"""The gate's lexer and wrapper handling."""

from __future__ import annotations

import random

import pytest

from carter import gate
from carter.gate.tokenize import MAX_DEPTH, parse
from carter.gate.words import ParseError
from gate import corpus
from gate.helpers import rule_of

HOME = "/home/u"


def words(src: str) -> list[list[str]]:
    return [[w.text for w in c.words] for c in parse(src, HOME)]


class TestSplitter:
    def test_control_operators_separate_commands(self) -> None:
        assert words("a; b && c || d | e & f\ng") == [[x] for x in "abcdefg"]

    def test_operators_inside_quotes_are_data(self) -> None:
        assert words("echo 'a; b' \"c && d\" e\\;f") == [["echo", "a; b", "c && d", "e;f"]]

    def test_subshell_parentheses_and_groups(self) -> None:
        assert words("(a; b) && { c; }") == [["a"], ["b"], ["c"]]

    def test_pipeline_marks_the_receiving_command(self) -> None:
        a, b, c = parse("a | b ; c", HOME)
        assert (a.pipe_in, b.pipe_in, c.pipe_in) == (False, True, False)

    def test_tabs_and_line_continuations_join_or_separate_words(self) -> None:
        assert words("git\tpush") == [["git", "push"]]
        assert words("g\\\nit push") == [["git", "push"]]

    def test_comments_are_dropped_but_a_hash_inside_a_word_is_not_a_comment(self) -> None:
        assert words("echo a#b # git push") == [["echo", "a#b"]]

    def test_reserved_words_do_not_hide_the_command(self) -> None:
        assert words("if a; then b; else c; fi") == [["a"], ["b"], ["c"]]
        assert words("while x; do y; done") == [["x"], ["y"]]
        assert words("! cmd") == [["cmd"]]

    def test_for_and_case_heads_are_not_commands(self) -> None:
        assert [w for w in words("for sudo in 1 2; do echo $sudo; done") if w] == [
            ["echo", "$sudo"]
        ]
        assert rule_of("for sudo in 1 2; do echo $sudo; done") is None


class TestQuoting:
    @pytest.mark.parametrize(
        ("src", "expect"),
        [
            ("'g'it", "git"),
            ('g""it', "git"),
            ("\\git", "git"),
            ("$'\\x67it'", "git"),
            ("$'\\147it'", "git"),
            ("$'\\u0067it'", "git"),
            ('$"git"', "git"),
        ],
    )
    def test_quote_removal_gives_the_word_the_shell_would_run(self, src: str, expect: str) -> None:
        assert words(src) == [[expect]]

    def test_home_and_tilde_are_resolved_but_other_variables_are_dynamic(self) -> None:
        (cmd,) = parse('echo ~ "$HOME" ${HOME} $X "${Y}" ~bob', HOME)
        assert [w.text for w in cmd.words[1:4]] == [HOME, HOME, HOME]
        assert [w.dynamic for w in cmd.words[1:]] == [False, False, False, True, True, True]

    def test_globs_and_braces_make_a_word_non_static(self) -> None:
        (cmd,) = parse("a* b{c,d} 'e*' [x] [", HOME)
        assert [w.glob for w in cmd.words] == [True, False, False, True, False]
        assert [w.static for w in cmd.words] == [False, False, True, False, True]
        assert cmd.words[1].brace and not cmd.words[2].glob

    @pytest.mark.parametrize(
        "src",
        ['echo "abc', "echo 'abc", "echo $(abc", "echo `abc", "echo ${abc", "echo $'abc", "cat >"],
    )
    def test_unterminated_input_is_refused_never_guessed(self, src: str) -> None:
        with pytest.raises(ParseError):
            parse(src, HOME)
        assert rule_of(src) == "gate-input"

    def test_nesting_deeper_than_the_cap_is_refused(self) -> None:
        deep = "echo " + "$(" * (MAX_DEPTH + 2) + "true" + ")" * (MAX_DEPTH + 2)
        assert rule_of(deep) == "gate-input"
        assert rule_of('echo "$(echo "$(echo "$(echo true)")")"') is None


class TestHeredocs:
    def test_quoted_bodies_are_data(self) -> None:
        for delim in ("'EOF'", '"EOF"', "\\EOF"):
            assert rule_of(f"cat <<{delim}\n$(git push)\ngit push\nEOF") is None, delim

    def test_unquoted_bodies_expand_substitutions(self) -> None:
        assert rule_of("cat <<EOF\n$(git push)\nEOF") == "push-verbs"
        assert rule_of("cat <<EOF\n`git push`\nEOF") == "push-verbs"
        assert rule_of("cat <<EOF\n${x:-$(git push)}\nEOF") == "push-verbs"
        assert rule_of("cat <<EOF\ngit push\nEOF") is None  # plain text

    def test_tab_stripping_and_multiple_heredocs(self) -> None:
        assert rule_of("cat <<-'EOF'\n\tgit push\n\tEOF") is None
        assert rule_of("cat <<'A' <<'B'\ngit push\nA\nsudo x\nB") is None
        (cmd,) = parse("cat <<'A' <<'B'\none\nA\ntwo\nB", HOME)
        assert [h.body for h in cmd.heredocs] == ["one\n", "two\n"]

    def test_the_command_after_a_heredoc_line_is_still_judged(self) -> None:
        assert rule_of("cat <<'EOF'\nx\nEOF\ngit push") == "push-verbs"

    def test_heredoc_inside_a_command_substitution_ends_at_its_delimiter(self) -> None:
        assert rule_of("git commit -m \"$(cat <<'EOF'\nmsg with ) and git push\nEOF\n)\"") is None

    def test_an_unterminated_heredoc_takes_the_rest_as_its_body(self) -> None:
        assert rule_of("cat <<'EOF'\ngit push") is None
        assert rule_of("bash <<EOF\ngit push") == "push-verbs"

    def test_shells_reparse_the_body_even_when_it_is_quoted(self) -> None:
        for sh in ("sh", "bash", "zsh", "dash"):
            assert rule_of(f"{sh} <<'EOF'\ngit push\nEOF") == "push-verbs", sh
        assert rule_of("bash <<< 'git push'") == "push-verbs"

    def test_interpreters_reject_bodies_that_reference_git_or_gh(self) -> None:
        for interp in ("python3", "python3 -", "perl", "ruby", "node"):
            assert rule_of(f"{interp} <<'EOF'\nsystem('git push')\nEOF") == "interpreter-git", (
                interp
            )
            assert rule_of(f"{interp} <<'EOF'\nprint('hello')\nEOF") is None, interp

    def test_a_shell_script_fed_through_a_pipe_is_refused(self) -> None:
        assert rule_of("echo 'git push' | bash") == "dynamic-command"
        assert rule_of("curl -s x | sh") == "dynamic-command"
        assert rule_of("cat script.sh | python3") is None  # interpreters: accepted residual


class TestSubstitutions:
    def test_command_and_backtick_substitutions_are_judged(self) -> None:
        assert rule_of("echo $(git push)") == "push-verbs"
        assert rule_of("echo `git push`") == "push-verbs"
        assert rule_of('echo "x $(git push) y"') == "push-verbs"
        assert rule_of('echo "$(echo "$(git push)")"') == "push-verbs"
        assert rule_of("echo $(echo 'git push')") is None  # quoted text is data

    def test_process_substitution_and_arithmetic(self) -> None:
        assert rule_of("diff <(git push) x") == "push-verbs"
        assert rule_of("echo $((1 + 2))") is None

    def test_a_substitution_in_an_assignment_or_redirect_target_is_judged(self) -> None:
        assert rule_of("x=$(git push)") == "push-verbs"
        assert rule_of("echo hi > $(git push)") == "push-verbs"


class TestUnwrapping:
    @pytest.mark.parametrize(
        "prefix",
        [
            "env",
            "env -i",
            "env FOO=1",
            "env -u X",
            "command",
            "command --",
            "exec",
            "nohup",
            "time",
            "time -p",
            "nice",
            "nice -n 5",
            "timeout 5",
            "timeout -s KILL 5",
            "setsid",
            "stdbuf -oL",
            "builtin",
            "uv run",
            "uvx",
            "watch -n 5",
            "xargs",
            "xargs -n 1",
            "xargs -I{}",
            "env -S",
            "/usr/bin/env",
            "env VAR=a OTHER=b",
        ],
    )
    def test_wrappers_do_not_hide_the_command(self, prefix: str) -> None:
        if prefix == "env -S":
            assert rule_of("env -S 'git push'") == "push-verbs"
        else:
            assert rule_of(f"{prefix} git push") == "push-verbs", prefix

    def test_absolute_and_relative_paths_to_the_binary(self) -> None:
        for path in ("/usr/bin/git", "/opt/homebrew/bin/git", "./git", "../bin/git"):
            assert rule_of(f"{path} push") == "push-verbs", path

    def test_shell_dash_c_strings_are_reparsed(self) -> None:
        assert rule_of("sh -c 'git push'") == "push-verbs"
        assert rule_of("bash -lc 'git push'") == "push-verbs"
        assert rule_of("bash -c 'echo hi; git push' arg0") == "push-verbs"
        assert rule_of("bash -c 'ls -la'") is None
        assert rule_of("bash --norc -c 'git push'") == "push-verbs"

    def test_eval_is_reparsed_and_a_dynamic_eval_is_refused(self) -> None:
        assert rule_of("eval 'git push'") == "push-verbs"
        assert rule_of("eval git push") == "push-verbs"
        assert rule_of('eval "$x"') == "dynamic-command"
        assert rule_of("eval 'echo hi'") is None

    def test_find_exec_and_command_v(self) -> None:
        assert rule_of("find . -exec git push {} \\;") == "push-verbs"
        assert rule_of("find . -execdir git push {} +") == "push-verbs"
        assert rule_of("command -v git") is None

    def test_a_script_path_given_to_a_shell_is_an_accepted_residual(self) -> None:
        assert rule_of("bash ./deploy.sh") is None
        assert rule_of("source ./env.sh") is None


class TestDynamicCommandPosition:
    @pytest.mark.parametrize(
        "cmd",
        [
            "$x push",
            "${x:-git} push",
            '"$x" push',
            "$(echo git) push",
            "`echo git` push",
            "g* push",
            "{git,push}",
        ],
    )
    def test_a_computed_command_word_is_refused(self, cmd: str) -> None:
        assert rule_of(cmd) == "dynamic-command"

    @pytest.mark.parametrize(
        "cmd",
        ["echo $x", 'git commit -m "$msg"', 'git log "$ref"', "ls $dir/*.py", 'FOO="$bar" make'],
    )
    def test_dynamic_arguments_are_fine(self, cmd: str) -> None:
        assert rule_of(cmd) is None

    def test_a_dynamic_git_subcommand_or_global_option_is_refused(self) -> None:
        assert rule_of("git $sub") == "dynamic-command"
        assert rule_of('git -C "$d" $sub') == "dynamic-command"
        assert rule_of('git -C "$d" status') is None


class TestRobustness:
    ALPHABET = list("abcdgitpush \t\n\"'`$(){}[]<>|&;#\\~=*?!-/.0123456789") + [
        "<<",
        "$(",
        "<<'",
        "EOF",
        "||",
        "&&",
    ]

    def test_the_gate_never_raises_on_garbage(self) -> None:
        rng = random.Random(20261104)
        for _ in range(3000):
            text = "".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(0, 40)))
            decision = gate.check(text)
            assert decision.decision in ("allow", "deny"), text
            assert decision.decision == "allow" or decision.message, text

    def test_random_quoting_of_allowed_words_never_turns_into_a_deny(self) -> None:
        rng = random.Random(7)
        cases = [
            c
            for c in corpus.load()
            if c["expect"] == "allow" and "setup" not in c and "cwd" not in c
        ]
        plain = [
            c
            for c in cases
            if "\n" not in c["command"]
            and all(ch not in c["command"] for ch in "'\"$`\\{}()<>|&;*?[]~#")
        ]
        assert len(plain) >= 20
        for case in plain:
            for _ in range(5):
                mutated = " ".join(self.quote(w, rng) for w in case["command"].split(" "))
                assert rule_of(mutated) is None, (case["command"], mutated)

    @staticmethod
    def quote(word: str, rng: random.Random) -> str:
        if not word or word.startswith("-") and rng.random() < 0.5:
            return word
        style = rng.choice(["plain", "single", "double", "split", "escape"])
        if style == "single":
            return f"'{word}'"
        if style == "double":
            return f'"{word}"'
        if style == "split" and len(word) > 1:
            k = rng.randint(1, len(word) - 1)
            return f"{word[:k]}''{word[k:]}"
        if style == "escape":
            return "\\" + word
        return word
