# ruff: noqa: E501
"""Linking the human's co-author email to GitHub, the cache, and ``--emit`` for role b
(plan 006 step 6; freeze K7, K11)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from carter.identity import coauthor, github
from carter.identity.coauthor import (
    LINK_CACHE_TTL_S,
    cached_link,
    check_link,
    gh_user_emails,
    noreply_parts,
    record_link,
    refresh_link,
)
from carter.ops.config import Config
from gh_api import FakeGitHub

DATA = Path(__file__).resolve().parents[1] / "data" / "github" / "user-emails.json"
ROWS = json.loads(DATA.read_text())
NOREPLY = "583231+octocat@users.noreply.github.com"
PRIMARY = "octocat@example.invalid"
HUMAN_ENV: dict[str, str] = {}  # no agent marker: a human terminal
AGENT_ENV = {"CARTER_AGENT_SHELL": "1"}


@dataclass
class U:
    id: int
    login: str


def user_ok(login: str) -> U:
    return U(583231, "octocat")


def no_user(login: str) -> U:
    raise OSError("offline")


@pytest.fixture
def home() -> Path:
    return Path(os.environ["HOME"])


class TestCheck:
    def test_the_noreply_pattern_is_found_after_casefold(self) -> None:
        assert noreply_parts(NOREPLY) == (583231, "octocat")
        assert noreply_parts("583231+OctoCat@USERS.NOREPLY.GITHUB.COM") == (583231, "octocat")
        for bad in (
            "octocat@users.noreply.github.com",
            "1+@users.noreply.github.com",
            NOREPLY + ".evil.example",
            PRIMARY,
        ):
            assert noreply_parts(bad) is None

    def test_noreply_is_yes_when_the_account_agrees(self) -> None:
        assert check_link(NOREPLY, user_ok, lambda: None) == "noreply"

    def test_noreply_with_another_id_or_login_is_not_linked(self) -> None:
        assert check_link("1+octocat@users.noreply.github.com", user_ok, lambda: None) == ""
        assert (
            check_link(
                "583231+someone@users.noreply.github.com",
                lambda login: U(583231, "octocat"),
                lambda: None,
            )
            == ""
        )

    def test_offline_is_unknown_not_an_error(self) -> None:
        assert check_link(NOREPLY, no_user, lambda: None) == ""

    def test_a_verified_email_of_the_account_is_yes_verified(self) -> None:
        assert check_link(PRIMARY, no_user, lambda: ROWS) == "verified"
        assert check_link(PRIMARY.upper(), no_user, lambda: ROWS) == "verified"

    def test_an_unverified_or_absent_email_is_unknown(self) -> None:
        assert check_link("old-address@example.invalid", no_user, lambda: ROWS) == ""
        assert check_link("other@example.invalid", no_user, lambda: ROWS) == ""
        assert check_link(PRIMARY, no_user, lambda: None) == ""

    def test_a_noreply_that_the_account_does_not_confirm_can_still_be_verified_through_gh(
        self,
    ) -> None:
        assert check_link(NOREPLY, no_user, lambda: ROWS) == "verified"

    def test_a_crashing_reader_is_unknown(self) -> None:
        def boom() -> list[dict]:
            raise RuntimeError

        assert check_link(PRIMARY, no_user, boom) == ""

    def test_the_real_client_against_the_loopback_fake(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeGitHub().start()
        try:
            monkeypatch.setenv("GITHUB_API_URL", fake.url)
            fake.public_world()
            assert check_link(NOREPLY, github.get_user, lambda: None) == "noreply"
            assert fake.authorized_requests() == []  # no credentials
        finally:
            fake.stop()


class TestCache:
    def test_a_recorded_state_is_read_back_until_it_expires(self, home: Path) -> None:
        record_link(NOREPLY, "noreply", home, now=1000.0)
        assert cached_link(NOREPLY, home, now=1000.0 + 5) == "noreply"
        assert cached_link(NOREPLY.upper(), home, now=1000.0 + 5) == "noreply"  # casefolded key
        assert cached_link(NOREPLY, home, now=1000.0 + LINK_CACHE_TTL_S + 1) == ""
        assert cached_link(PRIMARY, home, now=1000.0) == ""

    def test_the_file_is_0600_holds_hashes_only_and_no_email(self, home: Path) -> None:
        record_link(PRIMARY, "verified", home, now=1.0)
        path = coauthor.cache_path(home)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        text = path.read_text()
        assert "octocat" not in text and "example.invalid" not in text and "@" not in text
        (key,) = json.loads(text)
        assert key == coauthor.email_key(PRIMARY) and len(key) == 64

    def test_expired_rows_are_dropped_on_the_next_write(self, home: Path) -> None:
        record_link("old@example.invalid", "verified", home, now=1.0)
        record_link(PRIMARY, "verified", home, now=LINK_CACHE_TTL_S + 100.0)
        assert list(json.loads(coauthor.cache_path(home).read_text())) == [
            coauthor.email_key(PRIMARY)
        ]

    @pytest.mark.parametrize(
        "junk",
        [
            "",
            "not json",
            "[]",
            '{"x": 1}',
            json.dumps({coauthor.email_key(PRIMARY): {"linked": "yes"}}),
            json.dumps({coauthor.email_key(PRIMARY): {"linked": "verified", "at": "soon"}}),
        ],
    )
    def test_a_damaged_cache_reads_as_unknown_and_is_replaced_by_a_write(
        self, home: Path, junk: str
    ) -> None:
        path = coauthor.cache_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(junk)
        assert cached_link(PRIMARY, home) == ""
        record_link(PRIMARY, "verified", home)
        assert cached_link(PRIMARY, home) == "verified"

    def test_only_the_two_states_can_be_recorded(self, home: Path) -> None:
        with pytest.raises(ValueError):
            record_link(PRIMARY, "unknown", home)

    def test_a_future_timestamp_is_not_fresh(self, home: Path) -> None:
        record_link(PRIMARY, "verified", home, now=10_000.0)
        assert cached_link(PRIMARY, home, now=5_000.0) == ""


class TestHumanTerminalOnly:
    def test_a_human_terminal_asks_and_caches(self, home: Path) -> None:
        assert refresh_link(NOREPLY, user_ok, lambda: None, HUMAN_ENV, home) == "noreply"
        assert cached_link(NOREPLY, home) == "noreply"

    def test_an_agent_shell_never_calls_the_network_or_gh_and_never_writes(
        self, home: Path
    ) -> None:
        def fail(*_a: object) -> object:
            raise AssertionError("the network or gh was used in an agent shell")

        assert refresh_link(NOREPLY, fail, fail, AGENT_ENV, home) == ""  # type: ignore[arg-type]
        assert not coauthor.cache_path(home).exists()

    def test_an_agent_shell_may_read_what_a_human_cached(self, home: Path) -> None:
        record_link(NOREPLY, "noreply", home)
        assert refresh_link(NOREPLY, no_user, lambda: None, AGENT_ENV, home) == "noreply"

    def test_a_negative_answer_is_not_cached(self, home: Path) -> None:
        assert refresh_link("x@example.invalid", no_user, lambda: ROWS, HUMAN_ENV, home) == ""
        assert not coauthor.cache_path(home).exists()

    def test_an_unwritable_cache_does_not_fail_the_check(self, home: Path) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "run").write_text("a file where the folder should be")
        assert refresh_link(NOREPLY, user_ok, lambda: None, HUMAN_ENV, home) == "noreply"


class TestGhEmails:
    def fake_gh(self, tmp_path: Path, body: str, rc: int = 0) -> str:
        path = tmp_path / "gh"
        path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{body}\nEOF\nexit {rc}\n")
        path.chmod(0o755)
        return str(path)

    def runner(self, gh: str):  # type: ignore[no-untyped-def]
        def run(argv, **kw):  # type: ignore[no-untyped-def]
            assert argv == ["gh", "api", "/user/emails"]
            return subprocess.run([gh, *argv[1:]], **kw)

        return run

    def test_the_documented_shape_is_parsed(self, tmp_path: Path) -> None:
        rows = gh_user_emails(self.runner(self.fake_gh(tmp_path, DATA.read_text())))
        assert rows == ROWS

    @pytest.mark.parametrize(("body", "rc"), [("not json", 0), ("{}", 0), ("[]", 1), ("", 0)])
    def test_anything_else_is_none(self, tmp_path: Path, body: str, rc: int) -> None:
        got = gh_user_emails(self.runner(self.fake_gh(tmp_path, body, rc)))
        assert got is None or (body == "[]" and rc == 0)

    def test_no_gh_is_none(self) -> None:
        def missing(*_a: object, **_k: object) -> object:
            raise FileNotFoundError("gh")

        assert gh_user_emails(missing) is None  # type: ignore[arg-type]


LLM_EMAIL = "4242+llm-bot@users.noreply.github.com"
BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"


@pytest.fixture
def role_b(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from carter.identity.payload import fingerprint_of

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'schema = 2\n[identity]\nrole = "author"\nlogin = "llm-bot"\nid = 4242\nemail = "{LLM_EMAIL}"\n'
        f'[identity.signing]\nfingerprint = "{fingerprint_of(BLOB)}"\npublic_key = "{BLOB}"\n'
    )
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    monkeypatch.chdir(work)
    yield cfg


def git_user(name: str, email: str) -> None:
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
        f"[user]\n\tname = {name}\n\temail = {email}\n"
    )


class TestEmitForRoleB:
    def test_the_trailer_is_the_humans_and_the_shape_is_llm_authored(self, role_b: Path) -> None:
        git_user("Hu Man", PRIMARY)
        got = Config.load(role_b, workspace=None, env={})
        assert got.coauthor_trailer == f"Co-authored-by: Hu Man <{PRIMARY}>"
        assert (got.role, got.author, got.committer, got.commits, got.refusal_reason) == (
            "author",
            "llm",
            "llm",
            "allowed",
            "",
        )
        assert got.signer_fpr.startswith("SHA256:")

    def test_unlinked_is_false_with_a_warning_that_does_not_print_the_email(
        self, role_b: Path
    ) -> None:
        git_user("Hu Man", PRIMARY)
        got = Config.load(role_b, workspace=None, env={})
        assert got.coauthor_linked is False
        assert any("not known to be linked" in w for w in got.warnings)
        assert all(PRIMARY not in w for w in got.warnings)

    def test_a_fresh_cache_entry_makes_it_linked_without_any_network(self, role_b: Path) -> None:
        git_user("Hu Man", PRIMARY)
        record_link(PRIMARY, "verified", Path.home())
        got = Config.load(role_b, workspace=None, env={})
        assert got.coauthor_linked is True and not any("linked" in w for w in got.warnings)

    @pytest.mark.parametrize(
        ("name", "email"),
        [
            ("", ""),
            ("Hu Man", LLM_EMAIL),
            ("Carter", "state@carter.invalid"),
            ("Hu Man", "carter-bot@users.noreply.github.com"),
        ],
    )
    def test_without_a_usable_human_identity_commits_are_refused_with_the_code(
        self, role_b: Path, name: str, email: str
    ) -> None:
        git_user(name, email)
        got = Config.load(role_b, workspace=None, env={})
        assert (got.commits, got.refusal_reason, got.coauthor_trailer) == (
            "refused",
            "E-HUMAN-IDENTITY",
            "",
        )
        assert (got.author, got.committer) == ("human", "human")

    @pytest.mark.parametrize(
        ("name", "email"),
        [
            ("Carter", "carter@example.invalid"),
            ("Carter", "583231+carter@users.noreply.github.com"),
            ("Hu Man", "state@carter.invalid"),
        ],
    )
    def test_a_person_named_carter_or_that_address_alone_is_a_valid_human(
        self, role_b: Path, name: str, email: str
    ) -> None:
        git_user(name, email)
        got = Config.load(role_b, workspace=None, env={})
        assert (got.commits, got.refusal_reason) == ("allowed", "")
        assert got.coauthor_trailer == f"Co-authored-by: {name} <{email}>"

    def test_role_a_is_unchanged(self, role_b: Path) -> None:
        git_user("", "")
        role_b.write_text(role_b.read_text().replace('role = "author"\n', ""))
        got = Config.load(role_b, workspace=None, env={})
        assert (
            got.coauthor_trailer == f"Co-authored-by: llm-bot <{LLM_EMAIL}>"
            and got.commits == "allowed"
        )
        assert got.author == "human" and got.committer == "llm"

    def test_role_b_below_t2_is_still_the_tier_refusal(self, role_b: Path) -> None:
        role_b.write_text(role_b.read_text().split("[identity.signing]")[0])
        got = Config.load(role_b, workspace=None, env={})
        assert (got.commits, got.refusal_reason) == ("refused", "E-ROLE-B-TIER")
