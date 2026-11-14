# ruff: noqa: E501
"""``carter-guard`` commit events: prepare-commit-msg, commit-msg, post-commit.

The script is run for real (``dash`` and ``bash --posix`` for the direct cases, git's own hook
runner for the commit cases) in a repository of the hermetic home. The tier comes from Carter's own
git file, read with ``--file``; the signing block is the one the plugin sends (``payload``).
Every reject check is in ``prepare-commit-msg``; ``commit-msg`` only checks the trailer;
``post-commit`` only warns and never fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from carter.guard import hooks, mirror_io
from carter.guard.state import GuardState, load_or_empty_readonly, save
from carter.identity import env as entry
from carter.identity import shim
from carter.identity.errors import registry
from carter.identity.payload import fingerprint_of, shim_path, to_git_env
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace
from carter.identity.writer import write_config
from carter.install.paths import guard_state_path
from ssh_rig import KeyPair, real_ssh

LOGIN, UID = "llm-bot", 4242
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
COAUTHOR = f"Co-authored-by: {LOGIN} <{EMAIL}>"
FAKE_BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
SHELLS = [
    pytest.param(["dash"], id="dash"),
    pytest.param(["bash", "--posix"], id="bash-posix"),
]
AGENT = {"CARTER_AGENT_SHELL": "1"}


@pytest.fixture(params=SHELLS)
def sh(request: pytest.FixtureRequest) -> list[str]:
    argv: list[str] = request.param
    if shutil.which(argv[0]) is None:
        pytest.skip(f"{argv[0]} is not installed")
    return [shutil.which(argv[0]) or argv[0], *argv[1:]]


@dataclass
class World:
    home: Path
    repo: Path
    key: KeyPair | None = None
    agent_sock: str = ""

    @property
    def script(self) -> Path:
        return hooks.script_path(None)

    @property
    def chome(self) -> Path:
        return self.home / ".carter"

    def configure(
        self, tier: str, *, caps: dict[str, Workspace] | None = None, role: str = "co-author"
    ) -> IdentityConfig:
        """Write config.toml, the mirror, the guard script and the shim for ``tier``."""
        signing = Signing()
        if tier == "t2":
            blob = self.key.blob if self.key else FAKE_BLOB
            fpr = self.key.fingerprint if self.key else fingerprint_of(FAKE_BLOB)
            signing = Signing(public_key=blob, fingerprint=fpr)
        ident = (
            Identity(role=role, login=LOGIN, id=UID, email=EMAIL, name=LOGIN)
            if tier != "t0"
            else Identity()
        )
        cfg = IdentityConfig(
            identity=ident, signing=signing, workspaces=caps or {}, state="current"
        )
        (self.chome / "run").mkdir(parents=True, exist_ok=True, mode=0o700)
        write_config(cfg, self.chome / "config.toml")
        state = GuardState()
        mirror_io.sync(None, state, cfg)
        hooks.install_script(None, state)
        if tier == "t2":
            data = shim.render(
                shim.ShimParams(
                    key=signing.public_key,
                    sock=self.agent_sock or str(self.chome / "run" / "agent.sock"),
                    false_path=shim.resolve_false(),
                    keygen="/usr/bin/ssh-keygen",
                    run_dir=str(self.chome / "run"),
                )
            )
            shim.write(shim_path(self.home), data)
            allowed = shim.allowed_signers_path(self.home)
            allowed.parent.mkdir(exist_ok=True, mode=0o700)
            allowed.write_text(f'{EMAIL} namespaces="git" {signing.public_key}\n')
            state.record_file(shim_path(self.home), data)
        save(state, guard_state_path(None))
        return cfg

    def install_repo_hooks(self, events: tuple[str, ...] = hooks.COMMIT_EVENTS) -> None:
        for event in events:
            path = self.repo / ".git" / "hooks" / event
            path.write_text(hooks.repo_hook_text(self.script, event))
            path.chmod(0o755)

    def env(
        self, *, block: bool = True, extra: dict[str, str] | None = None, author_llm: bool = False
    ) -> dict[str, str]:
        """An agent shell: the plugin's identity block on top of the hermetic environment.
        The author is the human's own git identity (role a) unless ``author_llm`` (role author: the
        plugin's block then carries ``GIT_AUTHOR_*`` of the LLM)."""
        out = {**os.environ, **AGENT}
        if author_llm:
            out |= {"GIT_AUTHOR_NAME": LOGIN, "GIT_AUTHOR_EMAIL": EMAIL}
        answer = entry.answer(str(self.repo), {}, str(self.chome / "config.toml"), self.home)
        if block and answer.get("signing"):
            out = to_git_env(out, answer["signing"]).env
        out.update(extra or {})
        return out

    def git(self, *args: str, env: dict[str, str] | None = None, check: bool = False):  # type: ignore[no-untyped-def]
        done = subprocess.run(
            ["git", *args], cwd=self.repo, env=env or self.env(), capture_output=True, text=True
        )
        if check:
            assert done.returncode == 0, done.stderr
        return done

    def message(self, rev: str = "HEAD") -> str:
        return self.git("log", "-1", "--format=%B", rev, env={**os.environ}).stdout

    def run_hook(
        self, sh: list[str], event: str, text: str, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        msg = self.repo / "MSG"
        msg.write_text(text)
        return subprocess.run(
            [*sh, str(self.script), event, str(msg)],
            cwd=self.repo, env=env, capture_output=True, text=True, timeout=30,
        )  # fmt: skip


@pytest.fixture
def world(tmp_path: Path) -> World:
    home = Path(os.environ["HOME"])
    repo = tmp_path / "repo"
    repo.mkdir()
    base = {**os.environ, "GIT_AUTHOR_NAME": "h", "GIT_AUTHOR_EMAIL": "h@e.invalid",
            "GIT_COMMITTER_NAME": "h", "GIT_COMMITTER_EMAIL": "h@e.invalid"}  # fmt: skip
    for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", *argv], cwd=repo, env=base, check=True, capture_output=True)
    return World(home, repo)


def with_config(env: dict[str, str], **entries: str) -> dict[str, str]:
    """``env`` plus ``GIT_CONFIG_*`` entries after the existing ones (what ``-c`` would add)."""
    out = dict(env)
    n = int(out.get("GIT_CONFIG_COUNT", "0"))
    for i, (key, value) in enumerate(entries.items()):
        out[f"GIT_CONFIG_KEY_{n + i}"] = key.replace("__", ".")
        out[f"GIT_CONFIG_VALUE_{n + i}"] = value
    out["GIT_CONFIG_COUNT"] = str(n + len(entries))
    return out


def trap_path(tmp: Path) -> tuple[str, Path]:
    """A PATH whose every command records itself: the human path must not touch it."""
    bin_dir = tmp / "trap"
    bin_dir.mkdir()
    log = tmp / "trap.log"
    for name in ("git", "date", "tr", "ssh-keygen", "cat", "sed", "grep"):
        (bin_dir / name).write_text(f'#!/bin/sh\necho {name} >> "{log}"\nexit 99\n')
        (bin_dir / name).chmod(0o755)
    return str(bin_dir), log


class TestHumanPath:
    @pytest.mark.parametrize("event", hooks.COMMIT_EVENTS)
    def test_a_human_commit_is_a_no_op_with_no_external_command(
        self, world: World, sh: list[str], event: str, tmp_path: Path
    ) -> None:
        world.configure("t2")
        path, log = trap_path(tmp_path)
        for env in ({}, {"CARTER_HUMAN_SHELL": "1"}, {"AGENT": "1", "CARTER_HUMAN_SHELL": "1"}):
            (world.repo / "MSG").write_text("x\n")
            done = subprocess.run(
                [*sh, str(world.script), event, str(world.repo / "MSG")],
                cwd=world.repo, env={"PATH": path, **env}, capture_output=True, text=True,
            )  # fmt: skip
            assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), env
        assert not log.exists()
        assert (world.repo / "MSG").read_text() == "x\n"

    def test_a_missing_or_broken_script_never_blocks_a_human_commit(
        self, world: World, tmp_path: Path
    ) -> None:
        world.configure("t2")
        world.install_repo_hooks()
        env = {k: v for k, v in os.environ.items() if k not in AGENT}
        env |= {"GIT_AUTHOR_NAME": "h", "GIT_AUTHOR_EMAIL": "h@e.invalid",
                "GIT_COMMITTER_NAME": "h", "GIT_COMMITTER_EMAIL": "h@e.invalid"}  # fmt: skip
        for how in ("missing", "broken"):
            if how == "missing":
                world.script.unlink()
            else:
                world.script.write_text("#!/bin/sh\nexit 7\n")
                world.script.chmod(0o755)
            done = world.git("commit", "-q", "--allow-empty", "-m", how, env=env)
            assert done.returncode == 0, done.stderr
            assert COAUTHOR not in world.message()

    @pytest.mark.parametrize("event", hooks.COMMIT_EVENTS)
    def test_a_missing_script_blocks_an_agent_commit_except_post_commit(
        self, world: World, event: str
    ) -> None:
        world.configure("t1")
        world.install_repo_hooks()
        world.script.unlink()
        done = world.git("commit", "-q", "--allow-empty", "-m", "x")
        if event == "post-commit":  # the other two block first; post-commit alone never does
            assert done.returncode == 1 and "agent commit blocked" in done.stderr
            for other in ("prepare-commit-msg", "commit-msg"):
                (world.repo / ".git" / "hooks" / other).unlink()
            assert world.git("commit", "-q", "--allow-empty", "-m", "y").returncode == 0
        else:
            assert done.returncode == 1 and "agent commit blocked" in done.stderr


