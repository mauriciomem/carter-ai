"""The dedicated agent core.

Paths and permission rules are unit-tested with fakes; the probe, unlock and lock run against real
``ssh-agent``/``ssh-add`` started under the ``/tmp/c2b-*`` base of the ``real_ssh_agent`` fixtures.
macOS-only path facts are computed here and flagged for the user session.
"""

# ruff: noqa: E501
from __future__ import annotations

import os
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from carter.identity import agent, agent_paths, agent_proc, agent_setup
from carter.identity.agent_probe import Probe, classify_path, probe
from carter.identity.errors import E_UNLOCK_PATH, IdentityError
from carter.identity.schema import Identity, IdentityConfig, Signing
from sentinels import passphrase as new_passphrase
from ssh_rig import PASSPHRASE_PROMPT, KeyPair, Rig, pty_run, real_ssh

BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"


class TestPaths:
    def test_linux_prefers_the_xdg_runtime_dir(self, tmp_path: Path) -> None:
        xdg = tmp_path / "run" / "user"
        xdg.mkdir(parents=True)
        got = agent_paths.socket_path(tmp_path, {"XDG_RUNTIME_DIR": str(xdg)}, platform="linux")
        assert got == xdg / "carter" / "agent.sock"

    @pytest.mark.parametrize(
        "env",
        [{}, {"XDG_RUNTIME_DIR": "relative/dir"}, {"XDG_RUNTIME_DIR": "/nonexistent/dir"}],
        ids=["unset", "relative", "missing"],
    )
    def test_linux_falls_back_to_the_carter_run_dir_never_tmp_or_tmpdir(
        self, tmp_path: Path, env: dict[str, str]
    ) -> None:
        got = agent_paths.socket_path(tmp_path, {**env, "TMPDIR": "/tmp/x"}, platform="linux")
        assert got == tmp_path / ".carter" / "run" / "agent.sock"

    def test_an_xdg_dir_owned_by_someone_else_is_not_used(self, tmp_path: Path) -> None:
        xdg = tmp_path / "x"
        xdg.mkdir()
        got = agent_paths.socket_path(
            tmp_path, {"XDG_RUNTIME_DIR": str(xdg)}, platform="linux", euid=os.geteuid() + 1
        )
        assert got == tmp_path / ".carter" / "run" / "agent.sock"

    def test_macos_uses_tmpdir_carter_uid(self, tmp_path: Path) -> None:
        tmp = tmp_path / "T"
        tmp.mkdir()
        got = agent_paths.socket_path(
            tmp_path, {"TMPDIR": str(tmp)}, platform="darwin", euid=os.geteuid()
        )
        assert got == tmp / f"carter-{os.geteuid()}" / "agent.sock"
        assert agent_paths.socket_path(tmp_path, {}, platform="darwin") == (
            tmp_path / ".carter" / "run" / "agent.sock"
        )

    def test_pidfile_and_lock_live_in_the_carter_run_dir_on_both_systems(
        self, tmp_path: Path
    ) -> None:
        assert agent.pidfile_path(tmp_path) == tmp_path / ".carter" / "run" / "agent.pid"
        assert agent.lock_path(tmp_path) == tmp_path / ".carter" / "run" / "unlock.lock"
        assert agent.SOCKET_LIMITS == {"darwin": 104, "linux": 108}

    def test_the_length_limits_per_platform_and_the_hint(self) -> None:
        mac_limit = Path("/" + "m" * 103)  # 104 bytes
        agent_paths.check_length(Path("/" + "m" * 102), "darwin")
        with pytest.raises(IdentityError) as err:
            agent_paths.check_length(mac_limit, "darwin")
        assert err.value.code == E_UNLOCK_PATH and "104" in err.value.detail
        agent_paths.check_length(Path("/" + "l" * 106), "linux")  # 107 bytes
        with pytest.raises(IdentityError) as err:
            agent_paths.check_length(Path("/" + "l" * 107), "linux")
        assert "108" in err.value.detail

    def test_the_typical_macos_tmpdir_fits_computed_here_run_on_a_mac_in_step_33(self) -> None:
        tmpdir = "/var/folders/ab/" + "x" * 30 + "/T/"  # 49 bytes with the slash
        path = Path(tmpdir) / "carter-501" / "agent.sock"
        assert len(os.fsencode(path)) == 70
        agent_paths.check_length(path, "darwin")

    def test_a_directory_is_created_0700_and_a_loose_one_is_repaired(self, tmp_path: Path) -> None:
        made = tmp_path / "a" / "b"
        agent_paths.ensure_private_dir(made)
        assert stat.S_IMODE(made.stat().st_mode) == 0o700
        loose = tmp_path / "loose"
        loose.mkdir(mode=0o755)
        loose.chmod(0o755)
        agent_paths.ensure_private_dir(loose)
        assert stat.S_IMODE(loose.stat().st_mode) == 0o700

    def test_a_symlinked_directory_a_file_and_a_foreign_owner_are_refused(
        self, tmp_path: Path
    ) -> None:
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "link").symlink_to(real)
        (tmp_path / "file").write_text("x")
        for bad in (tmp_path / "link", tmp_path / "file"):
            with pytest.raises(IdentityError) as err:
                agent_paths.ensure_private_dir(bad)
            assert err.value.code == E_UNLOCK_PATH
        with pytest.raises(IdentityError) as err:
            agent_paths.ensure_private_dir(real, euid=os.geteuid() + 1)
        assert "another user" in err.value.detail
        assert stat.S_IMODE(real.stat().st_mode) != 0o000  # nothing was changed

    def test_the_child_environment_is_built_from_scratch(self, tmp_path: Path) -> None:
        env = agent_paths.child_env(tmp_path, tmp_path / "s.sock", DISPLAY="should-not-appear")
        assert env["SSH_AUTH_SOCK"] == str(tmp_path / "s.sock")
        assert env["SSH_ASKPASS_REQUIRE"] == "never"
        assert "SSH_ASKPASS" not in env and "SSH_AGENT_PID" not in env
        assert set(env) <= {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "SSH_ASKPASS_REQUIRE",
            "SSH_AUTH_SOCK",
            "DISPLAY",
        }


