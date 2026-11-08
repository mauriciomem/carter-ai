# ruff: noqa: E501
"""Slice B on a real isolated OpenCode (plan 007 step 19; RFC-0007 App A §5 slice B, App C.5).

A real OpenCode in its own HOME, ports and loopback-only netns, the mock model, Carter's own
``carter install`` (plugin, isolation.json, per-agent denies, the Carter agents), the REAL broker
core, a fake ``ssh`` that runs ``receive-pack`` against a local bare remote, a fake ``gh``, a fake
agent socket and a scripted human who answers the permission prompt through the API (``btools``).
No TUI (step 24), no real GitHub, no user key. Opt-in: ``CARTER_E2E=1``; 2.1.4 required, 2.1.2
through ``CARTER_E2E_OPENCODE_ALT``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from carter.broker import counter
from e2e.btools import (
    DEVOPS,
    FORCE_PUSH,
    HUMAN_PAUSE,
    LLM_EMAIL,
    BLab,
    close_lab,
    make_lab,
    run_git,
    write_config_toml,
)  # fmt: skip

pytestmark = pytest.mark.e2e


@pytest.fixture
def lab(rig_factory, opencode_bin) -> Iterator[BLab]:  # type: ignore[no-untyped-def]
    state = make_lab(rig_factory, opencode_bin)
    yield state
    close_lab(state)


def decisions(lab: BLab) -> list[str]:
    return [e["decision"] for e in lab.audit()]


class TestApproval:
    def test_devops_asks_the_human_who_approves_after_a_pause_and_the_pinned_commit_lands(
        self, lab: BLab
    ) -> None:
        sha = lab.commit("a.txt")
        sid, ask, text = lab.push("once")
        assert ask["action"] == "carter_push" and not ask.get("save"), (
            "no save: Once or Reject only"
        )
        assert ask["resources"][0] == "push o/r feat/x"
        assert ask["metadata"]["caller"] == DEVOPS and ask["metadata"]["session"] == sid
        assert "Pushed feat/x" in text
        assert lab.remote_ref() == sha
        assert lab.remote_ref("main") != sha  # only the branch moved
        (line,) = lab.audit()
        assert (line["decision"], line["agent"], line["owner_repo"], line["branch"]) == (
            "approved",
            DEVOPS,
            "o/r",
            "feat/x",
        )
        assert line["dwell_ms"] >= 500 and line["root"] == sid
        assert lab.git("rev-parse", "refs/remotes/origin/feat/x") == sha

    def test_the_prompt_is_asked_again_every_time_even_after_always(self, lab: BLab) -> None:
        lab.commit("a.txt")
        sid, _ask, _ = lab.push("once")
        lab.commit("b.txt")
        before = lab.say(sid, FORCE_PUSH)
        ask = lab.wait_ask()
        assert ask["action"] == "carter_push"
        lab.reply(ask, "always")  # "always" has nothing to save
        assert "Pushed" in lab.result(before)
        assert lab.rig.api("GET", "/api/permission/saved")["data"] == []

    def test_a_reject_pushes_nothing_ends_the_turn_and_counts_once(self, lab: BLab) -> None:
        lab.commit("a.txt")
        sid, _ask, _ = lab.push("reject")
        lab.wait_for(lambda: decisions(lab) == ["rejected"])
        assert lab.remote_ref() == "" and lab.counted(sid) == 1

    def test_three_rejections_in_a_session_family_stop_b_until_a_reset_or_a_new_session(
        self, lab: BLab
    ) -> None:
        lab.commit("a.txt")
        sid = lab.session()
        for n in (1, 2, 3):
            before = lab.say(sid, FORCE_PUSH)
            lab.reply(lab.wait_ask(), "reject")
            lab.wait_for(lambda n=n: len(lab.audit()) == n)
            del before
        assert lab.counted(sid) == 3
        before = lab.say(sid, FORCE_PUSH)
        text = lab.result(before)
        assert "E-B-REJECTED" in text and "3 rejections" in text and not lab.pending()
        assert lab.remote_ref() == ""
        # a new root session is free; the human's reset clears the old one
        other = lab.session()
        before = lab.say(other, FORCE_PUSH)
        ask = lab.wait_ask()
        lab.reply(ask, "once")
        assert "Pushed" in lab.result(before)
        counter.reset(lab.carter_dir)
        assert lab.counted(sid) == 0

    def test_an_instant_approval_is_a_dwell_refusal_before_git_runs(self, lab: BLab) -> None:
        lab.commit("a.txt")
        sid = lab.session()
        before = lab.say(sid, FORCE_PUSH)
        lab.reply(lab.wait_ask(), "once", pause=0)
        text = lab.result(before)
        assert "E-B-DWELL" in text and "looks like client auto-accept" in text
        assert lab.remote_ref() == "" and decisions(lab) == ["dwell"] and lab.counted(sid) == 1
        assert not [c for c in lab.ssh.calls() if "git-receive-pack" in " ".join(c["argv"])]

    def test_head_moving_between_the_prompt_and_the_push_is_refused(self, lab: BLab) -> None:
        lab.commit("a.txt")
        sid = lab.session()
        before = lab.say(sid, FORCE_PUSH)
        ask = lab.wait_ask()
        lab.commit("sneaky.txt")  # HEAD moves while the human is looking at the prompt
        lab.reply(ask, "once")
        assert "E-B-MOVED" in lab.result(before)
        assert lab.remote_ref() == ""


class TestWhoCanAsk:
    @pytest.mark.parametrize(
        "agent",
        ["build", "plan", "general", "carter-engineer", "carter-maestro", "carter-security"],
    )
    def test_every_other_agent_has_no_tool_at_all(self, lab: BLab, agent: str) -> None:
        sid = lab.session(agent)
        before = lab.say(sid, FORCE_PUSH)
        text = lab.result(before)
        assert (
            "No tool named" in text
            and "carter_push" in text
            and not lab.pending()
            and lab.audit() == []
        )

    def test_a_subagent_of_devops_is_general_and_denied(self, lab: BLab) -> None:
        sid = lab.session(DEVOPS)
        before = lab.say(sid, "TASK " + FORCE_PUSH)
        del before
        time.sleep(
            6
        )  # the child (agent `general`) tries the tool: there is none, so nothing to ask
        assert not lab.pending() and lab.audit() == [] and lab.remote_ref() == ""

    def test_devops_run_as_a_subagent_asks_in_the_child_session_and_counts_by_the_root(
        self, lab: BLab
    ) -> None:
        lab.commit("a.txt")
        parent = lab.session("build")
        lab.say(parent, f"TASKAS {DEVOPS} {FORCE_PUSH}")
        ask = lab.wait_ask()
        assert ask["sessionID"] != parent
        child = lab.rig.api("GET", f"/api/session/{ask['sessionID']}")["data"]
        assert child.get("parentID") == parent
        lab.reply(ask, "reject")
        lab.wait_for(lambda: lab.audit())
        (line,) = lab.audit()
        assert (line["root"], line["session"], line["decision"]) == (
            parent,
            ask["sessionID"],
            "rejected",
        )
        assert lab.counted(parent) == 1


class TestHeadless:
    def run_client(
        self, lab: BLab, *args: str, env: dict[str, str] | None = None
    ) -> tuple[int, str]:
        rig = lab.rig
        # `run` has no --dir: the session directory is the process's, so go to the repository first
        words = [
            *(f"{k}={v}" for k, v in (env or {}).items()),
            rig.opencode,
            "run",
            "--server",
            f"http://127.0.0.1:{rig.port}",
            "--agent",
            DEVOPS,
            *args,
            FORCE_PUSH,
        ]
        done = rig.run(
            ["sh", "-c", 'cd "$1" && shift && exec env "$@"', "sh", str(lab.ws), *words],
            timeout=120,
        )
        return done.returncode, done.stdout + done.stderr

    def test_run_without_auto_is_rejected_by_opencode_in_milliseconds(self, lab: BLab) -> None:
        lab.commit("a.txt")
        t0 = time.time()
        _rc, out = self.run_client(lab)
        assert "auto-rejecting" in out and time.time() - t0 < 60
        assert lab.remote_ref() == "" and not lab.pending()
        # OpenCode's auto-reject reaches the tool as a rejection that carries a message
        lab.wait_for(lambda: decisions(lab) == ["corrected"])

    def test_run_with_auto_answers_in_milliseconds_and_the_dwell_floor_refuses_before_git(
        self, lab: BLab
    ) -> None:
        lab.commit("a.txt")
        _rc, out = self.run_client(lab, "--auto")
        assert "E-B-DWELL" in out and "looks like client auto-accept" in out
        assert lab.remote_ref() == "" and decisions(lab) == ["dwell"]

    def test_the_headless_profile_denies_it_with_standalone_but_not_through_a_running_server(
        self, lab: BLab
    ) -> None:
        profile = lab.carter_dir / "opencode-headless.json"
        assert profile.is_file()
        lab.commit("a.txt")
        rig = lab.rig
        done = rig.run(
            [
                "sh",
                "-c",
                'cd "$1" && shift && exec env "$@"',
                "sh",
                str(lab.ws),
                f"OPENCODE_CONFIG={profile}",
                rig.opencode,
                "run",
                "--standalone",
                "--auto",
                "--agent",
                DEVOPS,
                FORCE_PUSH,
            ],
            timeout=180,
        )
        assert 'No tool named "carter_push"' in done.stdout + done.stderr
        assert lab.remote_ref() == "" and lab.audit() == []
        # the same profile in a client's environment changes nothing in the running server
        _rc, out = self.run_client(lab, "--auto", env={"OPENCODE_CONFIG": str(profile)})
        assert "No tool named" not in out and "E-B-DWELL" in out

    def test_a_profile_entry_for_the_file_defined_devops_appends_it_does_not_replace(
        self, lab: BLab
    ) -> None:
        """Freeze B8: if the profile replaced devops's permissions, the renderer would have to write
        the full list. The service reads OPENCODE_CONFIG only for the run that starts it."""
        rig = lab.rig

        def devops_rules(env: list[str]) -> list[dict[str, str]]:
            rig.stop_service()
            time.sleep(1)
            done = rig.run(
                [*(["env", *env] if env else []), rig.opencode, "debug", "agents"], timeout=120
            )
            for _ in range(5):
                if done.stdout.strip() not in ("", "[]"):
                    break
                time.sleep(2)
                done = rig.run(
                    [*(["env", *env] if env else []), rig.opencode, "debug", "agents"], timeout=120
                )
            agents = {a["id"]: a for a in json.loads(done.stdout)}
            return agents[DEVOPS]["permissions"]

        base = devops_rules([])
        profiled = devops_rules([f"OPENCODE_CONFIG={lab.carter_dir / 'opencode-headless.json'}"])
        rig.stop_service()
        deny = [{"action": a, "resource": "*", "effect": "deny"} for a in ("carter_push",)]
        assert [r for r in base if r in deny] == [], "devops itself has no deny rule for B"
        assert profiled[-len(deny) - 1 :][:-1] == deny or all(d in profiled for d in deny)
        assert len(profiled) > len(deny), "devops lost its own rules"
        assert all(r in profiled for r in base), "the profile replaced devops's permissions"


class TestTimeoutAndAbort:
    def test_nobody_answers_in_time_the_request_is_withdrawn_and_a_late_yes_does_nothing(
        self, lab: BLab
    ) -> None:
        lab.set_timeout_ms(2500)  # the shipped CLI keeps 120 s; the lab's wrapper shortens it
        lab.commit("a.txt")
        sid = lab.session()
        before = lab.say(sid, FORCE_PUSH)
        ask = lab.wait_ask()
        text = lab.result(before, timeout=30)
        assert "E-B-TIMEOUT" in text or "No approval within 120 s" in text
        assert lab.pending() == [], "the tool withdrew its own request"
        with pytest.raises(Exception):  # noqa: B017,PT011 - the late reply finds nothing (HTTP 404)
            lab.reply(ask, "once", pause=0)
        assert lab.remote_ref() == "" and decisions(lab) == ["timeout"] and lab.counted(sid) == 1

    def test_interrupting_the_session_while_the_prompt_is_open_withdraws_it(
        self, lab: BLab
    ) -> None:
        lab.commit("a.txt")
        sid = lab.session()
        lab.say(sid, FORCE_PUSH)
        lab.wait_ask()
        lab.rig.api("POST", f"/api/session/{sid}/interrupt", {})
        lab.wait_for(lambda: not lab.pending())
        lab.wait_for(lambda: decisions(lab) == ["aborted"])
        assert lab.remote_ref() == "" and lab.counted(sid) == 1


class TestRefusals:
    """Each one is refused with its code before any prompt, and nothing reaches the remote."""

    def test_the_remote_default_branch_is_routed_to_a_plus(self, lab: BLab) -> None:
        lab.git("checkout", "-q", "main")
        lab.commit("a.txt")
        text = lab.refused_push()
        assert "E-B-DEFAULT" in text and "carter push" in text

    def test_an_unsigned_llm_commit_names_the_commit(self, lab: BLab) -> None:
        key = Path(lab.rig.base / "llm-key")
        subprocess.run(
            [str(lab.ssh.bindir / "ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
        )
        pub = " ".join(key.with_suffix(".pub").read_text().split()[:2])
        fingerprint = subprocess.run(
            [str(lab.ssh.bindir / "ssh-keygen"), "-l", "-f", str(key.with_suffix(".pub"))],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[1]
        write_config_toml(lab, key=(pub, fingerprint))
        sha = lab.commit("llm.txt", llm=True)
        text = lab.refused_push()
        assert "E-B-UNSIGNED" in text and sha[:12] in text

    @pytest.mark.parametrize(
        "config",
        [
            "[core]\n\tsshCommand = ssh -F /tmp/evil\n",
            '[url "ssh://evil.invalid/"]\n\tinsteadOf = git@github.com:\n',
            "[credential]\n\thelper = !echo x\n",
        ],
        ids=["sshCommand", "insteadOf", "credential-helper"],
    )
    def test_hostile_repo_config(self, lab: BLab, config: str) -> None:
        lab.commit("a.txt")
        with (lab.ws / ".git" / "config").open("a") as fh:
            fh.write(config)
        text = lab.refused_push()
        assert "E-B-REPOCFG" in text and "could run code with your credentials" in text

    def test_a_foreign_hook_file(self, lab: BLab) -> None:
        lab.commit("a.txt")
        hook = lab.ws / ".git" / "hooks" / "reference-transaction"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        assert "E-B-REPOCFG" in lab.refused_push()

    def test_match_exec_in_the_ssh_config_is_refused_before_ssh_g_ever_runs(
        self, lab: BLab
    ) -> None:
        lab.commit("a.txt")
        (lab.home / ".ssh").mkdir(exist_ok=True)
        (lab.home / ".ssh" / "config").write_text('Match exec "touch /tmp/never"\n')
        text = lab.refused_push()
        assert "E-B-REPOCFG" in text and "ssh config" in text
        assert not [c for c in lab.ssh.calls() if c["argv"][:1] == ["-G"]]

    def test_proxycommand_from_ssh_g(self, lab: BLab) -> None:
        lab.commit("a.txt")
        lab.ssh.set_ssh_g(
            (
                Path(__file__).resolve().parents[1]
                / "data"
                / "ssh_g"
                / "openssh-10.2-proxycommand.txt"
            ).read_text()
        )
        assert "E-B-REPOCFG" in lab.refused_push()

    def test_an_https_origin_is_routed_to_a_plus(self, lab: BLab) -> None:
        lab.commit("a.txt")
        lab.git("remote", "set-url", "origin", "https://github.com/o/r.git")
        text = lab.refused_push()
        assert "E-B-HTTPS" in text and "carter push" in text

    def test_a_non_fast_forward(self, lab: BLab) -> None:
        first = lab.commit("a.txt")
        lab.git("reset", "-q", "--hard", "HEAD~1")
        lab.commit("b.txt")
        lab.git("update-ref", "refs/remotes/origin/feat/x", first)
        assert "non-fast-forward" in lab.refused_push()

    def test_a_server_started_from_an_agent_shell_is_refused_not_scrubbed(self, lab: BLab) -> None:
        lab.commit("a.txt")
        lab.restart(AGENT="1")
        text = lab.refused_push()
        assert "E-B-POLLUTED" in text and "AGENT" in text

    def test_a_stale_agent_socket(self, lab: BLab) -> None:
        lab.commit("a.txt")
        lab.restart(SSH_AUTH_SOCK="/tmp/b-lab-gone/agent.sock")
        assert "E-B-NOAGENT" in lab.refused_push()

    def test_isolation_values_in_the_server_env_are_pollution(self, lab: BLab) -> None:
        lab.commit("a.txt")
        lab.restart(GIT_SSH_COMMAND="ssh -o IdentityAgent=none")
        text = lab.refused_push()
        assert "E-B-POLLUTED" in text and "IdentityAgent" not in text

    def test_the_server_password_reaches_neither_the_child_nor_the_audit(self, lab: BLab) -> None:
        lab.commit("a.txt")
        lab.push("once")
        secret = lab.rig.password
        everything = (lab.ssh.bindir / "ssh.calls").read_text() + json.dumps(lab.audit())
        assert secret not in everything
        assert not any(
            n.startswith(("OPENCODE", "CARTER", "GH_", "GITHUB"))
            for c in lab.ssh.calls()
            for n in c["env_names"]
        )


class TestSelfTestAndInstall:
    def test_the_tools_and_the_hook_exist_only_for_devops_in_the_model_requests(
        self, lab: BLab
    ) -> None:
        for agent, expected in ((DEVOPS, True), ("carter-engineer", False), ("build", False)):
            sid = lab.session(agent)
            before = len(lab.rig.results())
            lab.rig.prompt(sid, "hello")
            time.sleep(2.5)
            requests = [
                json.loads(x) for x in (lab.rig.logs / "requests.jsonl").read_text().splitlines()
            ]
            tools = next(r["tools"] for r in reversed(requests) if r["tools"])
            assert ("carter_push" in tools) is expected, (agent, tools)
            del before

    def test_install_wrote_schema_2_with_the_broker_keys_and_the_profile(self, lab: BLab) -> None:
        doc = json.loads((lab.carter_dir / "isolation.json").read_text())
        assert doc["schema_version"] == 2
        plugin = doc["plugin"]
        assert (
            plugin["b_enabled"] is True
            and plugin["b_caller"] == DEVOPS
            and plugin["b_git"].endswith("/git")
        )
        assert plugin["broker_args"] == ["-I", "-m", "carter.broker_cli"]
        profile = json.loads((lab.carter_dir / "opencode-headless.json").read_text())
        assert list(profile["agents"]) == [DEVOPS]
        state = json.loads((lab.carter_dir / "guard-state.json").read_text())
        assert state["consents"]["g2"]["rev"] == 3
        names = {Path(f["path"]).name for f in state["files"]}
        assert {"broker.ts", "opencode-headless.json", "isolation.json"} <= names

    def test_the_plugin_files_and_the_isolation_hash_match(self, lab: BLab) -> None:
        done = lab.rig.run(
            [
                sys.executable,
                "-c",
                "from carter.cli import main; import sys; sys.argv=['carter','guard','status']; main()",
            ],
            timeout=120,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "MISSING" not in done.stdout


class TestSelfTestFailed:
    def test_a_failed_self_test_removes_the_tools_and_refuses_a_call(
        self, rig_factory, opencode_bin
    ) -> None:  # type: ignore[no-untyped-def]
        breaker = (
            'import { Plugin } from "@opencode/plugin"\n'
            "export default Plugin.define({ id: 'zzbreak', setup(ctx: any) {\n"
            "  ctx.tool.hook('execute.before', (e: any) => { if (e.tool === 'shell') throw new Error('zz refuses shells') })\n"
            "} })\n"
        )
        lab = make_lab(rig_factory, opencode_bin, plugins={"zz": breaker})
        try:
            sid = lab.session("build")
            lab.say(
                sid, "RUN echo hi"
            )  # our hook arms the timer; the later plugin rejects: no create.before
            lab.wait_for(
                lambda: any(
                    json.loads(f.read_text()).get("state") == "failed"
                    for f in (lab.home / ".carter/run/plugin-status").glob("*.json")
                ),
                timeout=25,
            )
            time.sleep(1.5)
            devops = lab.session(DEVOPS)
            before = lab.say(devops, FORCE_PUSH)
            text = lab.result(before)
            assert "No tool named" in text or "not available" in text, text
            assert not lab.pending() and lab.remote_ref() == ""
        finally:
            close_lab(lab)


def test_the_hygiene_of_the_lab_itself() -> None:
    assert HUMAN_PAUSE > 0.5 and LLM_EMAIL.endswith("@users.noreply.github.com")
    assert run_git.__name__ == "run_git"


def snapshot(home: Path) -> dict[str, str]:
    """What the install may change in a HOME: the OpenCode config files (parsed, so formatting does
    not count), the global gitconfig and the names of what lives in ~/.carter (not its state)."""
    import hashlib

    out: dict[str, str] = {}
    config = home / ".config" / "opencode"
    for name in ("opencode.jsonc", "opencode.json"):
        path = config / name
        if path.is_file():
            out[name] = json.dumps(json.loads(path.read_text()), sort_keys=True)
    for name in (".gitconfig",):
        if (home / name).is_file():
            out[name] = hashlib.sha256((home / name).read_bytes()).hexdigest()
    carter = home / ".carter"
    skip = {"backups", "state", "run", "memories"}
    out["~/.carter"] = (
        ",".join(sorted(p.name for p in carter.iterdir() if p.name not in skip))
        if carter.is_dir()
        else ""
    )
    plugins = config / "plugins"
    out["plugins"] = (
        ",".join(sorted(str(p.relative_to(plugins)) for p in plugins.rglob("*") if p.is_file()))
        if plugins.is_dir()
        else ""
    )
    return out


class TestRehearsal:
    """Install with B consent, use it, turn it off, remove everything: the HOME is back (step 23)."""

    def test_install_use_reject_turn_b_off_and_remove_leave_the_home_as_it_was(
        self, rig_factory, opencode_bin
    ) -> None:  # type: ignore[no-untyped-def]
        import socket
        import tempfile

        from broker.fakes import install_fake_gh, install_fake_ssh
        from e2e.btools import LAUNCHER, WRAPPER, build_world
        from e2e.g2 import PYTHON

        sockdir = Path(tempfile.mkdtemp(prefix="b-reh-", dir="/tmp"))
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(sockdir / "agent.sock"))
        rig = rig_factory(
            opencode=opencode_bin, server_env_extra={"SSH_AUTH_SOCK": str(sockdir / "agent.sock")}
        )
        try:
            before = snapshot(rig.home)
            ssh, gh = install_fake_ssh(rig.base / "ssh-bin"), install_fake_gh(rig.base / "gh-bin")
            (ssh.bindir / "ssh-add").write_text("#!/bin/sh\nexit 1\n")
            (ssh.bindir / "ssh-add").chmod(0o755)
            wrapper = rig.base / "py-wrap"
            wrapper.write_text(WRAPPER.format(py=PYTHON, base=str(rig.base), home=str(rig.home)))
            wrapper.chmod(0o755)
            env = [
                "env",
                f"CARTER_E2E_GH={gh.gh}",
                f"CARTER_E2E_PY={wrapper}",
                PYTHON,
                "-c",
                LAUNCHER,
            ]

            # 1. a revision-2 install first (what an existing user has), then the explicit yes to revision 3
            done = rig.run([*env, "install", "--yes"], timeout=300)
            assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
            installed = json.loads((rig.home / ".carter" / "guard-state.json").read_text())
            assert installed["consents"]["g2"]["rev"] == 3
            import re

            for agent_file in (rig.home / ".config" / "opencode" / "agents").glob("carter-*.md"):
                agent_file.write_text(
                    re.sub(r"(?m)^model:.*$", "model: mock/mock-1", agent_file.read_text())
                )
            lab = BLab(rig, ssh, gh, sockdir, wrapper)
            build_world(rig, lab)
            write_config_toml(lab)
            rig.restart()
            assert snapshot(rig.home) != before

            # 2. devops: one approved push, one rejected
            lab.commit("a.txt")
            _sid, _ask, text = lab.push("once")
            assert "Pushed" in text and lab.remote_ref() == lab.head()
            lab.commit("b.txt")
            lab.push("reject")
            lab.wait_for(lambda: decisions(lab) == ["approved", "rejected"])
            assert lab.remote_ref() != lab.head()

            # 3. B off, the rest of g2 stays: the tools are gone after a restart
            done = rig.run([*env, "guard", "remove", "--yes", "--only", "broker"], timeout=300)
            assert done.returncode == 0, done.stdout + done.stderr
            rig.restart()
            lab.sessions.clear()
            assert "No tool named" in lab.refused_after_commit()
            plugin = json.loads((rig.home / ".carter" / "isolation.json").read_text())["plugin"]
            assert plugin["b_enabled"] is False

            # 4. everything out: the HOME is as it was
            done = rig.run([*env, "uninstall", "--yes"], timeout=300)
            assert done.returncode == 0, done.stdout + done.stderr
            after = snapshot(rig.home)
            after.pop("~/.carter")
            before.pop("~/.carter")
            assert after == before, {
                k: (before.get(k), after.get(k))
                for k in set(before) | set(after)
                if before.get(k) != after.get(k)
            }
            assert not (rig.home / ".carter" / "isolation.json").exists()
            assert not (rig.home / ".carter" / "opencode-headless.json").exists()
            assert (rig.home / ".carter" / "state" / "audit" / "b.jsonl").exists(), (
                "the audit is kept"
            )
        finally:
            listener.close()
            import shutil

            shutil.rmtree(sockdir, ignore_errors=True)
