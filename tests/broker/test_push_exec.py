# ruff: noqa: E501
"""``broker push --exec``: pinned push, lock, audit. Fake ssh + a bare remote."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aplus.helpers import git
from broker.world import DEVOPS, World
from carter.broker import audit, counter, execute, plan
from carter.broker.plan import Caller
from carter.identity.errors import (
    E_B_ARGS,
    E_B_DWELL,
    E_B_MOVED,
    E_B_NOAGENT,
    E_B_REJECTED,
    E_B_REPOCFG,
    E_B_TIMEOUT,
    IdentityError,
)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = World(tmp_path)
    yield w
    w.close()


def go(
    w: World, pinned: str | None = None, *, dwell: int = 800, caller: Caller = DEVOPS, **kw: Any
) -> dict[str, Any]:
    now = execute.now_ms()
    server = kw.pop("server", None) or w.server_env()
    return execute.exec_push(
        w.repo, w.ctx, caller, server, pinned_sha=pinned or w.head(),
        asked_at=now - dwell, answered_at=now, **kw,
    )  # fmt: skip


def refused(w: World, code: str, pinned: str | None = None, **kw: Any) -> IdentityError:
    with pytest.raises(IdentityError) as exc:
        go(w, pinned, **kw)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


def lines(w: World) -> list[dict[str, Any]]:
    return audit.read_b(w.ctx.carter_dir)


class TestSuccess:
    def test_the_bare_remote_gets_exactly_the_pinned_commit(self, world: World) -> None:
        sha = world.commit("a.txt")
        result = go(world)
        assert result["ok"] and result["pushed"] == sha and world.remote_ref() == sha
        assert world.remote_ref("main") == world.base_sha  # nothing else moved

    def test_the_push_went_through_the_fake_ssh_as_git_at_github_with_the_agent_socket_only(
        self, world: World
    ) -> None:
        world.commit("a.txt")
        go(world)
        push_calls = [c for c in world.fake.calls() if "git-receive-pack" in " ".join(c["argv"])]
        assert len(push_calls) >= 1
        call = push_calls[0]
        assert call["argv"][-2] == "git@github.com"
        assert "SSH_AUTH_SOCK" in call["env_names"]
        assert not [
            n for n in call["env_names"] if n.startswith(("OPENCODE", "CARTER", "GH_", "GITHUB"))
        ]

    def test_the_server_password_never_reaches_the_child(
        self, world: World, tmp_path: Path
    ) -> None:
        world.commit("a.txt")
        go(world)
        assert "sentinel-server-password" not in (world.fake.bindir / "ssh.calls").read_text()

    def test_the_local_tracking_ref_follows_so_the_next_plan_is_incremental(
        self, world: World
    ) -> None:
        sha = world.commit("a.txt")
        go(world)
        assert git("rev-parse", "refs/remotes/origin/feat/x", cwd=world.repo).stdout.strip() == sha
        second = world.commit("b.txt")
        again = plan.build_push_plan(world.repo, world.ctx, DEVOPS, world.server_env())
        assert [c[0] for c in again.commits] == [second] and again.base == sha

    def test_the_audit_line_is_written_with_the_dwell_and_no_secret(self, world: World) -> None:
        world.commit("a.txt")
        go(world, dwell=1234)
        (line,) = lines(world)
        assert (line["decision"], line["dwell_ms"], line["verb"], line["owner_repo"]) == (
            "approved",
            1234,
            "push",
            "o/r",
        )
        assert (line["root"], line["session"], line["agent"]) == (
            "ses_root1",
            "ses_child1",
            "carter-devops",
        )
        text = (audit.audit_dir(world.ctx.carter_dir) / "b.jsonl").read_text()
        assert "sentinel" not in text and "git@github.com" not in text


class TestRefusalsChangeNothing:
    def untouched(self, w: World) -> None:
        assert w.remote_ref() == ""

    def test_head_moved_after_approval(self, world: World) -> None:
        pinned = world.commit("a.txt")
        world.commit("b.txt")
        err = refused(world, E_B_MOVED, pinned)
        assert pinned[:12] in str(err)
        self.untouched(world)
        assert lines(world)[-1]["decision"] == "refused" and lines(world)[-1]["code"] == E_B_MOVED

    @pytest.mark.parametrize(
        ("dwell", "code"),
        [(3, E_B_DWELL), (499, E_B_DWELL), (0, E_B_DWELL), (-5, E_B_DWELL), (120_001, E_B_TIMEOUT)],
    )
    def test_dwell_and_timeout_refuse_before_git_and_count_as_a_rejection(
        self, world: World, dwell: int, code: str
    ) -> None:
        world.commit("a.txt")
        refused(world, code, dwell=dwell)
        self.untouched(world)
        assert not [c for c in world.fake.calls() if "git-receive-pack" in " ".join(c["argv"])]
        assert counter.count(DEVOPS.root, world.ctx.carter_dir) == 1
        assert lines(world)[-1]["decision"] == {E_B_DWELL: "dwell", E_B_TIMEOUT: "timeout"}[code]

    def test_the_dwell_message_names_the_numbers(self, world: World) -> None:
        world.commit("a.txt")
        text = str(refused(world, E_B_DWELL, dwell=3))
        assert "3ms" in text and "500ms" in text

    def test_exactly_the_floor_passes(self, world: World) -> None:
        sha = world.commit("a.txt")
        assert go(world, dwell=500)["pushed"] == sha

    def test_stale_or_forged_timestamps_are_refused(self, world: World) -> None:
        world.commit("a.txt")
        now = execute.now_ms()
        with pytest.raises(IdentityError) as exc:
            execute.exec_push(world.repo, world.ctx, DEVOPS, world.server_env(), pinned_sha=world.head(),
                              asked_at=now - 900_000, answered_at=now - 899_000)  # fmt: skip
        assert exc.value.code == E_B_ARGS and "timestamps" in exc.value.detail
        self.untouched(world)

    def test_a_non_devops_caller(self, world: World) -> None:
        world.commit("a.txt")
        refused(world, "E-B-CALLER", caller=Caller("general", "s", "r"))
        self.untouched(world)

    def test_a_stopped_family(self, world: World) -> None:
        world.commit("a.txt")
        for _ in range(3):
            counter.add(DEVOPS.root, world.ctx.carter_dir)
        refused(world, E_B_REJECTED)
        self.untouched(world)

    def test_hostile_repo_config_added_between_plan_and_exec(self, world: World) -> None:
        world.commit("a.txt")
        world.local_config("[core]\n\tsshCommand = evil\n")
        refused(world, E_B_REPOCFG)
        self.untouched(world)
        assert not [c for c in world.fake.calls() if "git-receive-pack" in " ".join(c["argv"])]

    def test_a_hostile_ssh_config_added_between_plan_and_exec(self, world: World) -> None:
        world.commit("a.txt")
        (world.home / ".ssh" / "config").write_text('Match exec "x"\n')
        refused(world, E_B_REPOCFG)
        self.untouched(world)

    def test_a_config_written_after_the_plan_checks_is_caught_by_the_last_look_before_the_push(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """the window between the checks and `git push` is the lock, not more."""
        world.commit("a.txt")
        real = execute.repo_lock

        def hostile(*args: Any, **kw: Any):  # type: ignore[no-untyped-def]
            world.local_config('[url "ssh://evil.invalid/"]\n\tinsteadOf = git@github.com:\n')
            return real(*args, **kw)

        monkeypatch.setattr(execute, "repo_lock", hostile)
        refused(world, E_B_REPOCFG)
        self.untouched(world)
        assert not [c for c in world.fake.calls() if "git-receive-pack" in " ".join(c["argv"])]

    def test_a_dead_agent_at_exec(self, world: World) -> None:
        world.commit("a.txt")
        refused(world, E_B_NOAGENT, server={"HOME": "/x"})
        self.untouched(world)

    def test_an_unwritable_audit_blocks_the_push(self, world: World) -> None:
        world.commit("a.txt")
        directory = audit.audit_dir(world.ctx.carter_dir)
        directory.parent.mkdir(parents=True)
        directory.mkdir()
        (directory / "b.jsonl").symlink_to(world.tmp / "elsewhere")
        err = refused(world, E_B_ARGS)
        assert "audit" in err.detail
        self.untouched(world)


class TestFailureModes:
    def test_a_remote_that_rejects_gives_a_clear_error_and_an_audit_line(
        self, world: World
    ) -> None:
        world.commit("a.txt")
        hook = world.bare / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'rejected by policy' >&2\nexit 1\n")
        hook.chmod(0o755)
        err = refused(world, E_B_ARGS)
        assert "git push failed" in err.detail and "rejected" in err.detail
        assert [e["decision"] for e in lines(world)] == ["approved", "error"]
        assert world.remote_ref() == ""

    def test_an_ssh_failure_is_reported_without_retry(self, world: World) -> None:
        world.commit("a.txt")
        (world.fake.bindir / "ssh").write_text(
            "#!/bin/sh\ncase \"$1\" in -G) echo host github.com; exit 0;; esac\necho 'auth failed for git@github.com' >&2\nexit 255\n"
        )
        err = refused(world, E_B_ARGS)
        assert "exit 128" in err.detail and "auth failed" in err.detail

    def test_output_is_masked_and_control_characters_removed(self, world: World) -> None:
        world.commit("a.txt")
        (world.fake.bindir / "ssh").write_text(
            "#!/bin/sh\ncase \"$1\" in -G) echo host github.com; exit 0;; esac\nprintf 'fatal: https://user:tok3n@host/x \\033[31mred\\n' >&2\nexit 255\n"
        )
        detail = refused(world, E_B_ARGS).detail
        assert "tok3n" not in detail and "\x1b" not in detail and "***@" in detail

    def test_a_remote_that_accepts_but_does_not_move_is_caught_by_the_read_back(
        self, world: World
    ) -> None:
        world.commit("a.txt")
        hook = world.bare / "hooks" / "update"  # swallow the update silently
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        # make the remote ignore the ref: delete it right after receive via post-receive
        post = world.bare / "hooks" / "post-receive"
        post.write_text("#!/bin/sh\ngit update-ref -d refs/heads/feat/x\nexit 0\n")
        post.chmod(0o755)
        assert "not at the pinned commit" in refused(world, E_B_ARGS).detail


class TestLock:
    def test_concurrent_execs_on_one_repo_serialise(self, world: World, tmp_path: Path) -> None:
        import threading

        world.commit("a.txt")
        order: list[str] = []
        guard = threading.Lock()

        def hold(name: str, seconds: float) -> None:
            with execute.repo_lock(world.ctx.carter_dir, world.repo):
                with guard:
                    order.append(f"{name}-in")
                time.sleep(seconds)
                with guard:
                    order.append(f"{name}-out")

        threads = [threading.Thread(target=hold, args=(n, 0.15)) for n in "ab"]
        for t in threads:
            t.start()
            time.sleep(0.03)
        for t in threads:
            t.join()
        assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])

    def test_different_repos_do_not_share_a_lock(self, world: World, tmp_path: Path) -> None:
        with (
            execute.repo_lock(world.ctx.carter_dir, world.repo),
            execute.repo_lock(world.ctx.carter_dir, tmp_path),
        ):
            pass


def test_the_result_is_json_serialisable(world: World) -> None:
    world.commit("a.txt")
    json.dumps(go(world))