class TestInputs:
    def test_the_tier_is_read_from_carters_file_only(self, world: World, sh: list[str]) -> None:
        world.configure("t1")
        env = with_config(world.env(), carter__tier="t2")  # -c / local values have no effect
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 0, done.stderr
        assert COAUTHOR in (world.repo / "MSG").read_text()
        world.git("config", "--local", "carter.tier", "t0")
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", world.env())
        assert done.returncode == 0 and COAUTHOR in (world.repo / "MSG").read_text()

    def test_a_missing_file_is_t0(self, world: World, sh: list[str]) -> None:
        world.configure("t0")
        assert not (world.chome / "gitconfig").exists()
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", world.env())
        assert done.returncode == 0
        assert (world.repo / "MSG").read_text().endswith("Assisted-by: Carter\n")

    def test_the_hook_command_passes_carters_file_not_the_users_global_config(
        self, world: World
    ) -> None:
        world.configure("t1")
        command = hooks.hook_command(world.script, "prepare-commit-msg")
        assert f"CARTER_GUARD_CONFIG={world.chome}/gitconfig " in command
        # a [carter] section appended to the user's global config cannot outvote the file
        glob = Path(os.environ["GIT_CONFIG_GLOBAL"])
        glob.write_text(glob.read_text() + "[carter]\n\ttier = t0\n")
        world.install_repo_hooks()
        assert world.git("commit", "-q", "--allow-empty", "-m", "x").returncode == 0
        assert COAUTHOR in world.message()


