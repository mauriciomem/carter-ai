"""``carter identity add`` (plan 005 step 15, freeze H9/H12/H13/H16; RFC App B).

Fake GitHub on loopback, throwaway keys, the hermetic home. The invariant under test: every check
runs before any write, so a failure leaves the tree byte-identical; a success writes the config,
the shim, ``allowed_signers`` and the mirror, with hashes in guard state.
"""

# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import identity_add, terminal
from carter.cli import main
from carter.guard import mirror_io
from carter.guard.state import load
from carter.identity import env as entry
from carter.identity import shim
from carter.identity.config import load_identity
from carter.identity.errors import (
    E_GIT_OLD,
    E_GITHUB_UNREACHABLE,
    E_HUMAN_TERMINAL,
    E_IDENTITY_CHECK,
    IdentityError,
)
from carter.identity.payload import shim_path, shim_state
from carter.identity.schema import Identity, IdentityConfig
from carter.identity.writer import write_config
from gh_api import RATE_HEADERS, FakeGitHub, Reply, fixture
from ssh_rig import KeyPair, real_ssh

LOGIN, UID = "octocat", 583231
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"


@pytest.fixture
def home() -> Path:
    return Path(os.environ["HOME"])


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    server = FakeGitHub().start()
    monkeypatch.setenv("GITHUB_API_URL", server.url)
    server.public_world()
    yield server
    server.stop()


def register(fake: FakeGitHub, *blobs: str, auth: tuple[str, ...] = (), login: str = LOGIN) -> None:
    items = [
        {"id": 100 + i, "key": b, "title": f"k{i}", "created_at": "2026-01-01T00:00:00Z"}
        for i, b in enumerate(blobs)
    ]
    fake.on("GET", f"/users/{login}/ssh_signing_keys", Reply(200, json.dumps(items)))
    fake.on("GET", f"/{login}.keys", Reply(200, "\n".join(auth), content_type="text/plain"))


