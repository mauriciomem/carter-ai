# ruff: noqa: E501
"""``broker pr`` (plan 007 step 12): plan and exec from the handoff file, with a fake ``gh``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aplus.helpers import git
from broker.world import DEVOPS, World
from carter.aplus import handoff
from carter.broker import audit, counter, execute, pr
from carter.broker.plan import Caller
from carter.identity.errors import (
    E_B_ARGS,
    E_B_CALLER,
    E_B_DWELL,
    E_B_MOVED,
    E_HANDOFF,
    E_SECRET_SCAN,
    IdentityError,
)
from sentinels import prefixed

BRANCH = "feat/x"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = World(tmp_path)
    w.commit("a.txt")
    w.publish()
    yield w
    w.close()


def write(w: World, **over: Any) -> Path:
    fields = {
        "title": "Add a",
        "base": "main",
        "draft": False,
        "head_sha": w.head(),
        "repo": "o/r",
        "body": "Why\n\nBecause.\n",
    }
    fields.update(over)
    return handoff.write_handoff(w.repo, BRANCH, handoff.Handoff(**fields))


def plan_of(w: World, caller: Caller = DEVOPS) -> pr.PrPlan:
    return pr.build_pr_plan(w.repo, w.ctx, caller, w.server_env())


def go(
    w: World, *, dwell: int = 900, pinned: str | None = None, caller: Caller = DEVOPS
) -> dict[str, Any]:
    now = execute.now_ms()
    return pr.exec_pr(
        w.repo,
        w.ctx,
        caller,
        w.server_env(),
        pinned_sha=pinned or w.head(),
        asked_at=now - dwell,
        answered_at=now,
    )


def refused(code: str, fn: Any) -> IdentityError:
    with pytest.raises(IdentityError) as exc:
        fn()
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


def create_calls(w: World) -> list[dict[str, Any]]:
    return [c for c in w.gh.calls() if c["argv"][:2] == ["pr", "create"]]


class TestPlan:
    def test_the_plan_shows_title_base_and_the_body_preview(self, world: World) -> None:
        write(world, body="\n".join(f"line {i}" for i in range(60)) + "\n")
        doc = pr.pr_plan_json(plan_of(world), world.ctx, DEVOPS)
        assert (doc["verb"], doc["repo"], doc["title"], doc["base"], doc["draft"]) == (
            "pr",
            "o/r",
            "Add a",
            "main",
            False,
        )
        assert len(doc["body_preview"]) == 40 and doc["body_lines"] == 60
        assert sorted(doc) == ["approval", "ask", "audit", "base", "body_lines", "body_preview", "branch", "draft", "head_sha", "pinned_sha", "repo", "title", "verb"]  # fmt: skip

    def test_the_plan_calls_nothing(self, world: World) -> None:
        write(world)
        plan_of(world)
        assert world.gh.calls() == []

    def test_a_missing_handoff_names_the_expected_path(self, world: World) -> None:
        err = refused(E_HANDOFF, lambda: plan_of(world))
        assert "feat%2Fx.md" in err.detail

    def test_a_malformed_handoff_is_refused_and_kept(self, world: World) -> None:
        path = write(world)
        path.write_text("---\ntitle: x\n---\n")
        refused(E_HANDOFF, lambda: plan_of(world))
        assert path.exists()

    def test_only_this_branchs_handoff_is_read(self, world: World) -> None:
        handoff.write_handoff(
            world.repo, "other", handoff.Handoff("t", "main", False, world.head(), "o/r", "")
        )
        refused(E_HANDOFF, lambda: plan_of(world))

    def test_a_head_sha_that_is_not_an_ancestor_is_refused(self, world: World) -> None:
        write(world, head_sha="f" * 40)
        refused(E_HANDOFF, lambda: plan_of(world))

    def test_an_older_head_sha_on_the_branch_is_fine(self, world: World) -> None:
        old = world.head()
        write(world, head_sha=old)
        world.commit("b.txt")
        world.publish()
        assert plan_of(world).item.head_sha == old

    def test_the_handoff_repo_must_be_the_origin_repo(self, world: World) -> None:
        write(world, repo="someone/else")
        refused(E_HANDOFF, lambda: plan_of(world))

    @pytest.mark.parametrize("field", ["title", "body"])
    def test_a_secret_in_title_or_body_is_refused_before_gh(self, world: World, field: str) -> None:
        write(world, **{field: f"see {prefixed('ghp_')} please"})
        refused(E_SECRET_SCAN, lambda: plan_of(world))
        assert world.gh.calls() == []

    def test_a_secret_shaped_branch_name_is_refused(self, world: World) -> None:
        git("branch", "-m", f"feat/{prefixed('ghp_')}", cwd=world.repo)
        sha = world.head()
        git("update-ref", f"refs/remotes/origin/feat/{prefixed('ghp_')}", sha, cwd=world.repo)
        handoff.write_handoff(
            world.repo,
            f"feat/{prefixed('ghp_')}",
            handoff.Handoff("t", "main", False, sha, "o/r", ""),
        )
        refused(E_SECRET_SCAN, lambda: plan_of(world))

    def test_a_branch_that_is_not_on_origin_at_head_is_an_args_error_pointing_at_the_push(
        self, world: World
    ) -> None:
        write(world)
        world.commit("c.txt")  # HEAD moved past origin/feat/x
        err = refused(E_B_ARGS, lambda: plan_of(world))
        assert "carter_push" in err.detail and "carter push" in err.detail

    def test_a_non_devops_caller_is_refused(self, world: World) -> None:
        write(world)
        refused(E_B_CALLER, lambda: plan_of(world, Caller("general", "s", "r")))


class TestExec:
    def test_gh_runs_by_absolute_path_with_one_argv_element_per_flag(self, world: World) -> None:
        write(world, title="--web", body="-- body --\n")
        out = go(world)
        (call,) = create_calls(world)
        argv = call["argv"]
        assert argv[:2] == ["pr", "create"]
        assert "--repo=o/r" in argv and f"--head={BRANCH}" in argv and "--base=main" in argv
        assert "--title=--web" in argv and not {"--web", "--draft"} & set(argv)
        assert any(a.startswith("--body-file=") for a in argv)
        assert out["ok"] and out["url"] == "https://github.com/o/r/pull/7"

    def test_the_body_travels_in_a_0600_file_in_a_scratch_dir_that_is_deleted(
        self, world: World
    ) -> None:
        write(world, body="Hello\n")
        go(world)
        (call,) = create_calls(world)
        (body,) = call["bodies"]
        assert body["mode"] == "0o600" and body["text"] == "Hello\n"
        assert not Path(body["path"]).exists()
        assert Path(call["cwd"]) != world.repo and not str(call["cwd"]).startswith(str(world.repo))

    def test_the_handoff_is_deleted_only_after_success(self, world: World) -> None:
        path = write(world)
        world.gh.script({"pr create": {"stderr": "GraphQL: nope\n", "rc": 1}})
        err = refused(E_B_ARGS, lambda: go(world))
        assert (
            "gh pr create failed" in err.detail
            and "handoff is kept" in err.detail
            and path.exists()
        )
        world.gh.script({"pr create": {"stdout": "https://github.com/o/r/pull/9\n", "rc": 0}})
        go(world)
        assert not path.exists()

    def test_draft_adds_one_flag(self, world: World) -> None:
        write(world, draft=True)
        go(world)
        assert "--draft" in create_calls(world)[0]["argv"]

    def test_fork_flow_targets_the_parent_with_owner_colon_branch(self, world: World) -> None:
        write(world)
        world.gh.script(
            {
                "repo view": {
                    "stdout": json.dumps({"parent": {"owner": {"login": "up"}, "name": "stream"}}),
                    "rc": 0,
                }
            }
        )
        go(world)
        argv = create_calls(world)[0]["argv"]
        assert "--repo=up/stream" in argv and f"--head=o:{BRANCH}" in argv

    def test_a_secret_added_to_the_handoff_after_the_plan_is_caught_at_exec(
        self, world: World
    ) -> None:
        path = write(world)
        plan_of(world)
        write(world, body=f"oops {prefixed('ghp_')}\n")
        refused(E_SECRET_SCAN, lambda: go(world))
        assert create_calls(world) == [] and path.exists()

    def test_the_child_environment_is_the_pr_allow_list_and_has_no_secret(
        self, world: World
    ) -> None:
        write(world)
        go(world)
        (call,) = create_calls(world)
        names = set(call["env_names"])
        assert not {"OPENCODE_SERVER_PASSWORD", "SSH_AUTH_SOCK", "GH_TOKEN", "GITHUB_TOKEN"} & names
        assert {"GH_PROMPT_DISABLED", "GH_NO_UPDATE_NOTIFIER", "HOME", "PATH"} <= names

    def test_it_never_pushes(self, world: World) -> None:
        write(world)
        go(world)
        assert world.fake.calls() == [] or all(
            "git-receive-pack" not in " ".join(c["argv"]) for c in world.fake.calls()
        )

    def test_dwell_timeout_and_moved_refuse_before_gh(self, world: World) -> None:
        write(world)
        refused(E_B_DWELL, lambda: go(world, dwell=5))
        assert counter.count(DEVOPS.root, world.ctx.carter_dir) == 1
        refused(E_B_MOVED, lambda: go(world, pinned="e" * 40))
        assert create_calls(world) == []

    def test_every_outcome_is_audited_without_the_title(self, world: World) -> None:
        write(world, title="Secret-ish title")
        go(world)
        refused(E_B_DWELL, lambda: go(world, dwell=1))
        text = (audit.audit_dir(world.ctx.carter_dir) / "b.jsonl").read_text()
        decisions = [json.loads(x)["decision"] for x in text.splitlines()]
        assert decisions == ["approved", "dwell"] and "Secret-ish" not in text

    def test_gh_missing_is_an_args_error(self, world: World, tmp_path: Path) -> None:
        write(world)
        from carter.broker.env import Tools

        ctx = world.ctx
        bad = type(ctx)(
            ctx.cfg,
            ctx.owned,
            Tools(ctx.tools.git, str(tmp_path / "nogh"), ctx.tools.ssh_bin_dir),
            ctx.home,
        )
        with pytest.raises(IdentityError) as exc:
            pr.build_pr_plan(world.repo, bad, DEVOPS, world.server_env())
        assert exc.value.code == E_B_ARGS and "gh" in exc.value.detail
