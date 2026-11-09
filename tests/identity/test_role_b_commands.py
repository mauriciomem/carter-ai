# ruff: noqa: E501, F811
"""``identity add --role``, ``show`` and ``verify`` for role author.

The same fakes as the 2b command tests: loopback GitHub, throwaway keys, the hermetic home. The
human's identity is in the hermetic global git config; nothing leaves the machine except the
unauthenticated reads of the fake.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from carter import terminal
from carter.identity import coauthor
from carter.identity.config import load_identity
from carter.identity.errors import E_ROLE_B_TIER, registry
from identity.test_identity_add import cli, register, tree
from identity.test_identity_add import fake as fake  # fixtures
from identity.test_identity_add import home as home  # fixtures
from identity.test_show_verify import add_t2, run
from ssh_rig import KeyPair, real_ssh

LOGIN, UID = "octocat", 583231
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
HUMAN = ("Hu Man", "human@example.invalid")
NOREPLY_HUMAN = ("Hu Man", "1234+humanlogin@users.noreply.github.com")


def git_user(name: str, email: str) -> None:
    lines = (
        ["[user]"]
        + ([f"\tname = {name}"] if name else [])
        + ([f"\temail = {email}"] if email else [])
    )
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text("\n".join(lines) + "\n")


@pytest.fixture(autouse=True)
def human_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Your own terminal with your own git identity."""
    monkeypatch.setattr(terminal, "_isatty", lambda _s: True)
    git_user(*HUMAN)


@pytest.fixture
def key(throwaway_key: Callable[..., KeyPair]) -> KeyPair:
    return throwaway_key("ed25519", True)


def role_of(home: Path) -> str:
    return load_identity(home / ".carter" / "config.toml").identity.role