class TestT2Rejects:
    """Each reject names its code's message and exits 1 before any signing happens."""

    def reject(self, world: World, sh: list[str], env: dict[str, str], code: str) -> str:
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", env)
        assert done.returncode == 1 and done.stdout == "", done.stderr
        assert (world.repo / "MSG").read_text() == "msg\n"  # nothing added to a rejected message
        return done.stderr

    def test_no_identity_block_names_the_plugin_and_both_stale_directions(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        err = self.reject(world, sh, world.env(block=False), "E-GUARD-NOIDENT")
        entry_ = registry()["E-GUARD-NOIDENT"]
        assert entry_.message in err and entry_.remediation in err
        assert hooks.STALE_HINT in err and hooks.RESTART_HINT in err

    @pytest.mark.parametrize("missing", ["GIT_COMMITTER_EMAIL", "CARTER_IDENTITY"])
    def test_a_partial_block_is_no_block(self, world: World, sh: list[str], missing: str) -> None:
        world.configure("t2")
        env = world.env()
        del env[missing]
        assert registry()["E-GUARD-NOIDENT"].message in self.reject(
            world, sh, env, "E-GUARD-NOIDENT"
        )

    def test_a_stale_mirror_above_the_cap_rejects_with_the_update_hint(
        self, world: World, sh: list[str]
    ) -> None:
        """config.toml now says t1 (a cap was added) but the mirror still says t2 and the agent has
        no block: the reject points at `carter update`."""
        world.configure("t2")
        cfg = IdentityConfig(identity=Identity(login=LOGIN, id=UID, email=EMAIL), state="current")
        write_config(cfg, world.chome / "config.toml")
        err = self.reject(world, sh, world.env(), "E-GUARD-NOIDENT")
        assert "carter update" in err

    def test_a_stale_mirror_below_the_config_is_seen_as_t1_and_rejects_signing(
        self, world: World, sh: list[str]
    ) -> None:
        """config.toml is t2 (the plugin signs) but the mirror says t1: signing below T2."""
        world.configure("t2")
        env = world.env()
        t1 = IdentityConfig(identity=Identity(login=LOGIN, id=UID, email=EMAIL), state="current")
        state = load_or_empty_readonly(guard_state_path(None)).state
        mirror_io.sync(None, state, t1)
        err = self.reject(world, sh, env, "E-GUARD-NOSIGN")
        assert registry()["E-GUARD-NOSIGN"].message in err and "carter update" in err

    def test_a_committer_override_is_rejected_with_both_emails(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        env = world.env(extra={"GIT_COMMITTER_EMAIL": "evil@example.invalid"})
        err = self.reject(world, sh, env, "E-GUARD-COMMITTER")
        assert "committer is evil@example.invalid, expected " + EMAIL in err
        assert registry()["E-GUARD-COMMITTER"].remediation in err

    @pytest.mark.parametrize(
        ("override", "reason"),
        [
            ({"commit__gpgsign": "false"}, "commit.gpgsign is not true"),
            ({"gpg__format": "openpgp"}, "gpg.format is not ssh"),
            ({"user__signingkey": "/home/human/.ssh/id_ed25519"}, "user.signingkey is not a key:: literal"),
            ({"gpg__ssh__program": "/usr/bin/ssh-keygen"}, "gpg.ssh.program is not the Carter shim"),
        ],
    )  # fmt: skip
    def test_signing_overrides_are_rejected_each_with_its_own_reason(
        self, world: World, sh: list[str], override: dict[str, str], reason: str
    ) -> None:
        world.configure("t2")
        err = self.reject(world, sh, with_config(world.env(), **override), "E-GUARD-SIGNCFG")
        assert "E-GUARD-SIGNCFG" in err and reason in err
        assert registry()["E-GUARD-SIGNCFG"].remediation in err

    def test_a_clean_t2_block_passes_and_adds_the_trailer(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        done = world.run_hook(sh, "prepare-commit-msg", "msg\n", world.env())
        assert done.returncode == 0, done.stderr
        assert (world.repo / "MSG").read_text() == f"msg\n\n{COAUTHOR}\n"

    def test_a_cap_added_after_the_plugin_loaded_is_t1_and_signing_is_rejected(
        self, world: World, sh: list[str], tmp_path: Path
    ) -> None:
        world.configure("t2")
        env = world.env()  # the block the plugin sent before the cap existed
        capped = IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL),
            signing=Signing(public_key=FAKE_BLOB, fingerprint=fingerprint_of(FAKE_BLOB)),
            workspaces={str(tmp_path): Workspace(max_tier="t1")},
            state="current",
        )
        state = load_or_empty_readonly(guard_state_path(None)).state
        mirror_io.sync(None, state, capped)
        err = self.reject(world, sh, env, "E-GUARD-NOSIGN")
        assert "carter update" in err


class TestT0T1:
    @pytest.mark.parametrize("tier", ["t0", "t1"])
    def test_gpgsign_true_is_rejected_below_t2(
        self, world: World, sh: list[str], tier: str
    ) -> None:
        world.configure(tier)
        done = world.run_hook(
            sh, "prepare-commit-msg", "m\n", with_config(world.env(), commit__gpgsign="true")
        )
        assert done.returncode == 1 and registry()["E-GUARD-NOSIGN"].message in done.stderr

    def test_the_trailer_is_assisted_by_at_t0_and_co_authored_by_at_t1(
        self, world: World, sh: list[str]
    ) -> None:
        for tier, trailer in (("t0", "Assisted-by: Carter"), ("t1", COAUTHOR)):
            world.configure(tier)
            done = world.run_hook(sh, "prepare-commit-msg", "msg\n", world.env())
            assert done.returncode == 0, done.stderr
            assert (world.repo / "MSG").read_text() == f"msg\n\n{trailer}\n"

    def test_a_t1_login_comes_from_the_noreply_email(self, world: World, sh: list[str]) -> None:
        world.configure("t1")
        world.run_hook(sh, "prepare-commit-msg", "msg\n", world.env())
        assert (
            f"Co-authored-by: {LOGIN} <{UID}+{LOGIN}@users.noreply.github.com>"
            in (world.repo / "MSG").read_text()
        )


class TestCommitMsg:
    """commit-msg only checks the trailer."""

    def test_missing_trailer_is_rejected_with_the_registered_text(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t1")
        done = world.run_hook(sh, "commit-msg", "msg\n", world.env())
        assert done.returncode == 1 and "Co-authored-by trailer missing" in done.stderr
        assert registry()["E-GUARD-TRAILER"].remediation in done.stderr

    def test_t0_wants_assisted_by(self, world: World, sh: list[str]) -> None:
        world.configure("t0")
        assert world.run_hook(sh, "commit-msg", "msg\n", world.env()).returncode == 1
        done = world.run_hook(sh, "commit-msg", "msg\n\nAssisted-by: Carter\n", world.env())
        assert done.returncode == 0, done.stderr

    def test_the_key_is_compared_case_insensitively(self, world: World, sh: list[str]) -> None:
        world.configure("t1")
        done = world.run_hook(
            sh, "commit-msg", f"msg\n\nco-authored-by: {LOGIN} <{EMAIL}>\n", world.env()
        )
        assert done.returncode == 0, done.stderr

    def test_it_does_not_run_the_identity_checks(self, world: World, sh: list[str]) -> None:
        world.configure("t2")
        text = f"msg\n\n{COAUTHOR}\n"
        done = world.run_hook(sh, "commit-msg", text, world.env(block=False))
        assert done.returncode == 0, done.stderr  # NOIDENT is prepare-commit-msg's


def count(text: str, needle: str = "Co-authored-by:") -> int:
    return text.count(needle)


class TestTrailerIdempotence:
    """Exactly one trailer however the message arrives (hook runs for -m, -F, merge, squash, amend)."""

    @pytest.fixture(autouse=True)
    def ready(self, world: World) -> None:
        world.configure("t1")
        world.install_repo_hooks()

    def test_dash_m(self, world: World) -> None:
        assert world.git("commit", "-q", "--allow-empty", "-m", "a").returncode == 0
        assert count(world.message()) == 1

    def test_dash_f(self, world: World) -> None:
        (world.repo / "m.txt").write_text("from a file\n")
        assert world.git("commit", "-q", "--allow-empty", "-F", "m.txt").returncode == 0
        assert count(world.message()) == 1

    def test_amend_does_not_duplicate(self, world: World) -> None:
        world.git("commit", "-q", "--allow-empty", "-m", "a")
        for _ in range(2):
            assert world.git("commit", "-q", "--amend", "--allow-empty", "-m", "b").returncode == 0
        assert count(world.message()) == 1
        assert world.git("commit", "-q", "--amend", "--allow-empty", "--no-edit").returncode == 0
        assert count(world.message()) == 1

    def test_a_message_that_already_has_the_trailer(self, world: World) -> None:
        text = f"a\n\n{COAUTHOR}\n"
        assert world.git("commit", "-q", "--allow-empty", "-m", text).returncode == 0
        assert count(world.message()) == 1

    def test_merge_and_squash(self, world: World) -> None:
        world.git("checkout", "-q", "-b", "side")
        (world.repo / "s.txt").write_text("s\n")
        world.git("add", "s.txt")
        world.git("commit", "-q", "-m", "side")
        world.git("checkout", "-q", "-")
        (world.repo / "m.txt").write_text("m\n")
        world.git("add", "m.txt")
        world.git("commit", "-q", "-m", "main")
        merged = world.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        assert merged.returncode == 0, merged.stderr
        assert count(world.message()) == 1
        world.git("reset", "-q", "--hard", "HEAD~1")
        assert world.git("merge", "-q", "--squash", "side").returncode == 0
        done = world.git("commit", "-q", "-m", "squashed")
        assert done.returncode == 0, done.stderr
        assert count(world.message()) == 1

    def test_no_verify_does_not_skip_prepare_commit_msg(self, world: World) -> None:
        """git skips only pre-commit and commit-msg for `--no-verify`: every reject check and the
        trailer live in prepare-commit-msg, so the flag buys an agent nothing."""
        done = world.git("commit", "-q", "--allow-empty", "--no-verify", "-m", "nv")
        assert done.returncode == 0
        assert count(world.message()) == 1

    def test_the_message_body_is_untouched(self, world: World) -> None:
        world.git("commit", "-q", "--allow-empty", "-m", "subject\n\nbody line one\nbody line two")
        assert world.message().startswith("subject\n\nbody line one\nbody line two\n\n" + COAUTHOR)


def guard_log(world: World) -> Path:
    """Where the hook records an unsigned commit: with the other audit files."""
    return world.chome / "state" / "audit" / "guard.log"


class TestPostCommit:
    """Warn only: never fails the commit, never undoes it, leaves a line in state/audit/guard.log."""

    def warn(
        self, world: World, sh: list[str], env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*sh, str(world.script), "post-commit"],
            cwd=world.repo, env=env, capture_output=True, text=True,
        )  # fmt: skip

    def test_t1_unsigned_commit_is_silent(self, world: World, sh: list[str]) -> None:
        world.configure("t1")
        done = self.warn(world, sh, world.env())
        assert (done.returncode, done.stderr) == (0, "")
        assert not guard_log(world).exists()

    def test_t2_commit_without_the_llm_signature_warns_and_logs(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        done = self.warn(world, sh, world.env())
        head = world.git("rev-parse", "--short", "HEAD").stdout.strip()
        assert done.returncode == 0
        assert f"HEAD {head} is unsigned or not signed by the LLM key" in done.stderr
        assert registry()["E-GUARD-UNSIGNED"].remediation in done.stderr
        log = guard_log(world).read_text()
        assert "E-GUARD-UNSIGNED" in log and head in log and log[-1] == "\n"
        assert oct(guard_log(world).stat().st_mode & 0o777) == "0o600"

    def test_the_log_directory_is_created_private_and_the_old_location_is_not_used(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        assert not (world.chome / "state").exists()
        self.warn(world, sh, world.env())
        for directory in (world.chome / "state", guard_log(world).parent):
            assert oct(directory.stat().st_mode & 0o777) == "0o700"
        assert not (world.chome / "run" / "guard.log").exists()

    def test_a_second_warning_appends(self, world: World, sh: list[str]) -> None:
        world.configure("t2")
        for _ in range(2):
            self.warn(world, sh, world.env())
        assert len(guard_log(world).read_text().splitlines()) == 2

    def test_an_unwritable_log_directory_still_warns_and_never_fails(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        (world.chome / "state").write_text("a file where the directory should be")
        done = self.warn(world, sh, world.env())
        assert done.returncode == 0 and "unsigned" in done.stderr
        assert not guard_log(world).exists()

    def test_a_human_commit_is_silent(self, world: World, sh: list[str]) -> None:
        world.configure("t2")
        done = self.warn(world, sh, {k: v for k, v in os.environ.items() if k not in AGENT})
        assert (done.returncode, done.stderr) == (0, "")


@pytest.fixture
def signing_world(world: World, throwaway_key: Callable[..., KeyPair], real_ssh_agent) -> World:  # type: ignore[no-untyped-def]
    key = throwaway_key("ed25519")
    assert real_ssh_agent.add(key) == 0
    world.key = key
    world.agent_sock = str(real_ssh_agent.sock)
    world.configure("t2")
    world.install_repo_hooks()
    return world


@real_ssh
class TestRealSigning:
    """T2 end to end: the real shim, a throwaway agent and git's own hook runner."""

    def signature(self, world: World, rev: str = "HEAD") -> str:
        allowed = shim.allowed_signers_path(world.home)
        done = world.git(
            "-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={allowed}",
            "-c", f"gpg.ssh.program={shim_path(world.home)}",
            "log", "-1", "--format=%G?|%GF", rev, env={**os.environ},
        )  # fmt: skip
        return done.stdout.strip()

    def test_a_clean_agent_commit_is_signed_trailed_and_quiet(self, signing_world: World) -> None:
        w = signing_world
        done = w.git("commit", "-q", "--allow-empty", "-m", "signed")
        assert done.returncode == 0, done.stderr
        assert done.stderr == ""
        assert count(w.message()) == 1
        assert self.signature(w) == f"G|{w.key.fingerprint}"  # type: ignore[union-attr]
        assert not guard_log(w).exists()

    def test_every_commit_shape_still_ends_signed_with_one_trailer(
        self, signing_world: World
    ) -> None:
        w = signing_world
        w.git("commit", "-q", "--allow-empty", "-m", "one")
        assert w.git("commit", "-q", "--amend", "--allow-empty", "-m", "two").returncode == 0
        assert self.signature(w).startswith("G|") and count(w.message()) == 1

    def test_no_gpg_sign_is_a_rejected_override_at_t2(self, signing_world: World) -> None:
        w = signing_world
        done = w.git("commit", "-q", "--allow-empty", "-m", "x", "--no-gpg-sign")
        # `--no-gpg-sign` does not change config: prepare-commit-msg passes, the commit is unsigned,
        # and post-commit (not --no-verify-able) warns and logs. It never undoes the commit.
        assert done.returncode == 0
        assert "unsigned or not signed by the LLM key" in done.stderr
        assert "E-GUARD-UNSIGNED" in guard_log(w).read_text()
        assert self.signature(w).startswith("N|")

    def test_no_verify_changes_nothing_about_the_checks_or_the_warning(
        self, signing_world: World
    ) -> None:
        w = signing_world
        done = w.git("commit", "-q", "--allow-empty", "--no-verify", "--no-gpg-sign", "-m", "nv")
        assert done.returncode == 0
        assert count(w.message()) == 1  # prepare-commit-msg still ran
        assert "unsigned or not signed" in done.stderr  # and so did post-commit
        env = w.env(extra={"GIT_COMMITTER_EMAIL": "evil@example.invalid"})
        again = w.git("commit", "-q", "--allow-empty", "--no-verify", "-m", "nv2", env=env)
        assert again.returncode == 1 and "committer is evil@example.invalid" in again.stderr

    def test_an_agent_cannot_commit_as_someone_else(self, signing_world: World) -> None:
        w = signing_world
        env = w.env(extra={"GIT_COMMITTER_EMAIL": "evil@example.invalid"})
        done = w.git("commit", "-q", "--allow-empty", "-m", "x", env=env)
        assert done.returncode == 1 and "committer is evil@example.invalid" in done.stderr
        assert w.git("rev-list", "--count", "HEAD", env={**os.environ}).stdout.strip() == "1"

    def test_a_dash_capital_s_below_t2_slips_past_config_and_post_commit_warns(
        self, world: World, throwaway_key: Callable[..., KeyPair], real_ssh_keygen: None
    ) -> None:
        key = throwaway_key("ed25519")
        world.configure("t1")
        world.install_repo_hooks()
        done = world.git(
            "-c", "gpg.format=ssh", "-c", f"user.signingkey={key.path}",
            "commit", "-q", "--allow-empty", "-S", "-m", "x",
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        assert "unsigned or not signed" in done.stderr
        assert "E-GUARD-UNSIGNED" in guard_log(world).read_text()


class TestHostileInput:
    """Step-29 review: nothing in a commit message, a branch name or a path reaches a shell."""

    NASTY = "x $(touch PWNED) `touch PWNED2` ; touch PWNED3 \"'\\\\ %s %d ${HOME} \u00e9\n\nbody $(touch PWNED4)"

    def test_a_message_full_of_shell_syntax_is_kept_verbatim_and_runs_nothing(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t2")
        done = world.run_hook(sh, "prepare-commit-msg", self.NASTY + "\n", world.env())
        assert done.returncode == 0, done.stderr
        text = (world.repo / "MSG").read_text()
        assert text.startswith(self.NASTY) and text.endswith(f"{COAUTHOR}\n")
        assert not [p for p in world.repo.iterdir() if p.name.startswith("PWNED")]
        again = world.run_hook(sh, "commit-msg", text, world.env())
        assert again.returncode == 0, again.stderr

    def test_a_body_line_that_looks_like_the_trailer_does_not_satisfy_commit_msg(
        self, world: World, sh: list[str]
    ) -> None:
        world.configure("t1")
        fake = "subject\n\nCo-authored-by: x <x@y>\n\nmore text after it\n"
        # the trailer is not in the last paragraph, so it is not a trailer: rejected
        assert world.run_hook(sh, "commit-msg", fake, world.env()).returncode == 1

    def test_a_hostile_branch_name_and_pathname_do_not_matter(self, world: World) -> None:
        world.configure("t1")
        world.install_repo_hooks()
        weird = world.repo / "a b'c;d$(touch PWNED5).txt"
        weird.write_text("x\n")
        world.git("add", "-A")
        world.git("checkout", "-q", "-b", "feat/x;touch-PWNED6")
        done = world.git("commit", "-q", "-m", "ok")
        assert done.returncode == 0, done.stderr
        assert not [p for p in world.repo.iterdir() if p.name.startswith("PWNED")]
        assert COAUTHOR in world.message()

    def test_post_commit_ignores_a_caller_supplied_config_variable_in_the_real_hook(
        self, world: World
    ) -> None:
        """The hook command sets CARTER_GUARD_CONFIG inline, so a value in the caller's environment
        cannot make the script read another file as the hook tier."""
        world.configure("t2")
        world.install_repo_hooks()
        liar = world.repo.parent / "liar-gitconfig"
        liar.write_text("[carter]\n\ttier = t0\n")
        env = world.env(block=False, extra={"CARTER_GUARD_CONFIG": str(liar)})
        done = world.git("commit", "-q", "--allow-empty", "-m", "x", env=env)
        assert done.returncode == 1 and registry()["E-GUARD-NOIDENT"].message in done.stderr
