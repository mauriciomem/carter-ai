"""``carter pr`` (plan 003 step 20; RFC-0007 C.6.6): the handoff file in, a ``gh`` argv out.

Real git with a local bare ``origin``; ``gh`` is the recording fake (``fake_gh``), whose log
shows the argv, the environment it was given and the ``--body-file`` as it was at call time.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from aplus.helpers import commit_file, git
from carter.aplus import handoff, pr, run
from carter.aplus.handoff import Handoff, handoff_path, write_handoff
from carter.cli import main
from carter.identity.errors import (
    E_APLUS_ARGS,
    E_HANDOFF,
    E_HUMAN_TERMINAL,
    E_SECRET_SCAN,
)

URL = "https://github.com/o/r/pull/7"
NO_PARENT = json.dumps({"parent": None})
FORK = json.dumps({"parent": {"id": "x", "name": "upstream-repo", "owner": {"login": "up"}}})
BODY = "## Summary\n\n- the change\n- more\n"


@pytest.fixture
def ws(with_origin: Path, monkeypatch: pytest.MonkeyPatch, human_tty) -> Path:
    """feat/x pushed to origin at HEAD, cwd = repo, a human at a terminal."""
    git("checkout", "-q", "-b", "feat/x", cwd=with_origin)
    commit_file(with_origin, "feature.txt", message="feat: x")
    git("push", "-q", "origin", "feat/x", cwd=with_origin)
    monkeypatch.chdir(with_origin)
    human_tty(True)
    return with_origin


def head(repo: Path) -> str:
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def put(workspace: Path, **over: object) -> Path:
    fields = {
        "title": "feat: add x",
        "base": "main",
        "draft": False,
        "head_sha": head(workspace),
        "repo": "o/r",
        "body": BODY,
    }
    return write_handoff(workspace, "feat/x", Handoff(**{**fields, **over}))  # type: ignore[arg-type]


@pytest.fixture
def gh(fake_gh) -> Callable[..., object]:
    def script(*, parent: str = NO_PARENT, create_rc: int = 0, create_err: str = ""):
        return fake_gh(
            rules={
                "repo view": {"stdout": parent},
                "pr create": {"stdout": f"Creating pull request\n{URL}\n", "rc": create_rc,
                              "stderr": create_err},
            }
        )  # fmt: skip

    return script


def pr_cli(*, input: str | None = "y\n") -> Result:
    return CliRunner().invoke(main, ["pr"], input=input)


def created(fake) -> list[list[str]]:
    return [c for c in fake.calls() if c[:2] == ["pr", "create"]]


class TestRefusals:
    def test_an_agent_shell_is_refused_before_the_file_is_read(
        self, ws: Path, gh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = gh()
        path = put(ws)
        monkeypatch.setenv("OPENCODE_SESSION_ID", "s1")
        res = pr_cli()
        assert res.exit_code == 1 and f"Error: {E_HUMAN_TERMINAL}" in res.output
        assert fake.calls() == [] and path.exists()

    def test_no_tty_covers_the_bang_shell(self, ws: Path, gh, human_tty) -> None:
        fake = gh()
        path = put(ws)
        human_tty(False)
        res = pr_cli()
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
        assert "your own terminal" in res.output and "!carter" not in res.output
        assert fake.calls() == [] and path.exists()

    def test_arguments_are_refused(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws)
        res = CliRunner().invoke(main, ["pr", "--title", "x"])
        assert res.exit_code == 2 and fake.calls() == []
        res = CliRunner().invoke(main, ["pr", "other-branch"])
        assert res.exit_code == 1 and E_APLUS_ARGS in res.output and fake.calls() == []

    def test_a_missing_handoff_names_the_expected_path(self, ws: Path, gh) -> None:
        fake = gh()
        res = pr_cli()
        assert res.exit_code == 1 and f"Error: {E_HANDOFF}" in res.output
        assert ".carter/state/handoff/feat%2Fx.md" in res.output
        assert fake.calls() == []

    def test_only_the_current_branchs_handoff_is_read(self, ws: Path, gh) -> None:
        fake = gh()
        other = handoff_path(ws, "feat/other")
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text(put(ws).read_text())
        handoff_path(ws, "feat/x").unlink()
        res = pr_cli()
        assert res.exit_code == 1 and E_HANDOFF in res.output and fake.calls() == []
        assert other.exists()

    @pytest.mark.parametrize(
        "text",
        [
            "no front matter",
            "---\ntitle: x\n---\nbody",
            "---\ntitle: x\nbase: main\ndraft: false\nhead_sha: abc\nrepo: o/r\n---\n",
            "---\ntitle: x\nbase: main\ndraft: false\nhead_sha: " + "a" * 40 + "\nrepo: o/r\n"
            "extra: 1\n---\n",
        ],
    )
    def test_a_malformed_handoff_is_refused_and_kept(self, ws: Path, gh, text: str) -> None:
        fake = gh()
        path = handoff_path(ws, "feat/x")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        res = pr_cli()
        assert res.exit_code == 1 and E_HANDOFF in res.output
        assert fake.calls() == [] and path.exists()

    def test_a_head_sha_that_is_not_an_ancestor_is_refused(self, ws: Path, gh) -> None:
        fake = gh()
        path = put(ws, head_sha="1" * 40)
        res = pr_cli()
        assert res.exit_code == 1 and "not an ancestor of HEAD" in res.output
        assert fake.calls() == [] and path.exists()

    def test_an_older_head_sha_on_the_branch_is_fine(self, ws: Path, gh) -> None:
        fake = gh()
        old = head(ws)
        commit_file(ws, "later.txt")
        git("push", "-q", "origin", "feat/x", cwd=ws)
        put(ws, head_sha=old)
        assert pr_cli().exit_code == 0 and len(created(fake)) == 1

    def test_a_detached_head_is_refused(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws)
        git("checkout", "-q", "--detach", cwd=ws)
        res = pr_cli()
        assert res.exit_code == 1 and "detached HEAD" in res.output and fake.calls() == []


class TestSecretScan:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("body", "token: ghp_" + "A1b2C3d4" * 5 + "\n"),
            ("title", "fix: github_pat_" + "x" * 40),
            ("body", "AKIAIOSFODNN7EXAMPLE and more\n"),
        ],
    )
    def test_a_hit_refuses_before_any_gh_call_and_keeps_the_file(
        self, ws: Path, gh, field: str, value: str
    ) -> None:
        fake = gh()
        path = put(ws, **{field: value})
        res = pr_cli()
        assert res.exit_code == 1 and f"Error: {E_SECRET_SCAN}" in res.output
        assert fake.calls() == [] and path.exists()
        assert value.strip()[-12:] not in res.output  # the text itself is never echoed


class TestPreviewAndConfirm:
    def test_it_shows_title_target_base_and_the_first_40_body_lines(self, ws: Path, gh) -> None:
        gh()
        body = "\n".join(f"line {i}" for i in range(1, 61)) + "\n"
        put(ws, body=body, title="feat: preview", draft=True)
        res = pr_cli(input="n\n")
        out = res.output
        assert "Title:  feat: preview" in out and "Target: o/r" in out and "Base: main" in out
        assert "Draft:  yes" in out and "line 40" in out and "line 41" not in out
        assert "(20 more line(s) not shown)" in out

    @pytest.mark.parametrize("answer", ["n\n", "\n", "", "yes\n", "no\n"])
    def test_anything_but_y_creates_nothing(self, ws: Path, gh, answer: str) -> None:
        fake = gh()
        path = put(ws)
        res = pr_cli(input=answer)
        assert res.exit_code == 1 and "no pull request was created" in res.output
        assert created(fake) == [] and path.exists()
        assert fake.bodies() == []

    def test_control_characters_in_the_preview_are_defused(self, ws: Path, gh) -> None:
        gh()
        put(ws, body="evil \x1b]0;pwned\x07 end\n")
        out = pr_cli(input="n\n").output
        assert "\x1b" not in out and "\x07" not in out


class TestArgv:
    def test_the_exact_command_for_a_plain_pull_request(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws, title="feat: add x", draft=False)
        assert pr_cli().exit_code == 0
        (argv,) = created(fake)
        body = fake.bodies()[0]["path"]
        assert argv == [
            "pr", "create", "--repo=o/r", "--head=feat/x", "--base=main",
            "--title=feat: add x", f"--body-file={body}",
        ]  # fmt: skip

    def test_a_draft_adds_one_flag(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws, draft=True)
        pr_cli()
        assert created(fake)[0][-1] == "--draft"

    @pytest.mark.parametrize(
        "title", ["--web", "-w", "--repo=evil/x", "-F /etc/passwd", "--body=oops", "--", "-"]
    )
    def test_a_hostile_title_stays_one_argument_of_its_own_flag(
        self, ws: Path, gh, title: str
    ) -> None:
        fake = gh()
        put(ws, title=title)
        assert pr_cli().exit_code == 0
        (argv,) = created(fake)
        assert f"--title={title}" in argv
        assert title not in argv  # never a bare element that gh could read as an option
        assert len(argv) == 7 and all(a.startswith(("--", "pr", "create")) for a in argv)
        assert argv.count("--repo=o/r") == 1 and not any(a == "--web" for a in argv)

    def test_a_body_that_starts_with_a_dash_goes_in_the_file_not_on_the_line(
        self, ws: Path, gh
    ) -> None:
        fake = gh()
        put(ws, body="--web\n-w\n- item\n")
        assert pr_cli().exit_code == 0
        (argv,) = created(fake)
        assert all("--web" not in a or a.startswith("--title") for a in argv[:1] + argv[2:6])
        assert fake.bodies()[0]["content"] == "--web\n-w\n- item\n"

    def test_the_body_file_is_0600_holds_exactly_the_body_and_is_gone_afterwards(
        self, ws: Path, gh
    ) -> None:
        fake = gh()
        put(ws)
        pr_cli()
        (seen,) = fake.bodies()
        assert seen["mode"] == "0o600" and seen["content"] == BODY
        assert not os.path.exists(seen["path"]) and not os.path.exists(Path(seen["path"]).parent)

    def test_the_body_file_is_removed_when_gh_fails_and_when_the_human_declines(
        self, ws: Path, gh
    ) -> None:
        fake = gh(create_rc=1, create_err="boom")
        put(ws)
        pr_cli()
        assert not os.path.exists(fake.bodies()[0]["path"])

    def test_no_token_is_forced_on_gh(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws)
        pr_cli()
        assert all(e["GH_TOKEN"] is None and e["GITHUB_TOKEN"] is None for e in fake.envs())
        assert all(e["GH_PROMPT_DISABLED"] == "1" for e in fake.envs())

    def test_a_stale_token_variable_is_named_never_shown(
        self, ws: Path, gh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh()
        put(ws)
        monkeypatch.setenv("GITHUB_TOKEN", "github_pat_STALESENTINEL")
        out = pr_cli(input="n\n").output
        assert "GITHUB_TOKEN is set, so gh uses it" in out and "STALESENTINEL" not in out

    def test_gh_is_run_by_absolute_path(self, gh) -> None:
        fake = gh()
        found = run.gh_path()
        assert found == str(fake.bindir / "gh") and os.path.isabs(found)

    def test_a_missing_gh_is_a_clear_message(
        self, ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        put(ws)
        bindir = tmp_path / "onlygit"
        bindir.mkdir()
        import shutil

        (bindir / "git").symlink_to(shutil.which("git") or "/usr/bin/git")
        monkeypatch.setenv("PATH", str(bindir))
        res = pr_cli()
        assert res.exit_code == 1 and "gh not found" in res.output and "gh auth login" in res.output
        assert handoff_path(ws, "feat/x").exists()


class TestFork:
    def test_the_target_is_the_parent_and_the_head_is_owner_colon_branch(
        self, ws: Path, gh
    ) -> None:
        fake = gh(parent=FORK)
        put(ws)
        assert pr_cli().exit_code == 0
        (argv,) = created(fake)
        assert "--repo=up/upstream-repo" in argv and "--head=o:feat/x" in argv
        assert fake.calls()[0] == ["repo", "view", "o/r", "--json", "parent"]

    def test_the_repo_is_positional_for_repo_view_never_dash_r(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws)
        pr_cli()
        view = fake.calls()[0]
        assert view[:3] == ["repo", "view", "o/r"] and "-R" not in view and "--repo" not in view

    def test_a_malformed_parent_falls_back_to_the_repo_itself(self, ws: Path, gh) -> None:
        fake = gh(parent=json.dumps({"parent": {"name": "x y", "owner": {"login": "../"}}}))
        put(ws)
        pr_cli()
        assert "--repo=o/r" in created(fake)[0]

    def test_gh_failing_on_repo_view_stops_with_its_message(self, ws: Path, fake_gh) -> None:
        fake = fake_gh(rules={"repo view": {"rc": 1, "stderr": "HTTP 404: Not Found"}})
        path = put(ws)
        res = pr_cli()
        assert res.exit_code == 1 and "gh could not read o/r" in res.output
        assert "404" in res.output and created(fake) == [] and path.exists()

    def test_a_handoff_for_another_repo_than_origin_is_refused(
        self, ws: Path, gh, monkeypatch
    ) -> None:
        fake = gh()
        git("remote", "set-url", "origin", "git@github.com:real/repo.git", cwd=ws)
        path = put(ws, repo="evil/target")
        res = pr_cli()
        assert res.exit_code == 1 and "not the repo of origin" in res.output
        assert fake.calls() == [] and path.exists()

    def test_the_match_with_origin_is_case_insensitive(self, ws: Path, gh) -> None:
        gh()
        git("remote", "set-url", "origin", "https://github.com/O/R.git", cwd=ws)
        put(ws)
        item = handoff.read_handoff(ws, "feat/x")
        out: list[str] = []
        from carter.aplus.push import Io

        target, head_ = pr._target(ws, item, "feat/x", Io(out.append, lambda _p: ""))
        assert (target, head_) == ("o/r", "feat/x") and out == []

    def test_a_non_github_origin_is_noted_not_trusted_silently(self, ws: Path, gh) -> None:
        gh()
        put(ws)
        assert "was not cross-checked" in pr_cli(input="n\n").output


class TestPushFirst:
    def test_a_branch_missing_on_origin_offers_the_push_then_continues(self, ws: Path, gh) -> None:
        fake = gh()
        git("push", "-q", "origin", "--delete", "feat/x", cwd=ws)
        put(ws)
        res = pr_cli(input="y\ny\n")  # push confirmation, then the PR confirmation
        assert res.exit_code == 0, res.output
        assert "not on origin at HEAD" in res.output and "Pushed feat/x to origin" in res.output
        assert "refs/heads/feat/x" in git("ls-remote", "--heads", "origin", cwd=ws).stdout
        assert len(created(fake)) == 1
        assert res.output.index("Pushed feat/x") < res.output.index("Create this pull request")

    def test_a_branch_behind_the_local_head_is_pushed_too(self, ws: Path, gh) -> None:
        fake = gh()
        commit_file(ws, "newer.txt")
        put(ws)
        res = pr_cli(input="y\ny\n")
        assert res.exit_code == 0 and "Pushed feat/x" in res.output and len(created(fake)) == 1

    def test_declining_the_push_creates_nothing_and_keeps_the_file(self, ws: Path, gh) -> None:
        fake = gh()
        git("push", "-q", "origin", "--delete", "feat/x", cwd=ws)
        path = put(ws)
        res = pr_cli(input="n\n")
        assert res.exit_code == 1 and created(fake) == [] and path.exists()
        assert "refs/heads/feat/x" not in git("ls-remote", "--heads", "origin", cwd=ws).stdout

    def test_a_branch_already_on_origin_at_head_does_not_push(self, ws: Path, gh) -> None:
        gh()
        put(ws)
        res = pr_cli()
        assert res.exit_code == 0 and "Pushed" not in res.output


class TestResult:
    def test_success_prints_the_url_and_deletes_the_handoff(self, ws: Path, gh) -> None:
        gh()
        path = put(ws)
        res = pr_cli()
        assert res.exit_code == 0, res.output
        assert f"Created: {URL}" in res.output and not path.exists()

    def test_only_this_branchs_handoff_is_deleted(self, ws: Path, gh) -> None:
        gh()
        put(ws)
        other = handoff_path(ws, "feat/other")
        other.write_text("keep me")
        pr_cli()
        assert other.exists() and other.read_text() == "keep me"

    def test_a_gh_failure_keeps_the_file_and_never_shows_the_body(self, ws: Path, gh) -> None:
        gh(create_rc=1, create_err="GraphQL: not allowed\nsecond line")
        path = put(ws, body="SECRETBODYSENTINEL\n")
        res = pr_cli()
        assert res.exit_code == 1 and path.exists()
        failure = [ln for ln in res.output.splitlines() if "gh pr create failed" in ln]
        assert failure and "not allowed" in failure[0] and "SECRETBODYSENTINEL" not in failure[0]
        assert "kept" in failure[0]

    def test_urls_with_credentials_in_gh_output_are_masked(self, ws: Path, fake_gh) -> None:
        fake_gh(
            rules={
                "repo view": {"stdout": NO_PARENT},
                "pr create": {"rc": 1, "stderr": "fatal: https://user:HUNTER2@github.com/o/r"},
            }
        )
        put(ws)
        assert "HUNTER2" not in pr_cli().output

    def test_a_second_run_after_success_finds_no_handoff(self, ws: Path, gh) -> None:
        fake = gh()
        put(ws)
        assert pr_cli().exit_code == 0
        again = pr_cli()
        assert again.exit_code == 1 and E_HANDOFF in again.output and len(created(fake)) == 1