class TestAddRole:
    def test_role_author_with_a_key_writes_the_role_and_tells_you_about_your_identity(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        register(fake, key.blob)
        done = cli(
            "--login",
            LOGIN,
            "--ssh-public-key",
            str(key.pub_path),
            "--private-key",
            str(key.path),
            "--role",
            "author",
            "-v",
        )
        assert done.exit_code == 0, done.output
        assert role_of(home) == "author"
        assert "· author" in done.output
        assert "human identity: " in done.output and "! co-author link" in done.output  # a warning
        assert HUMAN[1] not in done.output and HUMAN[0] not in done.output  # names only

    def test_role_author_without_a_key_is_e_role_b_tier_and_nothing_is_written(
        self, fake, home: Path
    ) -> None:
        before = tree(home)
        done = cli("--login", LOGIN, "--role", "author")
        assert done.exit_code != 0 and E_ROLE_B_TIER in done.output + str(done.exception or "")
        assert tree(home) == before
        assert registry()[E_ROLE_B_TIER].message in done.output

    def test_dry_run_shows_the_role_and_writes_nothing_not_even_the_link_cache(
        self, fake, home: Path, key: KeyPair
    ) -> None:
        git_user(*NOREPLY_HUMAN)
        fake.on(
            "GET",
            "/users/humanlogin",
            __import__("gh_api").Reply(
                200, json.dumps({"login": "humanlogin", "id": 1234, "type": "User"})
            ),
        )
        register(fake, key.blob)
        before = tree(home)
        done = cli(
            "--login",
            LOGIN,
            "--ssh-public-key",
            str(key.pub_path),
            "--private-key",
            str(key.path),
            "--role",
            "author",
            "--dry-run",
            "-v",
        )
        assert (
            done.exit_code == 0
            and "· author" in done.output
            and "dry run, nothing written" in done.output
        )
        assert "co-author link: your address is linked to a GitHub account (noreply)" in done.output
        assert tree(home) == before and not coauthor.cache_path(home).exists()

    def test_a_real_run_caches_a_positive_link_as_a_hash(
        self, fake, home: Path, key: KeyPair
    ) -> None:
        git_user(*NOREPLY_HUMAN)
        fake.on(
            "GET",
            "/users/humanlogin",
            __import__("gh_api").Reply(
                200, json.dumps({"login": "humanlogin", "id": 1234, "type": "User"})
            ),
        )
        register(fake, key.blob)
        done = cli(
            "--login",
            LOGIN,
            "--ssh-public-key",
            str(key.pub_path),
            "--private-key",
            str(key.path),
            "--role",
            "author",
            input="y\n",
        )
        assert done.exit_code == 0, done.output
        path = coauthor.cache_path(home)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600 and "humanlogin" not in path.read_text()
        assert coauthor.cached_link(NOREPLY_HUMAN[1], home) == "noreply"

    def test_a_role_only_change_on_an_existing_t2_identity_keeps_the_key_and_the_shim(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        shim_before = (home / ".carter" / "bin" / "carter-ssh-sign").read_bytes()
        before_cfg = load_identity(home / ".carter" / "config.toml")
        done = cli("--login", LOGIN, "--role", "author", "-v")
        assert done.exit_code == 0, done.output
        after = load_identity(home / ".carter" / "config.toml")
        assert after.identity.role == "author" and after.signing == before_cfg.signing
        assert (home / ".carter" / "bin" / "carter-ssh-sign").read_bytes() == shim_before
        assert "role: author (config.toml only" in done.output
        back = cli("--login", LOGIN, "--role", "co-author", input="y\n")
        assert back.exit_code == 0 and role_of(home) == "co-author"

    def test_without_role_an_existing_role_is_kept_on_a_key_rotation(
        self, fake, home: Path, key: KeyPair, throwaway_key, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert cli("--login", LOGIN, "--role", "author", input="y\n").exit_code == 0
        other = throwaway_key("ed25519", True)
        register(fake, key.blob, other.blob)
        done = cli(
            "--login",
            LOGIN,
            "--ssh-public-key",
            str(other.pub_path),
            "--private-key",
            str(other.path),
            input="y\n",
        )
        assert done.exit_code == 0, done.output
        assert role_of(home) == "author"

    def test_role_alone_with_other_key_arguments_still_needs_the_key(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        done = cli("--login", LOGIN, "--role", "author", "--private-key", "/x/key")
        assert done.exit_code != 0 and "pass --ssh-public-key" in done.output

    def test_an_unknown_role_is_a_usage_error(self, fake, home: Path) -> None:
        done = cli("--login", LOGIN, "--role", "boss")
        assert done.exit_code == 2 and "Invalid value for '--role'" in done.output

    def test_a_dco_repository_gets_a_warning(
        self, fake, home: Path, key: KeyPair, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "dco.yml").write_text("require:\n  members: false\n")
        monkeypatch.chdir(tmp_path)
        register(fake, key.blob)
        done = cli(
            "--login",
            LOGIN,
            "--ssh-public-key",
            str(key.pub_path),
            "--private-key",
            str(key.path),
            "--role",
            "author",
            "--dry-run",
        )
        assert "! dco: this repository has .github/dco.yml" in done.output


class TestShow:
    def author(self, fake, home: Path, key: KeyPair, sock: str) -> None:
        add_t2(fake, key, sock)
        assert cli("--login", LOGIN, "--role", "author", input="y\n").exit_code == 0

    def test_role_author_at_t2_describes_the_shape_and_checks_the_humans_identity(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        self.author(fake, home, key, str(real_ssh_agent.sock))
        done = run("show")
        assert "role: author: the LLM is author and committer" in done.output
        assert (
            "author, committer and signer are the LLM; trailer `Co-authored-by: <you>`"
            in done.output
        )
        assert "OK    human identity: your git user.name and user.email are usable" in done.output
        assert "WARN  co-author link" in done.output
        assert HUMAN[1] not in done.output

    def test_an_unusable_identity_is_red_with_the_code(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        self.author(fake, home, key, str(real_ssh_agent.sock))
        git_user("", "")
        done = run("show")
        assert (
            done.exit_code == 1
            and "RED   human identity: E-HUMAN-IDENTITY" in done.output
            and "missing-name" in done.output
        )

    def test_show_reads_the_cache_and_never_asks_github_or_gh(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        self.author(fake, home, key, str(real_ssh_agent.sock))
        fake.requests.clear()
        coauthor.record_link(HUMAN[1], "verified", home)
        done = run("show")
        assert (
            "OK    co-author link: your address is linked to a GitHub account (verified)"
            in done.output
        )
        assert fake.requests == []

    def test_role_a_shows_none_of_it(self, fake, home: Path, key: KeyPair, real_ssh_agent) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert "human identity" not in run("show").output


@real_ssh
class TestVerify:
    def author(self, fake, home: Path, key: KeyPair, real_ssh_agent) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert cli("--login", LOGIN, "--role", "author", input="y\n").exit_code == 0
        assert real_ssh_agent.add(key) == 0

    def test_role_b_expects_l_l_g_and_the_humans_trailer(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        self.author(fake, home, key, real_ssh_agent)
        before = tree(home)
        done = run("verify")
        assert done.exit_code == 0, done.output
        for needle in (
            "OK    signature: good signature by " + key.fingerprint,
            "OK    author: the author is the LLM (role author)",
            "OK    committer: the committer is the LLM",
            f"OK    trailer: Co-authored-by: {HUMAN[0]} <{HUMAN[1]}>",
        ):
            assert needle in done.output, needle
        assert tree(home) == before

    def test_an_unusable_human_identity_is_its_own_message_not_a_signing_failure(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        self.author(fake, home, key, real_ssh_agent)
        git_user("", "")
        done = run("verify")
        assert (
            done.exit_code == 1
            and "E-HUMAN-IDENTITY" in done.output
            and "could not be signed" not in done.output
        )

    def test_role_a_still_expects_h_l_g(
        self, fake, home: Path, key: KeyPair, real_ssh_agent
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, str(real_ssh_agent.sock))
        assert real_ssh_agent.add(key) == 0
        done = run("verify")
        assert done.exit_code == 0 and "OK    author: the author is not the LLM" in done.output