class TestSetupHelpers:
    def cfg(self, **signing: str) -> IdentityConfig:
        return IdentityConfig(
            identity=Identity(login="l", id=1, email="1+l@users.noreply.github.com"),
            signing=Signing(public_key=BLOB + " c", fingerprint="SHA256:abc", **signing),
            state="current",
        )

    def test_from_config_a_key_file_setup(self, tmp_path: Path) -> None:
        s = agent_setup.setup_from_config(
            self.cfg(private_key_path="/k/id", ttl="2h"), tmp_path, {}
        )
        assert (s.blob, s.private_key, s.ttl, s.ssh_bin_dir) == (BLOB, "/k/id", "2h", "/usr/bin")
        assert s.managed_externally is False

    @pytest.mark.parametrize("extra", [{"agent_socket": "/s"}, {"program": "/p"}])
    def test_from_config_a_password_manager_setup_needs_no_private_key(
        self, tmp_path: Path, extra: dict[str, str]
    ) -> None:
        s = agent_setup.setup_from_config(self.cfg(**extra), tmp_path, {})
        assert s.managed_externally is True and s.private_key == ""

    def test_from_config_without_material_is_a_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            agent_setup.setup_from_config(self.cfg(), tmp_path, {})  # no private key path
        with pytest.raises(ValueError):
            agent_setup.setup_from_config(IdentityConfig(), tmp_path, {})

    @pytest.mark.parametrize("good", ["8h", "30m", "3600", "1d", "2W", "90s"])
    def test_ttl_accepts_what_ssh_add_accepts(self, good: str) -> None:
        assert agent.parse_ttl(good) == good

    def test_an_empty_ttl_means_no_lifetime(self) -> None:
        assert agent.parse_ttl("") == ""

    @pytest.mark.parametrize("bad", ["0", "-5", "8 h", "h", "1.5h", "forever", "8hh", "0h"])
    def test_ttl_rejects_the_rest(self, bad: str) -> None:
        with pytest.raises(ValueError):
            agent.parse_ttl(bad)

    def test_the_key_file_checks_use_stat_only(self, tmp_path: Path) -> None:
        good = tmp_path / "k"
        good.write_text("x")
        good.chmod(0o600)
        assert agent.check_key_file(str(good)) is None
        good.chmod(0o640)
        assert agent.check_key_file(str(good)) == "too-open"
        assert agent.check_key_file(str(tmp_path)) == "not-a-file"
        assert agent.check_key_file(str(tmp_path / "absent")) == "missing"