def tree(root: Path) -> dict[str, str]:
    """Hashes of every file under ``root`` (backups excluded: they are the documented exception)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "backups" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def key(throwaway_key: Callable[..., KeyPair]) -> KeyPair:
    return throwaway_key("ed25519", True)


def request(key: KeyPair, **over: object) -> identity_add.AddRequest:
    base: dict = {"login": LOGIN, "ssh_public_key": str(key.pub_path), "private_key": str(key.path)}
    base.update(over)
    return identity_add.AddRequest(**base)


class TestT1:
    def test_login_only_writes_the_identity_and_the_t1_mirror(
        self, fake: FakeGitHub, home: Path
    ) -> None:
        plan = identity_add.plan_add(identity_add.AddRequest(LOGIN))
        assert (plan.login, plan.uid, plan.fingerprint) == (LOGIN, UID, "")
        identity_add.apply_add(plan)
        cfg = load_identity(home / ".carter" / "config.toml")
        assert (cfg.identity.login, cfg.identity.id, cfg.identity.email) == (LOGIN, UID, EMAIL)
        assert cfg.signing.public_key == "" and cfg.identity.role == "co-author"
        assert mirror_io.read_entries(home / ".carter" / "gitconfig") == [
            ("carter.tier", "t1"),
            ("carter.llmEmail", EMAIL),
        ]
        assert not shim_path(home).exists() and not (home / ".carter" / "hooks").exists()
        assert fake.authorized_requests() == []


class TestApiNote:
    def test_a_non_default_api_is_named_in_the_plan_t1_and_t2(
        self, fake: FakeGitHub, key: KeyPair
    ) -> None:
        """Step-29 review: the user sees which server answered the checks when GITHUB_API_URL is set."""
        register(fake, key.blob)
        for req in (identity_add.AddRequest(LOGIN), request(key)):
            plan = identity_add.plan_add(req)
            assert any(n.startswith(f"GitHub API: {fake.url}") for n in plan.notes), plan.notes


class TestT2:
    def add(self, key: KeyPair, home: Path, **over: object) -> list[str]:
        return identity_add.apply_add(identity_add.plan_add(request(key, **over)))

    def test_a_key_file_gives_the_full_t2_setup(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        notices = self.add(key, home)
        cfg = load_identity(home / ".carter" / "config.toml")
        assert cfg.signing.public_key == key.blob and cfg.signing.fingerprint == key.fingerprint
        assert cfg.signing.private_key_path == str(key.path)
        assert mirror_io.read_entries(home / ".carter" / "gitconfig") == [
            ("carter.tier", "t2"),
            ("carter.llmEmail", EMAIL),
            ("carter.llmFingerprint", key.fingerprint),
        ]
        assert shim_state(home).ok is True  # executable, hash recorded in guard state
        recorded = {f["path"] for f in load(home / ".carter" / "guard-state.json").files}
        assert {
            str(shim_path(home)),
            str(shim.allowed_signers_path(home)),
            str(home / ".carter" / "gitconfig"),
        } <= recorded
        allowed = shim.allowed_signers_path(home)
        assert allowed.read_text() == f'{EMAIL} namespaces="git" {key.blob}\n'
        assert (
            stat.S_IMODE(allowed.stat().st_mode) == 0o600
            and stat.S_IMODE(allowed.parent.stat().st_mode) == 0o700
        )
        assert "guards not installed: `carter check --host` shows G2 off" in notices

    def test_the_entry_now_sends_the_signing_block(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        self.add(key, home)
        answer = entry.answer(str(home), {}, str(home / ".carter" / "config.toml"), home)
        assert answer["reason"] is None and answer["signing"]["fingerprint"] == key.fingerprint

    def test_a_key_literal_works_and_is_not_expanded(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        plan = identity_add.plan_add(request(key, ssh_public_key=f"key::{key.blob} laptop comment"))
        assert plan.cfg.signing.public_key == key.blob  # the comment is dropped

    def test_an_existing_config_is_backed_up_and_kept_in_its_other_parts(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        write_config(
            IdentityConfig(identity=Identity(), state="current"), home / ".carter" / "config.toml"
        )
        register(fake, key.blob)
        self.add(key, home)
        backups = list((home / ".carter" / "backups").rglob("config.toml"))
        assert len(backups) == 1 and "schema = 2" in backups[0].read_text()

    def test_a_repeated_identical_add_changes_nothing(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        self.add(key, home)
        before = tree(home / ".carter")
        stamps = {
            p: p.stat().st_mtime_ns
            for p in (home / ".carter").rglob("*")
            if p.is_file() and "backups" not in p.parts
        }
        self.add(key, home)
        assert tree(home / ".carter") == before
        assert {p: p.stat().st_mtime_ns for p in stamps} == stamps

    def test_rotation_keeps_the_old_public_key_for_verification(
        self, fake: FakeGitHub, home: Path, key: KeyPair, throwaway_key: Callable[..., KeyPair]
    ) -> None:
        new = throwaway_key("ed25519")
        register(fake, key.blob)
        self.add(key, home)
        register(fake, new.blob, key.blob)
        plan = identity_add.plan_add(request(new))
        assert plan.rotated_from == key.fingerprint
        identity_add.apply_add(plan)
        cfg = load_identity(home / ".carter" / "config.toml")
        assert cfg.signing.public_key == new.blob and cfg.signing.previous_public_keys == (
            key.blob,
        )
        lines = shim.allowed_signers_path(home).read_text().splitlines()
        assert lines == [
            f'{EMAIL} namespaces="git" {new.blob}',
            f'{EMAIL} namespaces="git" {key.blob}',
        ]
        assert mirror_io.read_entries(home / ".carter" / "gitconfig")[2] == (
            "carter.llmFingerprint",
            new.fingerprint,
        )
        assert (home / ".carter" / "bin" / "carter-ssh-sign").read_text().count(new.blob) == 1
        assert key.blob not in (home / ".carter" / "bin" / "carter-ssh-sign").read_text()

    def test_password_manager_setups_keep_the_shim(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        plan = identity_add.plan_add(
            identity_add.AddRequest(LOGIN, str(key.pub_path), None, "/run/pm/agent.sock", None)
        )
        identity_add.apply_add(plan)
        text = shim_path(home).read_text()
        assert (
            "AGENT_SOCK=/run/pm/agent.sock" in text
            and load_identity(home / ".carter" / "config.toml").signing.agent_socket
            == "/run/pm/agent.sock"
        )
        prog = identity_add.plan_add(
            identity_add.AddRequest(LOGIN, str(key.pub_path), None, None, "/opt/pm/sign")
        )
        identity_add.apply_add(prog)
        assert (
            "SIGNER=/opt/pm/sign" in shim_path(home).read_text()
            and "AGENT_SOCK=''" in shim_path(home).read_text()
        )


class TestChecksWriteNothing:
    """Every failure: an IdentityError naming the check, and the tree is byte-identical."""

    @pytest.fixture(autouse=True)
    def baseline(self, home: Path) -> None:
        (home / ".carter").mkdir(exist_ok=True)

    def refused(self, home: Path, req: identity_add.AddRequest, code: str, needle: str) -> None:
        before = tree(home / ".carter")
        with pytest.raises(IdentityError) as err:
            identity_add.apply_add(identity_add.plan_add(req))
        assert err.value.code == code and needle in str(err.value), str(err.value)
        assert tree(home / ".carter") == before

    def test_not_registered_as_a_signing_key(
        self, fake: FakeGitHub, home: Path, key: KeyPair, throwaway_key: Callable[..., KeyPair]
    ) -> None:
        register(fake, throwaway_key("ed25519").blob)
        self.refused(home, request(key), E_IDENTITY_CHECK, "not registered as an SSH signing key")

    def test_registered_as_an_authentication_key(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob, auth=(key.blob,))
        self.refused(home, request(key), E_IDENTITY_CHECK, "authentication key")

    @pytest.mark.parametrize("how", ["literal", "file", "private-file-with-pub"])
    def test_the_humans_own_signing_key(
        self, fake: FakeGitHub, home: Path, key: KeyPair, how: str
    ) -> None:
        register(fake, key.blob)
        value = {
            "literal": f"key::{key.blob}",
            "file": str(key.pub_path),
            "private-file-with-pub": str(key.path),
        }[how]
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
            f"[user]\n\tname = H\n\temail = h@e.invalid\n\tsigningkey = {value}\n"
        )
        self.refused(home, request(key), E_IDENTITY_CHECK, "your own signing key")

    def test_a_private_key_literal_is_refused(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        self.refused(
            home,
            request(key, ssh_public_key="key::-----BEGIN OPENSSH PRIVATE KEY-----"),
            E_IDENTITY_CHECK,
            "PRIVATE key",
        )

    def test_the_error_never_echoes_key_material(
        self, fake: FakeGitHub, home: Path, key: KeyPair, tmp_path: Path
    ) -> None:
        fake_private = tmp_path / "id_x"
        fake_private.write_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nSECRETBODYSECRET\n-----END OPENSSH PRIVATE KEY-----\n"
        )
        with pytest.raises(IdentityError) as err:
            identity_add.plan_add(request(key, ssh_public_key=str(fake_private)))
        assert "SECRETBODY" not in str(err.value) and "SECRETBODY" not in err.value.detail

    @pytest.mark.parametrize(
        "value", ["", "not a key", "ssh-ed25519", "ssh-ed25519 !!!", "/nonexistent/key.pub"]
    )
    def test_garbage_is_not_a_public_key(
        self, fake: FakeGitHub, home: Path, key: KeyPair, value: str
    ) -> None:
        self.refused(home, request(key, ssh_public_key=value), E_IDENTITY_CHECK, "")

    def test_a_key_literal_without_a_private_path_or_password_manager_is_refused(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        req = request(key, ssh_public_key=f"key::{key.blob}", private_key=None)
        self.refused(home, req, E_IDENTITY_CHECK, "--private-key")

    @pytest.mark.parametrize("missing", ["file", "directory", "loose"])
    def test_a_bad_private_key_file_is_named_before_anything_is_written(
        self, fake: FakeGitHub, home: Path, key: KeyPair, missing: str
    ) -> None:
        register(fake, key.blob)
        if missing == "file":
            key.path.unlink()
        elif missing == "directory":
            key.path.unlink()
            key.path.mkdir()
        else:
            key.path.chmod(0o644)
        word = {"file": "does not exist", "directory": "not a regular file", "loose": "chmod 600"}
        self.refused(home, request(key), E_IDENTITY_CHECK, word[missing])

    def test_account_problems(self, fake: FakeGitHub, home: Path, key: KeyPair) -> None:
        fake.on("GET", f"/users/{LOGIN}", Reply(404, fixture("err-404.json")))
        self.refused(home, request(key), E_IDENTITY_CHECK, "404")
        fake.public_world("someone", user="user-org.json")
        self.refused(home, request(key, login="someone"), E_IDENTITY_CHECK, "not a User")
        fake.public_world("bot", user="user-bot.json")
        self.refused(home, identity_add.AddRequest("bot"), E_IDENTITY_CHECK, "Bot")

    def test_network_rate_limit_and_server_errors_are_github_unreachable(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        fake.on(
            "GET", f"/users/{LOGIN}", Reply(403, fixture("err-403-rate.json"), dict(RATE_HEADERS))
        )
        self.refused(home, request(key), E_GITHUB_UNREACHABLE, "rate-limit")
        fake.on("GET", f"/users/{LOGIN}", Reply(502, "{}"))
        self.refused(home, request(key), E_GITHUB_UNREACHABLE, "server")
        fake.public_world()
        register(fake, key.blob)
        fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, "{truncated"))
        self.refused(home, request(key), E_GITHUB_UNREACHABLE, "bad-response")

    def test_an_id_mismatch_or_a_different_login_with_an_existing_config(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        write_config(
            IdentityConfig(
                identity=Identity(login=LOGIN, id=1, email=f"1+{LOGIN}@users.noreply.github.com"),
                state="current",
            ),
            home / ".carter" / "config.toml",
        )
        self.refused(home, request(key), E_IDENTITY_CHECK, "id differs")
        write_config(
            IdentityConfig(
                identity=Identity(
                    login="other", id=UID, email=f"{UID}+other@users.noreply.github.com"
                ),
                state="current",
            ),
            home / ".carter" / "config.toml",
        )
        self.refused(home, request(key), E_IDENTITY_CHECK, "another LLM identity")

    def test_login_only_on_a_t2_setup_is_not_a_silent_downgrade(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        identity_add.apply_add(identity_add.plan_add(request(key)))
        self.refused(
            home, identity_add.AddRequest(LOGIN), E_IDENTITY_CHECK, "signing key is configured"
        )

    def test_git_below_2_40_and_old_openssh_refuse_before_any_network_call_for_the_key(
        self, fake: FakeGitHub, home: Path, key: KeyPair, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register(fake, key.blob)

        def too_old() -> tuple[int, ...]:
            raise IdentityError(E_GIT_OLD, detail="found (2, 39)")

        monkeypatch.setattr(shim, "check_git", too_old)
        self.refused(home, request(key), E_GIT_OLD, "2.40")

    def test_a_broken_config_or_state_is_refused(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        (home / ".carter" / "config.toml").write_text("schema = 2\nnot toml [[[")
        self.refused(home, identity_add.AddRequest(LOGIN), "E-CONFIG", "")
        (home / ".carter" / "config.toml").unlink()
        (home / ".carter" / "guard-state.json").write_text("{not json")
        self.refused(home, identity_add.AddRequest(LOGIN), "E-STATE-INVALID", "")

    def test_a_write_that_fails_puts_every_file_back(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        (home / ".carter" / "hooks").write_text("a file where the hooks directory should be")
        before = tree(home / ".carter")
        with pytest.raises(OSError):
            identity_add.apply_add(identity_add.plan_add(request(key)))
        assert tree(home / ".carter") == before
        assert not (home / ".carter" / "gitconfig.d").exists()

    def test_the_private_key_is_never_opened(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        key.path.chmod(0)  # any open() would raise PermissionError
        try:
            identity_add.apply_add(identity_add.plan_add(request(key)))
        finally:
            key.path.chmod(0o600)
        assert load_identity(home / ".carter" / "config.toml").signing.private_key_path == str(
            key.path
        )


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(terminal, "_isatty", lambda _s: True)


def cli(*args: str, input: str | None = None, env: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(main, ["identity", "add", *args], input=input, env=env)


class TestCommand:
    def test_registered_with_the_frozen_options_and_the_role_flag(self) -> None:
        from carter.identity_cli import identity

        opts = {o.opts[0] for o in identity.commands["add"].params} - {"--help"}
        assert opts == {
            "--login",
            "--ssh-public-key",
            "--private-key",
            "--agent-socket",
            "--signing-program",
            "--role",
            "--dry-run",
            "-v",
        }

    def test_dry_run_prints_the_plan_and_writes_nothing_even_in_an_agent_shell(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        before = tree(home)
        done = cli(
            "--login",
            LOGIN,
            "--ssh-public-key",
            str(key.pub_path),
            "--dry-run",
            "-v",
            env={"AGENT": "1"},
        )
        assert done.exit_code == 0, done.output
        assert f"{LOGIN} · T2 · {key.fingerprint[:19]}" in done.output
        assert "dry run, nothing written" in done.output and "carter-ssh-sign" in done.output
        assert tree(home) == before

    def test_writing_is_refused_in_an_agent_shell_and_without_a_terminal(
        self, fake: FakeGitHub, home: Path, human: None
    ) -> None:
        agent = cli("--login", LOGIN, env={"AGENT": "1"})
        assert agent.exit_code == 1 and E_HUMAN_TERMINAL in agent.output
        assert not (home / ".carter" / "config.toml").exists()

    def test_it_asks_nothing_and_needs_no_terminal(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake, key.blob)
        done = cli("--login", LOGIN, "--ssh-public-key", str(key.pub_path))  # no input, no tty
        assert done.exit_code == 0, done.output
        assert done.output.splitlines()[0] == f"✓ {LOGIN} · T2 · {key.fingerprint[:19]}…"
        assert "carter identity unlock" in done.output  # the key has a passphrase: one next step
        assert len(done.output.splitlines()) <= 2
        assert str(key.path) not in done.output  # names and ids only
        cfg = load_identity(home / ".carter" / "config.toml")
        assert cfg.signing.private_key_path == str(key.path) and cfg.signing.mode == "agent"

    @pytest.mark.parametrize("which", ["pub", "private"])
    def test_either_path_of_the_pair_is_enough(
        self, fake: FakeGitHub, home: Path, key: KeyPair, which: str
    ) -> None:
        register(fake, key.blob)
        given = key.pub_path if which == "pub" else key.path
        done = cli("--login", LOGIN, "--ssh-public-key", str(given))
        assert done.exit_code == 0, done.output
        cfg = load_identity(home / ".carter" / "config.toml")
        assert cfg.signing.public_key == key.blob
        assert cfg.signing.private_key_path == str(key.path)

    def test_a_key_without_a_passphrase_is_accepted_silently_and_signs_from_its_file(
        self, fake: FakeGitHub, home: Path, throwaway_key: Callable[..., KeyPair]
    ) -> None:
        plain = throwaway_key("ed25519")
        register(fake, plain.blob)
        done = cli("--login", LOGIN, "--ssh-public-key", str(plain.pub_path))
        assert done.exit_code == 0, done.output
        assert "no passphrase" in done.output and "unlock" not in done.output
        assert "warn" not in done.output.lower() and "!" not in done.output
        cfg = load_identity(home / ".carter" / "config.toml")
        assert cfg.signing.mode == "file"
        script = shim_path(home).read_text()
        assert f"FILE_KEY={shlex.quote(str(plain.path))}" in script

    def test_the_removed_flag_is_gone(self, fake: FakeGitHub, home: Path) -> None:
        from carter.cli import main as top

        done = CliRunner().invoke(top, ["identity", "unlock", "--allow-no-passphrase"])
        assert done.exit_code == 2

    def test_an_unregistered_key_says_the_cause_and_the_fix_in_two_lines(
        self, fake: FakeGitHub, home: Path, key: KeyPair
    ) -> None:
        register(fake)  # the account has no signing key at all
        done = cli("--login", LOGIN, "--ssh-public-key", str(key.pub_path))
        lines = done.output.splitlines()
        assert done.exit_code == 1 and len(lines) == 2, done.output
        assert lines[0] == "✗ not registered as an SSH signing key on the account"
        assert lines[1].startswith("→ on GitHub: Settings") and lines[1].endswith(E_IDENTITY_CHECK)
        assert not (home / ".carter" / "config.toml").exists()

    def test_the_two_password_manager_options_exclude_each_other(self) -> None:
        done = cli("--login", LOGIN, "--agent-socket", "/a", "--signing-program", "/b", "--dry-run")
        assert done.exit_code == 2

    def test_failures_print_the_code_and_exit_one(
        self, fake: FakeGitHub, home: Path, human: None
    ) -> None:
        fake.on("GET", f"/users/{LOGIN}", Reply(404, fixture("err-404.json")))
        done = cli("--login", LOGIN)
        assert done.exit_code == 1 and E_IDENTITY_CHECK in done.output
        assert "Nothing was written" not in done.output  # the cause, not a list of reassurances
        bad = cli("--login", "not a login!", "--dry-run")
        assert bad.exit_code == 2


@real_ssh
def test_a_t2_identity_made_here_signs_a_commit_through_the_real_shim(
    fake: FakeGitHub, home: Path, key: KeyPair, real_ssh_agent, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """Step 21/25 sign with what step 15 writes: shim, config and agent agree end to end."""
    import subprocess

    from carter.identity.payload import to_git_env

    register(fake, key.blob)
    plan = identity_add.plan_add(request(key))
    # the shim bakes the dedicated socket; point this test's key at the throwaway agent instead
    params = shim.ShimParams(
        key=key.blob,
        sock=str(real_ssh_agent.sock),
        false_path=shim.resolve_false(),
        keygen="/usr/bin/ssh-keygen",
        run_dir=str(home / ".carter" / "run"),
    )
    (home / ".carter" / "run").mkdir(parents=True, exist_ok=True, mode=0o700)
    plan.shim_data = shim.render(params)
    identity_add.apply_add(plan)
    assert real_ssh_agent.add(key) == 0
    answer = entry.answer(str(home), {}, str(home / ".carter" / "config.toml"), home)
    block = answer["signing"]
    env = {**os.environ, **to_git_env({}, block).env}
    repo = tmp_path / "r"
    repo.mkdir()
    for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        done = subprocess.run(["git", *argv], cwd=repo, env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    shown = subprocess.run(
        [
            "git",
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.allowedSignersFile={shim.allowed_signers_path(home)}",
            "-c",
            f"gpg.ssh.program={shim_path(home)}",
            "log",
            "-1",
            "--format=%G?|%GF",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert shown.stdout.strip() == f"G|{key.fingerprint}"
