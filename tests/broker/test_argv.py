# ruff: noqa: E501
"""Validators and the fixed push argv )."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from carter.broker import argv
from carter.broker.env import Tools
from carter.identity.errors import E_B_ARGS, E_B_HTTPS, IdentityError

TABLE = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "b_hostile_argv.json").read_text()
)
SHA = "a" * 40
TOOLS = Tools(git="/usr/bin/git", gh="/usr/bin/gh", ssh_bin_dir="/usr/bin")


def materialise(text: str) -> str:
    return (
        text.replace("<SHA>", SHA).replace("<OTHER>", "b" * 40)
        .replace("<BARE>", "/tmp/bare.git").replace("<MARK>", "/tmp/MARK")
    )  # fmt: skip


def cases(kind: str) -> list[Any]:
    return [
        pytest.param(c, id=f"{c['id']}-{c['variant']}")
        for c in TABLE["cases"]
        if c["kind"] == kind and c["variant"] == "dashdash"
    ]


@pytest.mark.parametrize("case", cases("remote"))
def test_every_hostile_remote_is_refused_and_the_good_ones_accepted(case: dict[str, Any]) -> None:
    url = materialise(case["operands"][0])
    if case["expect_validator"] == "accept":
        assert argv.parse_url(url).url == url
    else:
        with pytest.raises(IdentityError) as exc:
            argv.parse_url(url)
        assert exc.value.code in (E_B_ARGS, E_B_HTTPS)


_REFSPEC = re.compile(rf"(?P<sha>{argv._SHA}):refs/heads/(?P<branch>[^\n]+)")


def parse_refspec(refspec: str) -> tuple[str, str]:
    """``(sha, branch)`` of a refspec of exactly the shape the broker builds; else refused."""
    match = _REFSPEC.fullmatch(refspec)
    if not match or not argv.valid_branch(match["branch"]):
        raise argv._args("the refspec is not <sha>:refs/heads/<branch>")
    return match["sha"], match["branch"]


@pytest.mark.parametrize("case", cases("refspec"))
def test_every_hostile_refspec_is_refused_and_the_good_ones_accepted(case: dict[str, Any]) -> None:
    spec = materialise(case["operands"][1])
    if case["expect_validator"] == "accept":
        sha, branch = parse_refspec(spec)
        assert argv.build_refspec(sha, branch) == spec
    else:
        with pytest.raises(IdentityError) as exc:
            parse_refspec(spec)
        assert exc.value.code == E_B_ARGS


def test_the_table_has_rows_to_exercise() -> None:
    assert len(cases("remote")) >= 20 and len(cases("refspec")) >= 25
    assert sum(c.values[0]["expect_validator"] == "accept" for c in cases("remote")) == 2


class TestUrl:
    @pytest.mark.parametrize(
        ("url", "slug"),
        [
            ("git@github.com:o/r.git", "o/r"),
            ("git@github.com:o/r", "o/r"),
            ("ssh://git@github.com/o/r.git", "o/r"),
            ("ssh://git@github.com/Org-1/my.repo_x", "Org-1/my.repo_x"),
            ("git@github.com:o/.github.git", "o/.github"),
            ("git@github.com:o/r.git.git", "o/r.git"),
        ],
    )
    def test_accepted(self, url: str, slug: str) -> None:
        assert argv.parse_url(url).slug == slug

    @pytest.mark.parametrize(
        "url",
        [
            "git@github.com:../..",
            "git@github.com:./r",
            "git@github.com:o/.",
            "git@github.com:o/..",
            "git@github.com:-o/r",
            "git@github.com:o/-r",
            "git@github.com:o/r.git\n",
            "git@github.com:o/r.git ",
            " git@github.com:o/r.git",
            "git@GitHub.com:o/r.git",
            "git@github.com:o/r/x",
            "git@github.com:o",
            "ssh://git@github.com:22/o/r.git",
            "ssh://git@github.com//o/r.git",
            "ssh://github.com/o/r.git",
            "ssh://root@github.com/o/r",
            "git@github.com.evil.example:o/r.git",
            "git@gitlab.com:o/r.git",
            "origin",
            "",
            "git@github.com:o/r\x00",
            "git@github.com:o/r;x",
            "git@github.com:o/r'x",
        ],
    )
    def test_refused(self, url: str) -> None:
        with pytest.raises(IdentityError) as exc:
            argv.parse_url(url)
        assert exc.value.code == E_B_ARGS

    @pytest.mark.parametrize(
        "url", ["https://github.com/o/r.git", "http://github.com/o/r", "HTTPS://github.com/o/r"]
    )
    def test_http_is_its_own_code_so_the_message_points_to_a_plus(self, url: str) -> None:
        with pytest.raises(IdentityError) as exc:
            argv.parse_url(url)
        assert exc.value.code == E_B_HTTPS and "carter push" in str(exc.value)

    def test_a_dollar_anchored_pattern_would_have_accepted_the_newline(self) -> None:
        assert re.match(r"^git@github\.com:[\w.-]+/[\w.-]+(\.git)?$", "git@github.com:o/r.git\n")
        with pytest.raises(IdentityError):
            argv.parse_url("git@github.com:o/r.git\n")


class TestBranch:
    @pytest.mark.parametrize("name", ["main", "feat/x", "fix-1.2", "a/b/c", "v1.0", "x@y", "u"])
    def test_plain_names(self, name: str) -> None:
        assert argv.valid_branch(name)

    @pytest.mark.parametrize(
        "name",
        ["\u202eevil", "a\u200bb", "a\u2028b", "a\u00a0b", "", "-x", "--x", "/x", "x/", ".x", "a/.b", "a..b", "a b", "a~b", "a^b", "a:b", "a?b", "a*b",
         "a[b", "a\\b", "a@{b", "@", "x.lock", "a.lock/b", "a//b", "x.", "a\nb", "a\x00b", "b" * 201],
    )  # fmt: skip
    def test_refused(self, name: str) -> None:
        assert not argv.valid_branch(name)

    def test_the_rules_agree_with_git_check_ref_format(self) -> None:
        import subprocess

        for name in [
            "main",
            "feat/x",
            "a..b",
            "a b",
            "x.lock",
            "a@{b",
            ".x",
            "a//b",
            "x.",
        ]:  # "@" is valid for git, refused here (stricter)
            git = subprocess.run(
                ["git", "check-ref-format", f"refs/heads/{name}"], capture_output=True
            )
            assert (git.returncode == 0 and not name.startswith("-")) == argv.valid_branch(name), (
                name
            )


class TestRefspec:
    def test_built_from_a_full_sha_and_a_plain_branch(self) -> None:
        assert argv.build_refspec(SHA, "feat/x") == f"{SHA}:refs/heads/feat/x"
        assert argv.build_refspec("c" * 64, "m") == f"{'c' * 64}:refs/heads/m"

    @pytest.mark.parametrize(
        "sha", ["", "HEAD", "abc123", "A" * 40, "a" * 39, "a" * 41, SHA + "\n"]
    )
    def test_a_short_symbolic_or_odd_sha_is_refused(self, sha: str) -> None:
        with pytest.raises(IdentityError):
            argv.build_refspec(sha, "feat/x")

    def test_a_bad_branch_is_refused(self) -> None:
        with pytest.raises(IdentityError):
            argv.build_refspec(SHA, "--force")


class TestPushArgv:
    def build(self) -> list[str]:
        return argv.push_argv(TOOLS, argv.parse_url("git@github.com:o/r.git"), SHA, "feat/x")

    def test_the_command_line_is_fixed_with_dashdash_before_the_operands(self) -> None:
        cmd = self.build()
        assert cmd[0] == "/usr/bin/git"
        i = cmd.index("--")
        assert cmd[i - 2 : i] == ["push", "--recurse-submodules=no"]
        assert cmd[i + 1 :] == ["git@github.com:o/r.git", f"{SHA}:refs/heads/feat/x"]
        assert cmd.count("--") == 1

    def test_ssh_is_the_absolute_path_with_batch_mode_and_only_the_ssh_transport(self) -> None:
        cmd = self.build()
        joined = " ".join(cmd)
        assert (
            "core.sshCommand=/usr/bin/ssh -o BatchMode=yes -o ClearAllForwardings=yes "
            "-o ForwardAgent=no -o PermitLocalCommand=no"
        ) in joined
        assert "protocol.allow=never" in cmd and "protocol.ssh.allow=always" in cmd

    def test_it_carries_the_neutralising_overrides_and_never_force_or_a_remote_name(self) -> None:
        cmd = self.build()
        for needed in (
            "core.fsmonitor=false",
            "credential.helper=",
            "core.askPass=",
            "core.pager=cat",
        ):
            assert needed in cmd
        assert any(a.startswith("core.hooksPath=") for a in cmd)
        assert not {"--force", "-f", "--mirror", "--delete", "--tags", "origin"} & set(cmd)
        assert "--no-pager" in cmd and "push.followTags=false" in cmd

    def test_a_ssh_path_with_spaces_or_quotes_is_shell_quoted(self) -> None:
        tools = Tools("/usr/bin/git", "", "/opt/my ssh/bin; touch x")
        cmd = argv.push_argv(tools, argv.parse_url("git@github.com:o/r.git"), SHA, "m")
        value = next(a for a in cmd if a.startswith("core.sshCommand="))
        import shlex

        assert shlex.split(value.split("=", 1)[1])[0] == "/opt/my ssh/bin; touch x/ssh"

    def test_ls_remote_has_the_same_shape(self) -> None:
        cmd = argv.ls_remote_argv(TOOLS, argv.parse_url("git@github.com:o/r.git"), "feat/x")
        assert cmd[-3:] == ["--", "git@github.com:o/r.git", "refs/heads/feat/x"]
        assert "ls-remote" in cmd