class TestSourceRules:
    def test_ssh_agent_dash_k_is_never_used(self) -> None:
        for name in ("agent", "agent_proc", "agent_probe", "agent_paths", "agent_setup"):
            text = (Path(agent.__file__).parent / f"{name}.py").read_text()
            assert '"-k"' not in text and "'-k'" not in text, name

    def test_nothing_in_the_library_opens_a_private_key(self) -> None:
        text = (Path(agent.__file__).parent / "agent_setup.py").read_text()
        assert "open(" not in text and "read_text" not in text and "read_bytes" not in text


# --- the real tools ------------------------------------------------------------------------------


@dataclass
class Ctx:
    rig: Rig
    setup: agent.Setup
    key: KeyPair
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)

    def runner(self, argv: list[str], env: dict[str, str]) -> int:
        """``run_with_terminal`` for tests: a PTY that types ``answers`` at passphrase prompts."""
        self.calls.append((argv, dict(env)))
        script = [(PASSPHRASE_PROMPT, a) for a in self.answers]
        done = pty_run(argv, env, script, scrub=self.answers)
        self.last_output = done.output
        return done.rc if isinstance(done.rc, int) else 255

    last_output: str = ""

    def with_ttl(self, ttl: str) -> agent.Setup:
        return agent.Setup(**{**self.setup.__dict__, "ttl": ttl})

    def pids(self) -> list[int]:
        return agent_proc.agents_under(self.setup.sock.parent)


@pytest.fixture
def ctx(rig: Rig, throwaway_key: Callable[..., KeyPair]) -> Iterator[Ctx]:
    key = throwaway_key("ed25519")
    home = rig.root / "home"
    sock_dir = rig.root / "sockdir"
    setup = agent.Setup(
        home=home,
        ssh_bin_dir="/usr/bin",
        ttl="8h",
        blob=key.blob,
        fingerprint=key.fingerprint,
        private_key=str(key.path),
        managed_externally=False,
        sock=sock_dir / "agent.sock",
    )
    state = Ctx(rig, setup, key)
    yield state
    for pid in agent_proc.agents_under(sock_dir):  # whatever a test left running
        agent_proc.stop_agent(pid)


def pidfile_pid(ctx: Ctx) -> int:
    return int(agent.pidfile_path(ctx.setup.home).read_text())


