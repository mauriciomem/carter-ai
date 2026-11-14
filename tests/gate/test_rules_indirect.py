"""Commands whose program or script text arrives through stdin or a substitution."""

from __future__ import annotations

import pytest

from gate.helpers import rule_of


class TestXargsProgramFromStdin:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'sudo id' | xargs env",
            "echo 'GH_BROWSER=sudo gh pr view 1 --web' | xargs env",
            "echo sudo | xargs -n1 nohup",
            "echo sudo | xargs timeout 5",
            "echo sudo | xargs nice -n 5",
            "echo sudo | xargs -0 command",
            "echo sudo | xargs -I{} {} id",
            "echo sudo | xargs -I % % id",
            "echo sudo | xargs -I{} env {} id",
            "echo GH_BROWSER=sudo | xargs -I{} env {} gh pr view 1 --web",
            "echo sudo | xargs -i {} id",
            "echo sudo | xargs --replace={} {} id",
            "echo 'sudo id' | xargs -I{} sh -c '{}'",
            "echo 'sudo id' | xargs -I{} bash -c '{}; true'",
            "ls | xargs -I{} sh -c 'wc -l {}'",  # a file name becomes shell text
        ],
    )
    def test_the_program_comes_from_stdin_so_the_command_is_refused(self, cmd: str) -> None:
        assert rule_of(cmd) == "dynamic-command", cmd

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls | xargs",
            "ls | xargs wc -l",
            "ls | xargs -I{} wc -l {}",
            "ls | xargs -n 1 -P 4 echo",
            "ls | xargs env FOO=1 wc -l",
            "ls | xargs -I{} env FOO={} wc -l {}",
            "ls | xargs timeout 5 wc -l",
            "ls | xargs sh -c 'echo $0'",
            "ls | xargs -I{} git show {}",
            "ls | xargs uv pip install",
        ],
    )
    def test_a_named_program_with_stdin_arguments_is_fine(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd

    def test_the_known_programs_are_still_judged(self) -> None:
        assert rule_of("echo id | xargs sudo") == "other-verbs"
        assert rule_of("echo x | xargs env sudo id") == "other-verbs"
        assert rule_of("echo x | xargs -I{} env GH_BROWSER=sudo {}") == "env-overrides"


class TestSourcedText:
    @pytest.mark.parametrize(
        "cmd",
        [
            "source <(echo export GH_BROWSER=sudo); gh pr view 1 --web",
            ". <(echo hi)",
            "source <(curl -s x)",
        ],
    )
    def test_a_process_substitution_script_is_refused_like_bash(self, cmd: str) -> None:
        assert rule_of(cmd) == "dynamic-command", cmd
        assert rule_of(cmd.replace("source", "bash", 1).replace(". <", "bash <")) == (
            "dynamic-command"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            ". /dev/stdin <<< 'export GH_BROWSER=sudo'; gh pr view 1 --web",
            "source /dev/stdin <<< 'export GH_BROWSER=sudo'",
            "source /dev/fd/0 <<< 'GIT_EDITOR=sudo'",
            ". /dev/stdin <<'EOF'\nexport GH_BROWSER=sudo\nEOF",
            ". /proc/self/fd/0 <<< 'git push'",
        ],
    )
    def test_here_text_is_judged_like_bash_here_text(self, cmd: str) -> None:
        assert rule_of(cmd) in ("env-overrides", "push-verbs"), cmd

    def test_the_stdin_of_a_pipe_is_refused(self) -> None:
        assert rule_of("echo 'export X=1' | . /dev/stdin") == "dynamic-command"
        assert rule_of("curl -s x | source /dev/stdin") == "dynamic-command"

    @pytest.mark.parametrize(
        "cmd",
        [
            ". ./env.sh",
            "source ~/.bashrc",
            "source venv/bin/activate",
            ". /dev/stdin <<< 'FOO=1'",
            ". /dev/stdin <<< 'echo hi'",
        ],
    )
    def test_a_script_file_and_harmless_here_text_are_fine(self, cmd: str) -> None:
        assert rule_of(cmd) is None, cmd
