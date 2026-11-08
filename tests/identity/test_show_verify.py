# ruff: noqa: E501
"""``carter identity show`` and ``verify`` (plan 005 step 16; RFC-0007 App B).

``show`` is read-only and prints names only. ``verify`` makes one real signed commit in a throwaway
repository with the real shim and a throwaway agent, and reports distinct messages for a locked
key, the wrong key, a stale shim socket and a changed fingerprint. GitHub is the loopback fake.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from carter import identity_add, identity_show, identity_verify
from carter.identity.agent_probe import Probe
from carter.identity.config import load_identity
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace
from carter.identity.writer import write_config
from gh_api import FakeGitHub, Reply
from rows import Out, invoke
from sentinels import fine_grained
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


def run(*args: str, env: dict[str, str] | None = None) -> Out:
    extra = ["-v"] if args and args[0] == "verify" else []
    return invoke("identity", *args, *extra, env=env)


def tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def make_t1(home: Path) -> None:
    (home / ".carter").mkdir(exist_ok=True)
    write_config(
        IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL, name=LOGIN), state="current"
        ),
        home / ".carter" / "config.toml",
    )


def add_t2(fake: FakeGitHub, key: KeyPair, sock: str, **over: object) -> None:
    items = [{"id": 1, "key": key.blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
    import json

    fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
    fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))
    req = identity_add.AddRequest(
        LOGIN, str(key.pub_path), None, over.get("agent_socket", sock), None
    )  # type: ignore[arg-type]
    identity_add.apply_add(identity_add.plan_add(req))


@pytest.fixture
def key(throwaway_key: Callable[..., KeyPair]) -> KeyPair:
    return throwaway_key("ed25519")


class TestShow:
    def test_nothing_configured_is_t0_and_exit_0(self, home: Path) -> None:
        done = run("show")
        assert done.exit_code == 0, done.output
        assert "none configured: tier t0" in done.output
        assert "configured t0, cap none, effective t0" in done.output
        assert "Assisted-by: Carter" in done.output

    def test_a_config_defect_is_e_config_never_defaults(self, home: Path) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text("schema = 2\nnot toml [[[")
        done = run("show")
        assert (
            done.exit_code == 1 and "E-CONFIG" in done.output and "effective t0" not in done.output
        )

    def test_t1_shows_role_tier_and_shape(self, home: Path) -> None:
        make_t1(home)
        out = run("show").output
        assert f"{LOGIN} (id {UID}, {EMAIL})" in out
        assert "co-author: the human is the author" in out and "(source: default)" in out
        assert "configured t1, cap none, effective t1" in out
        assert "trailer `Co-authored-by`; unsigned" in out
        assert "signing key" not in out  # no key custody lines below T2

    def test_the_role_source_follows_the_priority_order(self, home: Path, tmp_path: Path) -> None:
        make_t1(home)
        env_out = run("show", env={"CARTER_IDENTITY_ROLE": "co-author"}).output
        assert "(source: env)" in env_out
        typo = run("show", env={"CARTER_IDENTITY_ROLE": "boss"}).output
        assert "WARN  role: CARTER_IDENTITY_ROLE is not one of" in typo and "boss" not in typo

    def test_a_workspace_cap_is_shown_and_the_effective_tier_follows(
        self, home: Path, tmp_path: Path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL),
            workspaces={str(ws.resolve()): Workspace(max_tier="t0")},
            state="current",
        )
        (home / ".carter").mkdir(exist_ok=True)
        write_config(cfg, home / ".carter" / "config.toml")
        monkeypatch.chdir(ws)
        out = run("show").output
        assert "configured t1, cap t0, effective t0" in out
        assert (
            "OK    tier mirror: the guard reads t0" in out
        )  # no mirror file = t0 = the capped tier

    def test_it_is_read_only_and_works_in_an_agent_shell(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        before = tree(home)
        done = run("show", env={"AGENT": "1", "GH_TOKEN": fine_grained("SHOW")})
        assert done.exit_code in (0, 1)
        assert tree(home) == before
        assert "SHOW" not in done.output and str(key.path) not in done.output

    def test_t2_lists_the_custody_lines(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        out = run("show").output
        assert key.fingerprint in out
        assert "WARN  agent: locked: the agent holds no key" in out
        assert "OK    shim:" in out and "the shim and the agent socket agree" in out
        assert "author is you, committer and signer are the LLM" in out
        assert real_ssh_agent.add(key) == 0
        assert "OK    agent: the LLM key is loaded in the agent" in run("show").output

    @pytest.mark.parametrize(
        ("state", "level"),
        [
            ("ok", "OK"),
            ("empty", "WARN"),
            ("none", "WARN"),
            ("wrong-key", "RED"),
            ("stale", "RED"),
            ("bad", "RED"),
        ],
    )
    def test_every_agent_state_has_its_own_line_and_the_red_ones_exit_1(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        real_ssh_agent,
        monkeypatch: pytest.MonkeyPatch,
        state: str,
        level: str,  # type: ignore[no-untyped-def]
    ) -> None:
        add_t2(fake, key, str(real_ssh_agent.sock))
        monkeypatch.setattr(identity_show, "probe_setup", lambda *_a: Probe(state))
        done = run("show")
        agent_line = next(ln for ln in done.output.splitlines() if " agent:" in ln)
        assert agent_line.split()[0] == level
        assert (done.exit_code == 1) == (level == "RED")

    def test_a_shim_naming_another_socket_or_edited_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        shim = home / ".carter" / "bin" / "carter-ssh-sign"
        text = shim.read_text()
        shim.write_text(
            text.replace(f"AGENT_SOCK={real_ssh_agent.sock}", "AGENT_SOCK=/tmp/other.sock")
        )
        out = run("show").output
        assert "RED   shim: the shim names a different agent socket" in out
        assert "RED   shim:" in out and "missing, not executable or changed" in out

    def test_a_stale_mirror_is_warned_with_the_fix(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert "OK    tier mirror: the guard reads t2" in run("show").output
        (home / ".carter" / "gitconfig").unlink()
        out = run("show").output
        assert (
            "WARN  tier mirror: the guard reads t0, below config.toml" in out
            and "carter update" in out
        )

    def test_guard_coverage_unguarded_without_a_guard_install(self, home: Path) -> None:
        make_t1(home)
        out = run("show").output
        assert (
            "WARN  guards: no commit or push guards installed" in out
            and "carter guard install" in out
        )


class TestVerifyLocal:
    @pytest.fixture
    def stray(self) -> Callable[[], set[str]]:
        return lambda: {
            p for p in os.listdir(tempfile.gettempdir()) if p.startswith("carter-verify-")
        }

    @real_ssh
    def test_a_loaded_key_signs_a_test_commit_and_every_check_passes(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent, stray
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert real_ssh_agent.add(key) == 0
        before, files = stray(), tree(home)
        done = run("verify")
        assert done.exit_code == 0, done.output
        for needle in (
            "OK    signature: good signature by " + key.fingerprint,
            "OK    author: the author is not the LLM",
            "OK    committer: the committer is the LLM",
            f"OK    trailer: Co-authored-by: {LOGIN} <{EMAIL}>",
        ):
            assert needle in done.output, needle
        assert stray() == before and tree(home) == files  # nothing left, nothing written

    @real_ssh
    def test_a_locked_key_is_reported_without_prompting_and_exits_non_zero(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent, stray
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        done = run("verify")
        assert done.exit_code == 1
        assert (
            "RED   verify: locked (empty)" in done.output
            and "carter identity unlock" in done.output
        )
        assert not stray()

    @real_ssh
    def test_the_wrong_key_loaded_is_its_own_message(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        throwaway_key: Callable[..., KeyPair],
        real_ssh_agent,
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        other = throwaway_key("ed25519")
        assert real_ssh_agent.add(other) == 0
        done = run("verify")
        assert (
            done.exit_code == 1
            and "the agent holds other keys, not the configured one" in done.output
        )

    @real_ssh
    def test_a_stale_shim_socket_is_its_own_message(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert real_ssh_agent.add(key) == 0
        cfg = load_identity(home / ".carter" / "config.toml")
        write_config(
            replace(cfg, signing=replace(cfg.signing, agent_socket="/tmp/moved.sock")),
            home / ".carter" / "config.toml",
        )
        done = run("verify")
        assert (
            done.exit_code == 1
            and "the shim names a different agent socket than config.toml" in done.output
        )

    @real_ssh
    def test_a_changed_fingerprint_is_its_own_message(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert real_ssh_agent.add(key) == 0
        cfg = load_identity(home / ".carter" / "config.toml")
        write_config(
            replace(cfg, signing=replace(cfg.signing, fingerprint="SHA256:" + "A" * 43)),
            home / ".carter" / "config.toml",
        )
        done = run("verify")
        assert (
            done.exit_code == 1
            and "the configured fingerprint is not the public key's" in done.output
            or "fingerprint" in done.output
        )

    def test_below_t2_there_is_nothing_to_verify(self, home: Path) -> None:
        make_t1(home)
        done = run("verify")
        assert done.exit_code == 1 and "no signing key is configured (tier below T2)" in done.output

    def test_the_previous_keys_are_in_allowed_signers(
        self, key: KeyPair, throwaway_key: Callable[..., KeyPair]
    ) -> None:
        old = throwaway_key("ed25519")
        cfg = IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL),
            signing=Signing(
                public_key=key.blob, fingerprint=key.fingerprint, previous_public_keys=(old.blob,)
            ),
            state="current",
        )
        assert identity_verify.allowed_signers_text(cfg).splitlines() == [
            f'{EMAIL} namespaces="git" {key.blob}',
            f'{EMAIL} namespaces="git" {old.blob}',
        ]

    @real_ssh
    def test_the_private_key_is_never_opened(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert real_ssh_agent.add(key) == 0
        key.path.chmod(0)
        try:
            assert run("verify").exit_code == 0
        finally:
            key.path.chmod(0o600)


class TestVerifyRemote:
    SHA = "a1" * 20

    def test_verified_unsigned_and_unknown_key(self, fake: FakeGitHub) -> None:
        for name, level, text in (
            ("commit-verified.json", "OK", "is Verified on GitHub (valid)"),
            ("commit-unsigned.json", "RED", "is not verified: unsigned"),
            ("commit-unknown-key.json", "RED", "not verified: unknown_key"),
        ):
            fake.commit_world("octocat/hello", self.SHA, name)
            done = run("verify", "--remote", "octocat/hello", "--sha", self.SHA)
            assert done.output.count(f"{level}") >= 1 and text in done.output
            assert (done.exit_code == 0) == (level == "OK")
        assert fake.authorized_requests() == []

    def test_unreachable_github_is_an_error_not_a_pass(self, fake: FakeGitHub) -> None:
        fake.on("GET", f"/repos/octocat/hello/commits/{self.SHA}", Reply(502, "{}"))
        done = run("verify", "--remote", "octocat/hello", "--sha", self.SHA)
        assert (
            done.exit_code == 1
            and "E-GITHUB-UNREACHABLE" in done.output
            and "OK" not in done.output.split("E-GITHUB")[0]
        )

    def test_options_go_together_and_are_validated(self, fake: FakeGitHub) -> None:
        assert run("verify", "--remote", "octocat/hello").exit_code == 2
        assert run("verify", "--sha", self.SHA).exit_code == 2
        assert run("verify", "--remote", "no slash", "--sha", self.SHA).exit_code == 2
        assert run("verify", "--remote", "octocat/hello", "--sha", "xyz").exit_code == 2
        assert fake.requests == []
