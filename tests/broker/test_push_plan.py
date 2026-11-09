# ruff: noqa: E501
"""``broker push --plan``: range, signatures, default branch, refusals."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from aplus.helpers import git
from broker.world import DEVOPS, ORIGIN, World
from carter.broker import plan as planmod
from carter.broker.plan import Caller
from carter.identity.errors import (
    E_B_ARGS,
    E_B_CALLER,
    E_B_DEFAULT,
    E_B_HTTPS,
    E_B_NOAGENT,
    E_B_REJECTED,
    E_B_REPOCFG,
    E_B_UNSIGNED,
    IdentityError,
)

needs_keygen = pytest.mark.skipif(
    not any(Path(p).exists() for p in ("/usr/bin/ssh-keygen", "/bin/ssh-keygen")),
    reason="no ssh-keygen",
)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = World(tmp_path)
    yield w
    w.close()


def build(w: World, caller: Caller = DEVOPS) -> planmod.PushPlan:
    return planmod.build_push_plan(w.repo, w.ctx, caller, w.server_env())


def refused(w: World, code: str, caller: Caller = DEVOPS) -> IdentityError:
    with pytest.raises(IdentityError) as exc:
        build(w, caller)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


class TestThePlan:
    def test_a_new_branch_plan_has_the_range_the_pinned_sha_and_the_commit_list(
        self, world: World
    ) -> None:
        sha = world.commit("a.txt")
        plan = build(world)
        assert (plan.branch, plan.pinned_sha, plan.new_branch) == ("feat/x", sha, True)
        assert (
            plan.base == world.base_sha and plan.base_label == "as of merge-base(origin/HEAD, HEAD)"
        )
        assert [c[0] for c in plan.commits] == [sha] and plan.url.slug == "o/r"

    def test_an_existing_remote_branch_uses_origin_branch_as_the_base(self, world: World) -> None:
        first = world.commit("a.txt")
        git("update-ref", "refs/remotes/origin/feat/x", first, cwd=world.repo)
        second = world.commit("b.txt")
        plan = build(world)
        assert (plan.base, plan.base_label, plan.new_branch) == (
            first,
            "as of origin/feat/x",
            False,
        )
        assert [c[0] for c in plan.commits] == [second]

    def test_the_plan_makes_no_network_call_and_uses_no_credential(self, world: World) -> None:
        world.commit("a.txt")
        build(world)
        # `ssh -G` is local (prints the effective config); a connection would be a remote command
        calls = world.fake.calls()
        assert calls and all(c["argv"][0] == "-G" for c in calls)
        assert not any("git-receive-pack" in " ".join(c["argv"]) for c in calls)
        assert all("SSH_AUTH_SOCK" not in c["env_names"] for c in calls)

    def test_the_plan_does_not_expose_the_server_password_or_the_socket(self, world: World) -> None:
        world.commit("a.txt")
        out = json.dumps(planmod.push_plan_json(build(world), world.ctx, DEVOPS))
        assert "sentinel-server-password" not in out and str(world.sock_path) not in out

    def test_sensitive_paths_are_shown_not_refused(self, world: World) -> None:
        (world.repo / ".github" / "workflows").mkdir(parents=True)
        (world.repo / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
        git("add", "-f", ".github/workflows/ci.yml", cwd=world.repo)
        git("commit", "-q", "-m", "ci", cwd=world.repo)
        plan = build(world)
        assert plan.sensitive == ("A .github/workflows/ci.yml",)

    def test_commit_subjects_are_escaped_and_capped(self, world: World) -> None:
        (world.repo / "x").write_text("x")
        git("add", "x", cwd=world.repo)
        git("commit", "-q", "-m", "subject\twith\x1b[31m escape " + "z" * 200, cwd=world.repo)
        (subject,) = [s for _sha, s in build(world).commits]
        assert "\x1b" not in subject and "\t" not in subject and len(subject) <= 72

    def test_bidi_and_zero_width_characters_cannot_disguise_the_prompt(self, world: World) -> None:
        """"""
        (world.repo / "x").write_text("x")
        git("add", "x", cwd=world.repo)
        git("commit", "-q", "-m", "ok\u202e evil\u200b\u2028end", cwd=world.repo)
        (subject,) = [s for _sha, s in build(world).commits]
        assert subject == "ok? evil??end"

    def test_more_than_twenty_commits_are_summarised(self, world: World) -> None:
        for i in range(23):
            world.commit(f"f{i}.txt")
        plan = build(world)
        assert plan.count == 23 and len(plan.commits) == 20
        ask = planmod.push_ask(plan, DEVOPS)
        assert any("3 earlier commit" in line for line in ask["resources"])


class TestPlanJsonSchema:
    def test_the_keys_and_types_are_stable(self, world: World) -> None:
        world.commit("a.txt")
        doc = planmod.push_plan_json(build(world), world.ctx, DEVOPS)
        assert sorted(doc) == [
            "approval", "ask", "audit", "base_label", "branch", "commits", "count", "new",
            "new_branch", "old", "pinned_sha", "repo", "sensitive", "verb",
        ]  # fmt: skip
        assert doc["verb"] == "push" and doc["repo"] == "o/r" and doc["count"] == 1
        assert doc["approval"] == {"min_dwell_ms": 500, "timeout_ms": 120000}
        assert sorted(doc["ask"]) == ["metadata", "resources"]
        assert sorted(doc["ask"]["metadata"]) == ["caller", "pinned", "session", "verb"]
        assert sorted(doc["audit"]) == ["branch", "commits", "owner_repo", "range", "verb"]
        assert sorted(doc["commits"][0]) == ["sha", "subject"]
        json.dumps(doc)

    def test_the_ask_names_the_caller_session_and_range_and_no_secret(self, world: World) -> None:
        world.commit("a.txt")
        doc = planmod.push_plan_json(build(world), world.ctx, DEVOPS)
        text = json.dumps(doc["ask"])
        assert (
            "carter-devops" in text and "ses_child1" in text and "feat/x" in text and ".." in text
        )
        assert "sentinel" not in text and "git@github.com" not in text

    def test_the_effective_dwell_is_at_least_500_and_only_configurable_upward(
        self, world: World
    ) -> None:
        from dataclasses import replace

        from carter.identity.schema import Broker

        for configured, expected in [
            (0, 500),
            (150, 500),
            (500, 500),
            (2000, 2000),
            (999_999, 10_000),
        ]:
            cfg = replace(world.cfg, broker=Broker(min_dwell_ms=configured))
            ctx = type(world.ctx)(cfg, world.ctx.owned, world.ctx.tools, world.home)
            assert planmod.dwell_ms(ctx) == expected


class TestRefusals:
    def test_a_caller_that_is_not_devops_is_refused_first(self, world: World) -> None:
        world.commit("a.txt")
        for agent in ("general", "build", "carter-engineer", ""):
            refused(world, E_B_CALLER, Caller(agent, "ses_c", "ses_r"))

    def test_odd_session_ids_are_refused(self, world: World) -> None:
        world.commit("a.txt")
        refused(world, E_B_ARGS, Caller("carter-devops", "a b", "ses_r"))
        refused(world, E_B_ARGS, Caller("carter-devops", "ses_c", "../x"))

    def test_the_remote_default_branch_is_refused_and_points_to_a_plus(self, world: World) -> None:
        git("checkout", "-q", "main", cwd=world.repo)
        world.commit("a.txt")
        err = refused(world, E_B_DEFAULT)
        assert "carter push" in str(err) and "`main`" in str(err)

    @pytest.mark.parametrize("name", ["main", "master"])
    def test_main_and_master_stay_refused_even_if_origin_head_was_moved_by_a_shell(
        self, world: World, name: str
    ) -> None:
        """`git remote set-head` moves a local ref; the usual defaults stay refused."""
        git("checkout", "-q", "-B", name, cwd=world.repo)
        git("update-ref", "refs/remotes/origin/other", world.base_sha, cwd=world.repo)
        git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/other", cwd=world.repo)
        world.commit("a.txt")
        refused(world, E_B_DEFAULT)

    def test_an_unknown_default_branch_fails_closed(self, world: World) -> None:
        world.commit("a.txt")
        git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD", cwd=world.repo)
        assert "origin/HEAD" in refused(world, E_B_ARGS).detail

    def test_a_non_fast_forward_is_refused(self, world: World) -> None:
        first = world.commit("a.txt")
        git("reset", "-q", "--hard", world.base_sha, cwd=world.repo)
        world.commit("b.txt")
        git("update-ref", "refs/remotes/origin/feat/x", first, cwd=world.repo)
        assert "non-fast-forward" in refused(world, E_B_ARGS).detail

    def test_an_empty_range_is_refused(self, world: World) -> None:
        assert "nothing to push" in refused(world, E_B_ARGS).detail

    def test_a_detached_head_is_refused(self, world: World) -> None:
        world.commit("a.txt")
        git("checkout", "-q", "--detach", cwd=world.repo)
        assert "detached" in refused(world, E_B_ARGS).detail

    def test_an_https_origin_is_routed_to_a_plus(self, world: World) -> None:
        world.commit("a.txt")
        git("remote", "set-url", "origin", "https://github.com/o/r.git", cwd=world.repo)
        assert "carter push" in str(refused(world, E_B_HTTPS))

    @pytest.mark.parametrize(
        "url", ["git@gitlab.com:o/r.git", "ssh://git@github.com:2222/o/r.git", "../x"]
    )
    def test_another_origin_shape_is_an_args_error(self, world: World, url: str) -> None:
        world.commit("a.txt")
        git("remote", "set-url", "origin", url, cwd=world.repo)
        refused(world, E_B_ARGS)

    def test_a_repo_that_is_not_a_repo_is_an_args_error(self, world: World, tmp_path: Path) -> None:
        elsewhere = tmp_path / "plain"
        elsewhere.mkdir()
        with pytest.raises(IdentityError) as exc:
            planmod.build_push_plan(elsewhere, world.ctx, DEVOPS, world.server_env())
        assert exc.value.code == E_B_ARGS

    @pytest.mark.parametrize(
        "text",
        [
            "[core]\n\tsshCommand = ssh -F /tmp/x\n",
            '[url "ssh://evil/"]\n\tinsteadOf = git@github.com:\n',
            "[credential]\n\thelper = !x\n",
        ],
    )
    def test_hostile_repo_config_is_refused_before_anything_else(
        self, world: World, text: str
    ) -> None:
        world.commit("a.txt")
        world.local_config(text)
        refused(world, E_B_REPOCFG)

    def test_a_hostile_ssh_config_is_refused(self, world: World) -> None:
        world.commit("a.txt")
        (world.home / ".ssh" / "config").write_text('Match exec "touch /tmp/x"\n')
        err = refused(world, E_B_REPOCFG)
        assert "ssh config" in err.detail and world.fake.calls() == []

    def test_a_stale_agent_socket_is_refused_so_nobody_approves_in_vain(self, world: World) -> None:
        world.commit("a.txt")
        with pytest.raises(IdentityError) as exc:
            planmod.build_push_plan(
                world.repo, world.ctx, DEVOPS, {"SSH_AUTH_SOCK": "/nonexistent"}
            )
        assert exc.value.code == E_B_NOAGENT

    def test_a_family_with_three_rejections_cannot_even_prompt(self, world: World) -> None:
        from carter.broker import counter

        world.commit("a.txt")
        for _ in range(3):
            counter.add(DEVOPS.root, world.ctx.carter_dir)
        refused(world, E_B_REJECTED)
        build_other = Caller("carter-devops", "ses_c", "ses_other_root")
        assert build(world, build_other).branch == "feat/x"

    def test_a_corrupt_counter_fails_closed(self, world: World) -> None:
        from carter.broker import counter

        world.commit("a.txt")
        counter.path(world.ctx.carter_dir).parent.mkdir(parents=True)
        counter.path(world.ctx.carter_dir).write_text("{broken")
        refused(world, E_B_REJECTED)


@needs_keygen
class TestSignatures:
    @pytest.fixture
    def kworld(self, tmp_path: Path) -> Iterator[World]:
        w = World(tmp_path, signing_key=True)
        yield w
        w.close()

    def test_an_unsigned_llm_commit_is_refused_naming_it(self, kworld: World) -> None:
        sha = kworld.commit("a.txt", llm=True)
        err = refused(kworld, E_B_UNSIGNED)
        assert sha[:12] in str(err)

    def test_a_signed_llm_commit_passes(self, kworld: World) -> None:
        kworld.commit("a.txt", llm=True, sign=True)
        assert build(kworld).count == 1

    def test_human_commits_are_not_looked_at(self, kworld: World) -> None:
        kworld.commit("a.txt")
        assert build(kworld).count == 1

    def test_a_commit_signed_by_an_unknown_key_is_refused(
        self, kworld: World, tmp_path: Path
    ) -> None:
        import subprocess

        other = tmp_path / "other"
        subprocess.run(
            [
                str(kworld.fake.bindir / "ssh-keygen"),
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(other),
            ],
            check=True,
        )
        kworld.key = (other, kworld.key[1], kworld.key[2])  # type: ignore[index]
        kworld.commit("a.txt", llm=True, sign=True)
        refused(kworld, E_B_UNSIGNED)

    def test_the_check_needs_no_unlocked_agent(self, kworld: World) -> None:
        kworld.commit("a.txt", llm=True, sign=True)
        # the only agent in the world is the fake socket with no keys (ssh-add exits 1)
        assert build(kworld).count == 1


def test_origin_constant_matches_the_fixture() -> None:
    assert ORIGIN == "git@github.com:o/r.git"