@real_ssh
class TestProbe:
    def test_none_bad_stale_empty_wrong_key_ok(
        self, rig: Rig, real_ssh_agent: Any, throwaway_key: Any
    ) -> None:
        sock = real_ssh_agent.sock
        key: KeyPair = throwaway_key("ed25519")
        other: KeyPair = throwaway_key("ed25519")
        assert probe(rig.root / "run" / "nothing.sock", "/usr/bin") == Probe("none")
        assert probe(sock, "/usr/bin", key.fingerprint) == Probe("empty")
        real_ssh_agent.add(other)
        assert probe(sock, "/usr/bin", key.fingerprint) == Probe("wrong-key")
        real_ssh_agent.add(key)
        assert probe(sock, "/usr/bin", key.fingerprint) == Probe("ok")
        assert probe(sock, "/usr/bin") == Probe("ok")  # no fingerprint: any key counts
        assert probe(sock, "/usr/bin", key.fingerprint).live
        real_ssh_agent.kill(hard=True)
        assert probe(sock, "/usr/bin", key.fingerprint).state == "stale"

    def test_something_that_is_not_our_socket_is_bad_and_never_probed(
        self, rig: Rig, real_ssh_agent: Any
    ) -> None:
        for name, make in (
            ("file", lambda p: p.write_text("x")),
            ("dir", lambda p: p.mkdir()),
            ("link", lambda p: p.symlink_to(real_ssh_agent.sock)),
        ):
            path = rig.root / "run" / name
            make(path)
            assert probe(path, "/usr/bin") == Probe("bad"), name
            assert classify_path(path) == "bad"

    def test_a_socket_of_another_owner_is_bad(self, real_ssh_agent: Any) -> None:
        assert classify_path(real_ssh_agent.sock, euid=os.geteuid() + 1) == "bad"

    def test_a_hung_agent_is_stale_after_the_timeout(self, real_ssh_agent: Any) -> None:
        os.kill(real_ssh_agent.pid, signal.SIGSTOP)
        try:
            start = time.monotonic()
            got = probe(real_ssh_agent.sock, "/usr/bin", timeout=0.6)
            assert got == Probe("stale", "timeout") and time.monotonic() - start < 3
        finally:
            os.kill(real_ssh_agent.pid, signal.SIGCONT)

    def test_it_reads_exit_codes_not_prose(self, real_ssh_agent: Any, tmp_path: Path) -> None:
        fake = tmp_path / "bin"
        fake.mkdir()
        (fake / "ssh-add").write_text("#!/bin/sh\necho 'The agent has no identities.'\nexit 0\n")
        (fake / "ssh-add").chmod(0o755)
        # prose that looks like "empty" but exit 0 and no fingerprint column: not empty
        assert probe(real_ssh_agent.sock, str(fake), "SHA256:x").state == "wrong-key"
        (fake / "ssh-add").write_text("#!/bin/sh\nexit 1\n")
        assert probe(real_ssh_agent.sock, str(fake)).state == "empty"
        (fake / "ssh-add").write_text("#!/bin/sh\nexit 2\n")
        assert probe(real_ssh_agent.sock, str(fake)).state == "stale"

    def test_it_runs_without_a_terminal_so_it_can_never_prompt(self, real_ssh_agent: Any) -> None:
        done = pty_run(
            ["/bin/sh", "-c", "exit 0"], {"PATH": "/usr/bin:/bin"}, []
        )  # a terminal exists in this process tree...
        assert done.rc == 0
        assert probe(real_ssh_agent.sock, "/usr/bin").state == "empty"  # ...the probe is detached


