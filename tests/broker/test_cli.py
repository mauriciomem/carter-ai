# ruff: noqa: E501
"""The broker CLI and the refusal layer: exit codes, JSON, pollution, record."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from broker.world import World
from carter import broker_cli
from carter.broker import audit, checks, counter, execute

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    w = World(tmp_path)
    # the one test seam for the account home: the resolver itself (never config or an env var)
    monkeypatch.setattr(checks, "account_home", lambda: w.home)
    # the CLI reads config.toml and the guard state from HOME; point HOME at the world
    monkeypatch.setenv("HOME", str(tmp_path / "home-for-cli"))
    (tmp_path / "home-for-cli").mkdir()
    from carter.identity.writer import write_config
    from carter.install.paths import carter_config_path

    write_config(w.cfg, carter_config_path(None))
    w.base_dir = None
    yield w
    w.close()


def call(w: World, *argv: str, environ: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    code = broker_cli.run(argv, environ if environ is not None else w.server_env(), out)
    return code, json.loads(out.getvalue())


def common(w: World, agent: str = "carter-devops") -> list[str]:
    return ["--cwd", str(w.repo), "--agent", agent, "--session", "ses_c", "--root", "ses_r",
            "--git", "/usr/bin/git", "--gh", w.gh.gh]  # fmt: skip


class TestPlanAndExec:
    def test_plan_prints_the_json_document_and_exits_zero(self, world: World) -> None:
        world.commit("a.txt")
        code, doc = call(world, "push", "--plan", *common(world))
        assert code == 0 and doc["verb"] == "push" and doc["pinned_sha"] == world.head()

    def test_exec_pushes_and_audits_in_the_users_carter_dir(self, world: World) -> None:
        sha = world.commit("a.txt")
        now = execute.now_ms()
        code, doc = call(world, "push", "--exec", *common(world), "--pinned-sha", sha,
                         "--asked-at", str(now - 700), "--answered-at", str(now))  # fmt: skip
        assert code == 0 and doc["pushed"] == sha and world.remote_ref() == sha
        assert audit.read_b()[-1]["decision"] == "approved"

    def test_exec_without_its_flags_is_a_refusal_not_a_crash(self, world: World) -> None:
        world.commit("a.txt")
        code, doc = call(world, "push", "--exec", *common(world))
        assert code == 1 and doc["code"] == "E-B-ARGS"

    def test_a_refusal_is_one_json_line_with_code_message_detail_and_is_audited(
        self, world: World
    ) -> None:
        world.commit("a.txt")
        code, doc = call(world, "push", "--plan", *common(world, agent="general"))
        assert (
            code == 1
            and sorted(doc) == ["code", "detail", "message"]
            and doc["code"] == "E-B-CALLER"
        )
        assert audit.read_b()[-1]["decision"] == "refused"

    def test_the_default_branch_refusal_routes_to_a_plus(self, world: World) -> None:
        from aplus.helpers import git

        git("checkout", "-q", "main", cwd=world.repo)
        world.commit("a.txt")
        code, doc = call(world, "push", "--plan", *common(world))
        assert code == 1 and doc["code"] == "E-B-DEFAULT" and "carter push" in doc["message"]


class TestUsage:
    @pytest.mark.parametrize(
        "argv",
        [[], ["push"], ["push", "--plan"], ["nope"], ["record"], ["push", "--plan", "--exec"], ["pr", "--plan"],  # there is no pr verb any more
         ["record", "--outcome", "maybe", "--agent", "a", "--session", "s", "--root", "r"]],
    )  # fmt: skip
    def test_bad_usage_exits_two_with_a_json_line(self, world: World, argv: list[str]) -> None:
        code, doc = call(world, *argv)
        assert code == 2 and doc["code"] == "usage"

    def test_there_is_no_flag_that_takes_a_remote_a_ref_or_a_url(self) -> None:
        text = broker_cli.parser().format_help()
        text += "".join(
            sub.format_help()
            for sub in broker_cli.parser()._subparsers._group_actions[0].choices.values()
        )  # type: ignore[union-attr]
        for word in ("--remote", "--ref", "--url", "--refspec", "--force", "--branch"):
            assert word not in text


class TestRefusalLayer:
    @pytest.mark.parametrize("argv", [["push", "--plan"], ["push", "--exec"]])
    def test_every_subcommand_refuses_in_an_agent_shell(
        self, world: World, argv: list[str]
    ) -> None:
        world.commit("a.txt")
        extra = (
            ["--pinned-sha", "x", "--asked-at", "1", "--answered-at", "2"]
            if "--exec" in argv
            else []
        )
        code, doc = call(
            world,
            *argv,
            *common(world),
            *extra,
            environ=world.server_env(AGENT="1", OPENCODE_SESSION_ID="ses_1"),
        )
        assert code == 1 and doc["code"] == "E-B-POLLUTED"
        assert "AGENT" in doc["message"] and "ses_1" not in json.dumps(doc)
        assert world.remote_ref() == ""

    def test_record_refuses_in_an_agent_shell_too(self, world: World) -> None:
        code, doc = call(world, "record", "--outcome", "rejected", "--agent", "carter-devops", "--session", "s",
                         "--root", "r", environ=world.server_env(CARTER_AGENT_SHELL="1"))  # fmt: skip
        assert code == 1 and doc["code"] == "E-B-POLLUTED"
        assert counter.count("r") == 0

    def test_isolation_values_are_pollution_and_are_named_never_scrubbed(
        self, world: World
    ) -> None:
        world.commit("a.txt")
        env = world.server_env(
            GIT_SSH_COMMAND="ssh -o IdentityAgent=none",
            DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent",
        )
        code, doc = call(world, "push", "--plan", *common(world), environ=env)
        assert code == 1 and doc["code"] == "E-B-POLLUTED"
        assert "GIT_SSH_COMMAND" in doc["message"] and "IdentityAgent" not in json.dumps(doc)

    def test_ordinary_desktop_state_and_tokens_are_not_pollution(self, world: World) -> None:
        world.commit("a.txt")
        env = world.server_env(
            GH_TOKEN="t", GITHUB_TOKEN="t", DBUS_SESSION_BUS_ADDRESS="unix:path=/run/bus"
        )
        code, _doc = call(world, "push", "--plan", *common(world), environ=env)
        assert code == 0

    def test_a_stale_agent_socket_is_noagent(self, world: World) -> None:
        world.commit("a.txt")
        code, doc = call(
            world,
            "push",
            "--plan",
            *common(world),
            environ={"HOME": "/x", "SSH_AUTH_SOCK": "/gone"},
        )
        assert code == 1 and doc["code"] == "E-B-NOAGENT"

    def test_the_server_password_reaches_neither_the_output_nor_the_audit_nor_the_child(
        self, world: World
    ) -> None:
        sha = world.commit("a.txt")
        now = execute.now_ms()
        code, doc = call(world, "push", "--exec", *common(world), "--pinned-sha", sha,
                         "--asked-at", str(now - 700), "--answered-at", str(now))  # fmt: skip
        assert code == 0
        everything = (
            json.dumps(doc)
            + (audit.audit_dir(None) / "b.jsonl").read_text()
            + (world.fake.bindir / "ssh.calls").read_text()
        )
        assert "sentinel-server-password" not in everything

    def test_no_marker_the_guard_honours_is_set(self, world: World) -> None:
        sha = world.commit("a.txt")
        now = execute.now_ms()
        call(world, "push", "--exec", *common(world), "--pinned-sha", sha, "--asked-at", str(now - 700), "--answered-at", str(now))  # fmt: skip
        names = {n for c in world.fake.calls() for n in c["env_names"]}
        assert (
            not {"CARTER_AGENT_SHELL", "CARTER_HUMAN_SHELL", "CARTER_BROKER", "AGENT", "OPENCODE"}
            & names
        )


class TestRecord:
    def rec(self, w: World, outcome: str, root: str = "ses_r") -> tuple[int, dict[str, Any]]:
        return call(w, "record", "--outcome", outcome, "--agent", "carter-devops", "--session", "ses_c", "--root", root,
                    "--audit", json.dumps({"owner_repo": "o/r", "branch": "feat/x", "range": "a..b", "commits": 2, "verb": "push", "evil": "x"}))  # fmt: skip

    def test_each_outcome_counts_and_writes_one_audit_line(self, world: World) -> None:
        for n, outcome in enumerate(("rejected", "corrected", "aborted"), 1):
            code, doc = self.rec(world, outcome)
            assert code == 0 and doc["count"] == n
        assert doc["stopped"] is True
        lines = audit.read_b()
        assert [e["decision"] for e in lines] == ["rejected", "corrected", "aborted"]
        assert lines[0]["owner_repo"] == "o/r" and "evil" not in json.dumps(lines)

    def test_a_timeout_returns_the_registry_text_for_the_wrapper(self, world: World) -> None:
        code, doc = self.rec(world, "timeout")
        assert code == 0 and doc["code"] == "E-B-TIMEOUT" and "120 s" in doc["message"]

    def test_the_third_one_makes_the_next_plan_refuse(self, world: World) -> None:
        world.commit("a.txt")
        for _ in range(3):
            self.rec(world, "rejected")
        code, doc = call(world, "push", "--plan", *common(world))
        assert code == 1 and doc["code"] == "E-B-REJECTED"
        # another root session (a new session) is free
        code, _ = call(world, "push", "--plan", "--cwd", str(world.repo), "--agent", "carter-devops", "--session", "ses_c2",
                       "--root", "ses_other", "--git", "/usr/bin/git", "--gh", world.gh.gh)  # fmt: skip
        assert code == 0

    def test_a_corrupt_counter_file_refuses_a_plan(self, world: World) -> None:
        world.commit("a.txt")
        counter.path().parent.mkdir(parents=True, exist_ok=True)
        counter.path().write_text("{nope")
        code, doc = call(world, "push", "--plan", *common(world))
        assert code == 1 and doc["code"] == "E-B-REJECTED"


def test_the_module_runs_as_python_dash_i_dash_m_and_refuses_cleanly(tmp_path: Path) -> None:
    home = tmp_path / "h"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO)}
    done = subprocess.run(
        [sys.executable, "-I", "-m", "carter.broker_cli", "push", "--plan"],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert done.returncode == 2 and json.loads(done.stdout)["code"] == "usage"
    env["AGENT"] = "1"
    done = subprocess.run(
        [sys.executable, "-I", "-m", "carter.broker_cli", "record", "--outcome", "rejected", "--agent", "a", "--session", "s", "--root", "r"],
        env=env, capture_output=True, text=True, cwd=REPO,
    )  # fmt: skip
    assert done.returncode == 1 and json.loads(done.stdout)["code"] == "E-B-POLLUTED"
    assert not os.path.exists(home / ".carter" / "run")
