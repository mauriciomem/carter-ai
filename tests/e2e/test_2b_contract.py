# ruff: noqa: E501
"""The slice-2b contract on a real OpenCode (plan 005 step 25; App A §5, 2b columns).

A real isolated OpenCode (own HOME, ports, mock model, loopback-only network namespace when the
host allows it), the REAL plugin, gate, ``identity env`` entry, hooks, shim and dedicated
ssh-agent, a throwaway LLM key with a passphrase, a loopback fake GitHub and a scratch repo.
Setup is the user's own sequence: ``guard install`` (g2 rev 2 + hooks), ``identity add`` (pty),
``identity unlock`` (pty). No user key, no real GitHub, no TUI. Opt-in: ``CARTER_E2E=1``;
``tests/e2e/run.sh`` runs it (2.1.4 required; 2.1.2 through ``CARTER_E2E_OPENCODE_ALT``).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from carter.identity import agent_proc
from carter.identity.errors import (
    E_SHIM_REFUSED,
    E_SIGN_AGENT_REFUSE,
    E_SIGN_HUMAN_FALLBACK,
    E_UNLOCK_OPENCODE,
)
from carter.identity.payload import fingerprint_of
from e2e.g2 import CARTER, LAUNCHER, PYTHON, bang, error_message, run_shell, status, wait_status
from e2e.harness import Rig
from gh_api import FakeGitHub, Reply
from ssh_rig import PASSPHRASE_PROMPT, KeyPair, pty_run

pytestmark = pytest.mark.e2e

LOGIN, UID = "llm-bot", 4242
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
HUMAN = "E2E Human <e2e-human@example.invalid>"
LLM = f"{LOGIN} <{EMAIL}>"
REFUSED = "Refused by the Carter command gate"
LOCKED_STRINGS = ("Couldn't find key in agent?", "Couldn't get agent socket?")


@dataclass
class Lab:
    rig: Rig
    key: KeyPair
    fake: FakeGitHub
    passphrase: str
    counter: int = 0

    # --- the user's own commands (pty or plain subprocess, the rig's HOME, no agent signals) ---
    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in self.rig.env().items() if k != "OPENCODE_SERVER_PASSWORD"}
        env.update({"GITHUB_API_URL": self.fake.url, "PYTHONPATH": "", **extra})
        return env

    def carter(self, *args: str, answers: tuple[str, ...] = (), timeout: float = 60):  # type: ignore[no-untyped-def]
        script = [(PASSPHRASE_PROMPT, a) for a in answers if a == self.passphrase]
        script += [(r"\[y/N\]:\s*$", a) for a in answers if a != self.passphrase]
        return pty_run(
            [sys.executable, "-c", LAUNCHER, *args],
            self.env(),
            script,
            scrub=[self.passphrase],
            cwd=str(self.rig.home),
            timeout=timeout,
        )

    def carter_plain(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", LAUNCHER, *args],
            env=self.env(),
            cwd=self.rig.home,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=90,
        )

    def wrapper(self) -> Path:
        """``~/bin/carter`` for the shells the model and the human use (the launcher stands in for
        the root-ownership check of ``false``, which a user namespace cannot pass)."""
        folder = self.rig.home / "bin"
        folder.mkdir(exist_ok=True)
        (folder / "launcher.py").write_text(LAUNCHER + "\n")
        path = folder / "carter"
        path.write_text(f'#!/bin/sh\nexec {PYTHON} {folder / "launcher.py"} "$@"\n')
        path.chmod(0o755)
        return path

    def unlock(self, *flags: str) -> None:
        done = self.carter("identity", "unlock", *flags, answers=(self.passphrase,))
        assert done.rc == 0 and "Unlocked the LLM signing key" in done.output, done.output

    def lock(self, *flags: str) -> None:
        done = self.carter_plain("identity", "lock", *flags)
        assert done.returncode == 0, done.stdout + done.stderr

    # --- what the model and the human do -------------------------------------------------------
    def script(self, body: str) -> Path:
        self.counter += 1
        path = self.rig.ws / f"s{self.counter}.sh"
        path.write_text(f"#!/bin/sh\ncd {self.rig.ws}\n{body}\n")
        return path

    def agent_commit(self, message: str) -> str:
        path = self.script(
            f"echo {message!r} >> f.txt\ngit add f.txt\ngit commit -q -m {message!r}\necho rc=$?"
        )
        return run_shell(self.rig, f"sh {path}")

    def human(self, body: str) -> str:
        return bang(self.rig, f"sh {self.script(body)}")

    def human_commit(self, message: str) -> str:
        return self.human(
            f"echo {message!r} >> f.txt\ngit add f.txt\ngit commit -q -m {message!r}\necho rc=$?"
        )

    def show(self, rev: str = "HEAD") -> str:
        """author|committer|%G?|%GF with the allowed-signers file the guards use."""
        allowed = self.rig.home / ".carter" / "hooks" / "allowed_signers"
        env = {"HOME": str(self.rig.home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "gpg.ssh.allowedSignersFile", "GIT_CONFIG_VALUE_0": str(allowed), "GIT_CONFIG_KEY_1": "gpg.ssh.program", "GIT_CONFIG_VALUE_1": str(self.rig.home / ".carter" / "bin" / "carter-ssh-sign")}  # fmt: skip
        return subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>|%cn <%ce>|%G?|%GF", rev],
            cwd=self.rig.ws,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def message(self) -> str:
        return subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=self.rig.ws,
            env={
                "HOME": str(self.rig.home),
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            },
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def count(self) -> int:
        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.rig.ws,
            env={
                "HOME": str(self.rig.home),
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            },
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return int(out.strip())

    def staged(self) -> str:
        return subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.rig.ws,
            env={
                "HOME": str(self.rig.home),
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            },
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def config(self) -> Path:
        return self.rig.home / ".carter" / "config.toml"

    def touch_config(self) -> None:
        now = time.time() + self.counter + 1  # a new mtime: the plugin asks the entry again
        os.utime(self.config(), (now, now))
        self.counter += 1


def register(fake: FakeGitHub, blob: str) -> None:
    items = [{"id": 1, "key": blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
    fake.on(
        "GET",
        f"/users/{LOGIN}",
        Reply(200, json.dumps({"login": LOGIN, "id": UID, "type": "User"})),
    )
    fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
    fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))


@pytest.fixture
def lab(rig_factory, opencode_bin, throwaway_key: Callable[..., KeyPair]) -> Iterator[Lab]:  # type: ignore[no-untyped-def]
    fake = FakeGitHub().start()
    rig = rig_factory(
        opencode=opencode_bin,
        server_env_extra={"SSH_AUTH_SOCK": "/tmp/fake-agent.sock", "GITHUB_TOKEN": "not-a-token"},
    )
    key = throwaway_key("ed25519", True)
    assert key.passphrase
    state = Lab(rig, key, fake, key.passphrase)
    register(fake, key.blob)
    # 1. install: g2 at revision 2 and the hooks at revision 2, the explicit form
    done = rig.run([*CARTER, "guard", "install", "--yes", "--only", "g2,hooks"], timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    rig.restart()
    # 2. identity add against the fake (dry run first), 3. unlock through a pty
    dry = state.carter(
        "identity",
        "add",
        "--login",
        LOGIN,
        "--ssh-public-key",
        str(key.pub_path),
        "--private-key",
        str(key.path),
        "--dry-run",
    )
    assert dry.rc == 0 and "Dry run: nothing was written." in dry.output, dry.output
    added = state.carter(
        "identity",
        "add",
        "--login",
        LOGIN,
        "--ssh-public-key",
        str(key.pub_path),
        "--private-key",
        str(key.path),
        answers=("y",),
    )
    assert added.rc == 0 and key.fingerprint in added.output, added.output
    state.unlock()
    # `carter update` needs a Carter workspace. `init` writes more than the folder it is given, so it
    # runs in a scratch HOME: the rig's OpenCode and the agent's repo must see none of it.
    (rig.base / "proj").mkdir()
    (rig.base / "scratch-home").mkdir()
    init = subprocess.run(
        [sys.executable, "-c", LAUNCHER, "init", str(rig.base / "proj"), "--no-git-state"],
        env={**state.env(), "HOME": str(rig.base / "scratch-home")},
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )  # fmt: skip
    assert init.returncode == 0, init.stdout + init.stderr
    state.wrapper()
    yield state
    state.carter_plain(
        "identity", "lock", "--all"
    )  # (a test may have removed the identity already)
    left = agent_proc.agents_under(rig.home / ".carter")
    for pid in left:
        agent_proc.stop_agent(pid)
    fake.stop()
    assert not left, "a test left its agent running (stopped by the fixture)"


class TestK1AndTheTiers:
    def test_an_agent_commit_is_k1_verified_good_with_the_trailer_and_a_quiet_post_commit(
        self, lab: Lab
    ) -> None:
        out = lab.agent_commit("signed by the llm")
        assert "rc=0" in out, out
        assert lab.show() == f"{HUMAN}|{LLM}|G|{fingerprint_of(lab.key.blob)}"
        assert (
            lab.message().count(f"Co-authored-by: {LOGIN} <{EMAIL}>") == 1
        )  # the hook added it once
        assert (
            "unsigned or not signed" not in out
            and not (lab.rig.home / ".carter" / "run" / "guard.log").exists()
        )
        flags = set(status(lab.rig)[0]["flags"])
        assert not {"sign-unavailable", "config-error"} & flags
        wait_status(lab.rig, "passed")

    def test_a_stale_mirror_is_rejected_then_a_cap_after_update_is_unsigned_human_human_then_k1_again(
        self, lab: Lab
    ) -> None:
        assert "rc=0" in lab.agent_commit("before the cap")
        config = lab.config()
        original = config.read_text()
        config.write_text(original + f'[workspaces."{lab.rig.ws}"]\nmax_tier = "t1"\n')
        before = lab.count()
        # the config says t1 but the guard's mirror still says t2: the hook rejects (stale mirror)
        stale = lab.agent_commit("stale mirror")
        assert "rc=0" not in stale and "carter update" in stale and lab.count() == before, stale
        assert "f.txt" in lab.staged()  # nothing lost
        upd = lab.carter_plain("update", str(lab.rig.base / "proj"), "--yes")
        assert upd.returncode == 0 and "Wrote the tier mirror" in upd.stdout, (
            upd.stdout + upd.stderr
        )
        capped = lab.agent_commit("capped")
        assert "rc=0" in capped, capped
        who = lab.show().split("|")
        assert (
            who[2] == "N" and who[0] == HUMAN and who[1] == HUMAN
        )  # unsigned, human author and committer
        assert lab.message().count("Co-authored-by:") == 1
        # remove the cap and update: K1 again
        config.write_text(original)
        assert lab.carter_plain("update", str(lab.rig.base / "proj"), "--yes").returncode == 0
        assert "rc=0" in lab.agent_commit("k1 again")
        assert lab.show().split("|")[2] == "G"

    def test_t1_and_t0_configs_give_unsigned_commits_and_the_signing_flags_fail(
        self, lab: Lab
    ) -> None:
        lab.lock("--all")
        config = lab.config()
        text = config.read_text()
        config.write_text(text.split("[identity.signing]")[0])  # T1: an account, no key
        lab.touch_config()
        hooks = lab.carter_plain(
            "update", str(lab.rig.base / "proj"), "--yes"
        )  # refresh the mirror for t1
        assert hooks.returncode == 0, hooks.stdout + hooks.stderr
        t1 = lab.agent_commit("at t1")
        assert "rc=0" in t1, t1
        assert lab.show().split("|")[2] == "N" and lab.message().count("Co-authored-by:") == 1
        before = lab.count()
        # a bare -S below T2 (inside a script, so the gate sees only `sh`): git itself must fail
        path = lab.script("echo x >> f.txt\ngit add f.txt\ngit commit -S -q -m nope\necho rc=$?")
        out = run_shell(lab.rig, f"sh {path}")
        assert "rc=0" not in out and "rc=" in out and lab.count() == before, out
        tag = lab.script("git tag -s t1 -m s\necho rc=$?")
        out = run_shell(lab.rig, f"sh {tag}")
        assert "rc=0" not in out and "rc=" in out, out
        assert (
            subprocess.run(
                ["git", "tag"],
                cwd=lab.rig.ws,
                capture_output=True,
                text=True,
                env={
                    "HOME": str(lab.rig.home),
                    "PATH": "/usr/bin:/bin",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                },
            ).stdout
            == ""
        )
        # t0: nothing configured
        config.write_text("schema = 2\n")
        lab.touch_config()
        assert lab.carter_plain("update", str(lab.rig.base / "proj"), "--yes").returncode == 0
        t0 = lab.agent_commit("at t0")
        assert "rc=0" in t0, t0
        assert lab.message().count("Assisted-by: Carter") == 1 and lab.show().split("|")[2] == "N"


class TestNeverDegrade:
    def failed(self, lab: Lab, message: str, *needles: str) -> str:
        before = lab.count()
        out = lab.agent_commit(message)
        assert "rc=0" not in out and lab.count() == before, out
        assert "f.txt" in lab.staged(), "the changes must stay staged"
        assert any(n in out for n in needles) or not needles, out
        return out

    def test_locked_expired_killed_and_wrong_state_all_fail_with_the_raw_strings_and_staged_changes(
        self, lab: Lab
    ) -> None:
        assert "rc=0" in lab.agent_commit("warm")
        # locked: `lock` stops the now-empty agent, so it is the no-agent string (E-SIGN-NOAGENT)
        lab.lock()
        self.failed(lab, "locked", *LOCKED_STRINGS)
        # TTL expired: the agent is alive and empty
        lab.unlock("--ttl", "3")
        assert "rc=0" in lab.agent_commit("inside the ttl")
        time.sleep(5)
        self.failed(lab, "expired", *LOCKED_STRINGS)
        # the agent killed hard: a stale socket is left behind
        lab.unlock()
        pids = agent_proc.agents_under(lab.rig.home / ".carter" / "run")
        assert pids
        for pid in pids:
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        self.failed(lab, "killed", *LOCKED_STRINGS, "Connection refused")
        lab.unlock()  # unlock replaces the stale socket
        assert "rc=0" in lab.agent_commit("recovered")
        # the human's own `!` commit is unaffected by every one of these
        lab.lock("--all")
        human = lab.human_commit("human while locked")
        assert "rc=0" in human, human
        assert lab.show().split("|")[2] == "N"

    def test_a_missing_shim_and_a_corrupt_config_block_instead_of_degrading(self, lab: Lab) -> None:
        shim = lab.rig.home / ".carter" / "bin" / "carter-ssh-sign"
        kept = shim.read_bytes()
        shim.unlink()
        lab.touch_config()
        self.failed(lab, "shim gone")
        assert "sign-unavailable" in status(lab.rig)[0]["flags"]
        shim.write_bytes(kept)
        shim.chmod(0o755)
        lab.touch_config()
        assert "rc=0" in lab.agent_commit("shim back")
        good = lab.config().read_text()
        lab.config().write_text("schema = 2\n[identity\nbroken")
        lab.touch_config()
        self.failed(lab, "config corrupt")
        assert "config-error" in status(lab.rig)[0]["flags"]
        human = lab.human_commit("human with a corrupt config")
        assert "rc=0" in human, human
        lab.config().write_text(good)
        lab.touch_config()
        assert "rc=0" in lab.agent_commit("config back")


class TestShimGateAndRefusals:
    def test_the_gate_rejects_a_foreign_key_and_the_shim_refuses_one_if_the_gate_were_bypassed(
        self, lab: Lab, throwaway_key: Callable[..., KeyPair]
    ) -> None:
        decoy = throwaway_key("ed25519")
        before = lab.count()
        path = lab.script(f"git -c user.signingkey={decoy.path} commit -S -m x\necho rc=$?")
        out = run_shell(lab.rig, f"sh {path}")
        direct = error_message(
            run_shell(lab.rig, f"git -c user.signingkey={decoy.path} commit -S -m x")
        )
        assert direct.startswith(REFUSED), direct  # the literal command is a gate rejection
        assert lab.count() == before and "rc=0" not in out
        # direct run of the real shim with another key: refused by the shim itself
        shim = lab.rig.home / ".carter" / "bin" / "carter-ssh-sign"
        done = subprocess.run(
            [
                str(shim),
                "-Y",
                "sign",
                "-n",
                "git",
                "-f",
                str(decoy.pub_path),
                str(lab.rig.ws / "f.txt"),
            ],
            env=lab.env(),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        assert done.returncode != 0 and E_SHIM_REFUSED in done.stderr

    def test_unlock_is_refused_for_the_agent_for_agent_variables_and_in_the_bang_shell(
        self, lab: Lab
    ) -> None:
        lab.lock("--all")
        gate = error_message(run_shell(lab.rig, "carter identity unlock"))
        assert gate.startswith(REFUSED)
        agent = subprocess.run(
            [sys.executable, "-c", LAUNCHER, "identity", "unlock"],
            env={**lab.env(), "AGENT": "1"},
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        assert agent.returncode == 1 and E_UNLOCK_OPENCODE in agent.stdout + agent.stderr
        # OpenCode sets OPENCODE_TERMINAL in every shell it spawns, the `!` shell included: that comes first
        wrapper = lab.wrapper()
        shown = lab.human(f"{wrapper} identity unlock 2>&1; echo rc=$?")
        assert E_UNLOCK_OPENCODE in shown and "rc=1" in shown, shown
        assert not agent_proc.agents_under(lab.rig.home / ".carter" / "run")  # nothing was started


class TestCarterCommit:
    def wrapper(self, lab: Lab) -> Path:
        return lab.wrapper()

    def test_from_a_human_shell_it_is_k1_and_with_the_key_locked_the_fallback_is_unsigned(
        self, lab: Lab
    ) -> None:
        carter = self.wrapper(lab)
        out = lab.human(
            f"echo a >> g.txt\ngit add g.txt\n{carter} commit -m 'human k1' 2>&1\necho rc=$?"
        )
        assert "rc=0" in out, out
        assert lab.show() == f"{HUMAN}|{LLM}|G|{fingerprint_of(lab.key.blob)}"
        lab.lock("--all")
        out = lab.human(
            f"echo b >> g.txt\ngit add g.txt\n{carter} commit -m 'human locked' 2>&1\necho rc=$?"
        )
        assert "rc=0" in out and E_SIGN_HUMAN_FALLBACK in out and "Unverified" in out, out
        shown = lab.show().split("|")
        assert (
            shown[2] == "N" and shown[0] == HUMAN and shown[1] == HUMAN
        )  # H/H unsigned, the human's key never used
        assert lab.message().count("Co-authored-by:") == 1

    def test_in_an_agent_shell_it_works_with_the_key_loaded_and_refuses_when_locked(
        self, lab: Lab
    ) -> None:
        carter = self.wrapper(lab)
        path = lab.script(
            f"echo c >> h.txt\ngit add h.txt\n{carter} commit -m 'agent carter commit' 2>&1\necho rc=$?"
        )
        ok = run_shell(lab.rig, f"sh {path}")
        assert "rc=0" in ok and lab.show().split("|")[2] == "G", ok
        lab.lock("--all")
        before = lab.count()
        path = lab.script(
            f"echo d >> h.txt\ngit add h.txt\n{carter} commit -m 'locked' 2>&1\necho rc=$?"
        )
        refused = run_shell(lab.rig, f"sh {path}")
        assert E_SIGN_AGENT_REFUSE in refused and "rc=0" not in refused and lab.count() == before, (
            refused
        )
        assert "h.txt" in lab.staged()


class TestRemove:
    def test_identity_remove_then_guard_remove_leave_a_working_unsigned_repo_and_no_agent(
        self, lab: Lab
    ) -> None:
        assert "rc=0" in lab.agent_commit("before removal")
        done = lab.carter_plain("identity", "remove", "--yes")
        assert done.returncode == 0 and "What stays" in done.stdout, done.stdout + done.stderr
        home = lab.rig.home
        assert not (home / ".carter" / "bin" / "carter-ssh-sign").exists()
        assert not agent_proc.agents_under(home / ".carter" / "run")
        gone = lab.rig.run([*CARTER, "guard", "remove", "--yes"], timeout=240)
        assert gone.returncode == 0, gone.stdout + gone.stderr
        assert (
            not (home / ".carter" / "gitconfig").exists()
            and not (home / ".carter" / "isolation.json").exists()
        )
        out = lab.human_commit("after removal")
        assert "rc=0" in out, out
        assert lab.show().split("|")[2] == "N"