@real_ssh
class TestUnlock:
    def test_a_fresh_unlock_starts_the_agent_and_loads_the_key(self, ctx: Ctx) -> None:
        got = agent.unlock(ctx.setup, ctx.runner)
        assert got == agent.UnlockResult("unlocked", 0, True)
        sock = ctx.setup.sock
        assert stat.S_IMODE(sock.stat().st_mode) == 0o600
        assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700
        pidfile = agent.pidfile_path(ctx.setup.home)
        assert stat.S_IMODE(pidfile.stat().st_mode) == 0o600
        assert stat.S_IMODE(agent.lock_path(ctx.setup.home).stat().st_mode) == 0o600
        assert stat.S_IMODE(pidfile.parent.stat().st_mode) == 0o700
        assert agent_proc.verified_agent(pidfile, sock) == pidfile_pid(ctx)
        assert probe(sock, "/usr/bin", ctx.key.fingerprint).state == "ok"

    def test_no_ttl_means_no_lifetime_option(self, ctx: Ctx) -> None:
        agent.unlock(ctx.with_ttl(""), ctx.runner)
        ((argv, _env),) = ctx.calls
        assert argv == ["/usr/bin/ssh-add", str(ctx.key.path)]

    def test_ssh_add_gets_a_scrubbed_environment_and_the_ttl(self, ctx: Ctx) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        ((argv, env),) = ctx.calls
        assert argv == ["/usr/bin/ssh-add", "-t", "8h", str(ctx.key.path)]
        assert env["SSH_AUTH_SOCK"] == str(ctx.setup.sock) and env["SSH_ASKPASS_REQUIRE"] == "never"
        assert not {"DISPLAY", "SSH_ASKPASS", "SSH_AGENT_PID"} & set(env)

    def test_a_second_unlock_is_idempotent_and_does_not_prompt(self, ctx: Ctx) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        before = pidfile_pid(ctx)
        again = agent.unlock(ctx.setup, ctx.runner)
        assert again.status == "already-unlocked" and len(ctx.calls) == 1
        assert pidfile_pid(ctx) == before and len(ctx.pids()) == 1

    def test_extend_re_adds_the_key_and_replaces_the_lifetime(self, ctx: Ctx) -> None:
        agent.unlock(ctx.with_ttl("2"), ctx.runner)  # expires after 2 s
        assert agent.unlock(ctx.setup, ctx.runner, extend=True).status == "unlocked"  # 8h now
        assert len(ctx.calls) == 2
        time.sleep(3)
        assert probe(ctx.setup.sock, "/usr/bin", ctx.key.fingerprint).state == "ok"

    def test_the_key_really_expires_after_the_ttl_and_unlock_asks_again(self, ctx: Ctx) -> None:
        short = ctx.with_ttl("2")
        agent.unlock(short, ctx.runner)
        time.sleep(3)
        assert probe(ctx.setup.sock, "/usr/bin", ctx.key.fingerprint).state == "empty"
        assert agent.unlock(short, ctx.runner).status == "unlocked" and len(ctx.calls) == 2
        assert len(ctx.pids()) == 1  # the same agent was reused

    def test_a_stale_socket_after_a_crash_is_replaced(self, ctx: Ctx) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        old = pidfile_pid(ctx)
        os.kill(old, signal.SIGKILL)
        time.sleep(0.2)
        assert ctx.setup.sock.exists()
        assert agent.unlock(ctx.setup, ctx.runner).started_agent is True
        assert pidfile_pid(ctx) != old and not agent_proc.alive(old)
        assert probe(ctx.setup.sock, "/usr/bin", ctx.key.fingerprint).state == "ok"

    def test_an_orphan_whose_socket_vanished_is_stopped_through_the_verified_pidfile(
        self, ctx: Ctx
    ) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        orphan = pidfile_pid(ctx)
        ctx.setup.sock.unlink()  # e.g. a $TMPDIR purge: the agent lives on, unreachable
        assert agent_proc.alive(orphan)
        agent.unlock(ctx.setup, ctx.runner)
        assert not agent_proc.alive(orphan) and pidfile_pid(ctx) != orphan

    def test_a_hung_agent_is_stopped_with_term_then_kill_and_replaced(self, ctx: Ctx) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        hung = pidfile_pid(ctx)
        os.kill(hung, signal.SIGSTOP)
        got = agent.unlock(ctx.setup, ctx.runner)
        assert got.started_agent and not agent_proc.alive(hung)
        assert probe(ctx.setup.sock, "/usr/bin", ctx.key.fingerprint).state == "ok"

    def test_a_pidfile_naming_some_other_process_is_never_killed(self, ctx: Ctx) -> None:
        bystander = subprocess.Popen(["sleep", "30"])
        try:
            run = agent.run_dir(ctx.setup.home)
            agent_paths.ensure_private_dir(run)
            agent.pidfile_path(ctx.setup.home).write_text(f"{bystander.pid}\n")
            assert agent.unlock(ctx.setup, ctx.runner).status == "unlocked"
            assert bystander.poll() is None  # not ssh-agent, not on our socket: left alone
        finally:
            bystander.kill()
            bystander.wait()

    @pytest.mark.parametrize("kind", ["file", "link", "dir"])
    def test_a_path_that_is_not_our_socket_is_refused_and_kept(self, ctx: Ctx, kind: str) -> None:
        sock = ctx.setup.sock
        agent_paths.ensure_private_dir(sock.parent)
        if kind == "file":
            sock.write_text("precious")
        elif kind == "link":
            sock.symlink_to(ctx.rig.root / "keys")
        else:
            sock.mkdir()
        with pytest.raises(IdentityError) as err:
            agent.unlock(ctx.setup, ctx.runner)
        assert err.value.code == E_UNLOCK_PATH and not ctx.calls and not ctx.pids()
        assert os.path.lexists(sock) and (kind != "file" or sock.read_text() == "precious")

    def test_a_symlinked_socket_directory_is_refused(self, ctx: Ctx) -> None:
        real = ctx.rig.root / "elsewhere"
        real.mkdir(mode=0o700)
        ctx.setup.sock.parent.symlink_to(real)
        with pytest.raises(IdentityError) as err:
            agent.unlock(ctx.setup, ctx.runner)
        assert err.value.code == E_UNLOCK_PATH and not ctx.pids()

    def test_a_too_long_socket_path_is_refused_before_anything_starts(self, ctx: Ctx) -> None:
        long_setup = agent.Setup(
            **{**ctx.setup.__dict__, "sock": ctx.rig.root / ("d" * 120) / "agent.sock"}
        )
        with pytest.raises(IdentityError) as err:
            agent.unlock(long_setup, ctx.runner)
        assert (
            err.value.code == E_UNLOCK_PATH and str(agent_paths.socket_limit()) in err.value.detail
        )
        assert not (ctx.rig.root / ("d" * 120)).exists()

    def test_two_concurrent_unlocks_make_one_agent_and_load_one_key(self, ctx: Ctx) -> None:
        results: list[Any] = []

        def go() -> None:
            try:
                results.append(agent.unlock(ctx.setup, ctx.runner))
            except Exception as exc:  # pragma: no cover - reported below
                results.append(exc)

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert sorted(r.status for r in results) == ["already-unlocked", "unlocked"], results
        assert len(ctx.pids()) == 1 and len(ctx.calls) == 1
        listed = ctx.rig.run("ssh-add", "-l", sock=ctx.setup.sock)
        assert listed.stdout.count("SHA256:") == 1

    def test_a_failed_add_does_not_leave_an_idle_agent_we_started(self, ctx: Ctx) -> None:
        got = agent.unlock(ctx.setup, lambda argv, env: 1)
        assert got.status == "failed" and got.returncode == 1 and got.started_agent
        assert not ctx.pids() and not ctx.setup.sock.exists()
        assert not agent.pidfile_path(ctx.setup.home).exists()


@real_ssh
class TestPassphraseKey:
    def test_d54_the_exit_code_alone_tells_a_passphrase_key_from_a_plain_one(
        self, ctx: Ctx, throwaway_key: Any
    ) -> None:
        assert agent.no_passphrase(ctx.setup) is True
        locked: KeyPair = throwaway_key("ed25519", True)
        assert (
            agent.no_passphrase(
                agent.Setup(**{**ctx.setup.__dict__, "private_key": str(locked.path)})
            )
            is False
        )
        missing = agent.Setup(**{**ctx.setup.__dict__, "private_key": str(ctx.rig.root / "nope")})
        assert agent.no_passphrase(missing) is False

    def test_the_passphrase_goes_from_the_terminal_to_ssh_add_and_nowhere_else(
        self, ctx: Ctx, throwaway_key: Any
    ) -> None:
        locked: KeyPair = throwaway_key("ed25519", True)
        assert locked.passphrase
        ctx.answers = ["wrong-" + new_passphrase("W"), locked.passphrase]
        setup = agent.Setup(
            **{
                **ctx.setup.__dict__,
                "private_key": str(locked.path),
                "fingerprint": locked.fingerprint,
            }
        )
        result = agent.unlock(setup, ctx.runner)
        assert result.status == "unlocked"
        assert "Bad passphrase, try again" in ctx.last_output  # ssh-add's own re-prompt, unwrapped
        secret = locked.passphrase
        ((argv, env),) = ctx.calls
        assert secret not in " ".join(argv) and secret not in "".join(env.values())
        assert secret not in repr(result) and secret not in ctx.last_output
        for path in (agent.pidfile_path(setup.home), agent.lock_path(setup.home)):
            assert secret not in path.read_text()
        ps = " ".join(command for _, command in agent_proc.user_processes())
        assert secret not in ps

    def test_a_wrong_passphrase_that_ends_the_prompt_fails_and_leaves_no_agent(
        self, ctx: Ctx, throwaway_key: Any
    ) -> None:
        locked: KeyPair = throwaway_key("ed25519", True)
        ctx.answers = ["nope", ""]  # a wrong answer, then an empty line ends ssh-add (rc 1)
        setup = agent.Setup(**{**ctx.setup.__dict__, "private_key": str(locked.path)})
        got = agent.unlock(setup, ctx.runner)
        assert got.status == "failed" and got.returncode == 1 and not ctx.pids()


@real_ssh
class TestLock:
    def test_lock_removes_the_key_and_stops_the_empty_agent(self, ctx: Ctx) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        pid = pidfile_pid(ctx)
        got = agent.lock(ctx.setup)
        assert got == agent.LockResult("locked", True, 0)
        assert not agent_proc.alive(pid) and not ctx.setup.sock.exists()
        assert not agent.pidfile_path(ctx.setup.home).exists()

    def test_lock_when_nothing_is_there_is_a_quiet_success(self, ctx: Ctx) -> None:
        assert agent.lock(ctx.setup) == agent.LockResult("already-locked", False, 0)
        agent.unlock(ctx.setup, ctx.runner)
        agent.lock(ctx.setup)
        assert agent.lock(ctx.setup).status == "already-locked"

    def test_lock_on_an_agent_that_does_not_hold_the_key_is_already_locked(
        self, ctx: Ctx, throwaway_key: Any
    ) -> None:
        sock, _ = ctx.rig.start_agent("dedicated")
        decoy: KeyPair = throwaway_key("ed25519")
        ctx.rig.run("ssh-add", str(decoy.path), sock=sock)
        setup = agent.Setup(**{**ctx.setup.__dict__, "sock": sock})
        got = agent.lock(setup)
        assert got.status == "already-locked" and got.agent_stopped is False  # "refused" = absent

    def test_lock_removes_only_the_configured_key_and_keeps_the_agent_for_the_rest(
        self, ctx: Ctx, throwaway_key: Any
    ) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        decoy: KeyPair = throwaway_key("ed25519")
        assert ctx.rig.run("ssh-add", str(decoy.path), sock=ctx.setup.sock).returncode == 0
        got = agent.lock(ctx.setup)
        assert got.status == "locked" and got.agent_stopped is False
        listed = ctx.rig.run("ssh-add", "-l", sock=ctx.setup.sock).stdout
        assert decoy.fingerprint in listed and ctx.key.fingerprint not in listed
        assert len(ctx.pids()) == 1

    def test_lock_all_stops_the_agent_and_verified_orphans_naming_the_socket_dir(
        self, ctx: Ctx, throwaway_key: Any
    ) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        decoy: KeyPair = throwaway_key("ed25519")
        ctx.rig.run("ssh-add", str(decoy.path), sock=ctx.setup.sock)
        # an orphan from an earlier run: another agent under the same directory
        other = ctx.setup.sock.parent / "orphan.sock"
        started = ctx.rig.run("ssh-agent", "-a", str(other), "-s")
        orphan = int(started.stdout.split("SSH_AGENT_PID=")[1].split(";")[0])
        ctx.rig.pids.append(orphan)
        assert len(ctx.pids()) == 2
        got = agent.lock(ctx.setup, stop_all=True)
        assert got.agent_stopped is True and not ctx.pids()
        assert not agent_proc.alive(orphan)

    def test_lock_does_not_touch_an_agent_it_cannot_verify(self, ctx: Ctx) -> None:
        agent.unlock(ctx.setup, ctx.runner)
        real_pid = pidfile_pid(ctx)
        agent.pidfile_path(ctx.setup.home).write_text("1\n")  # not ours, not ssh-agent
        got = agent.lock(ctx.setup)
        assert got.status == "locked" and got.agent_stopped is False
        assert agent_proc.alive(real_pid)  # the empty agent stays; only a verified pid is stopped
        agent_proc.stop_agent(real_pid)

    def test_lock_refuses_nothing_when_the_socket_path_is_not_ours(self, ctx: Ctx) -> None:
        sock = ctx.setup.sock
        agent_paths.ensure_private_dir(sock.parent)
        sock.write_text("x")
        assert agent.lock(ctx.setup).status == "already-locked"
        assert sock.read_text() == "x"


class TestStopAgent:
    def test_an_unknown_pid_is_gone_and_a_stopped_process_is_continued_then_ended(self) -> None:
        assert agent_proc.stop_agent(2**22 + 12345) == "gone"
        child = subprocess.Popen(["sleep", "60"])
        os.kill(child.pid, signal.SIGSTOP)
        assert agent_proc.stop_agent(child.pid, wait=2.0) in ("term", "kill")
        child.wait(timeout=5)
        assert child.returncode is not None
