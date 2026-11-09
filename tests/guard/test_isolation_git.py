"""The rendered isolation block against real git.

The environment is produced by the Python reference ``apply_isolation`` from a rendered
``isolation.json`` document, which is exactly what the TypeScript core produces for the same
input (golden vectors). Everything runs in
the hermetic fixture home with file remotes only: no network, no agent socket, no real key.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from carter.identity import isolation
from carter.identity.isolation_apply import apply_isolation
from sentinels import fine_grained

GIT = shutil.which("git")
FALSE = next((p for p in isolation.FALSE_CANDIDATES if Path(p).exists()), None)
pytestmark = pytest.mark.skipif(FALSE is None, reason="no /usr/bin/false or /bin/false")


def git(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env if env is not None else dict(os.environ),
        capture_output=True,
        text=True,
        input=stdin,
        timeout=60,
    )


@pytest.fixture
def doc(tmp_path: Path) -> dict:
    assert FALSE is not None
    return isolation.render(
        home=str(tmp_path / "home"),
        python_path=sys.executable,
        carter_path="/x/carter",
        false_path=FALSE,
    )


def isolated(
    doc: dict, base: dict[str, str] | None = None, *, block: bool = False, pat: str | None = None
):
    env = {**os.environ, **(base or {})}
    return apply_isolation(env, doc, pat, block_commits=block)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    assert git("init", "-q", "-b", "main", cwd=path).returncode == 0
    assert git("commit", "-q", "--allow-empty", "-m", "base", cwd=path).returncode == 0
    return path


def commits(repo: Path) -> int:
    return int(git("rev-list", "--count", "HEAD", cwd=repo).stdout)


def tags(repo: Path) -> list[str]:
    return git("tag", "--list", cwd=repo).stdout.split()


@pytest.fixture
def ssh_key(tmp_path: Path, real_ssh_keygen: None) -> Path:
    key = tmp_path / "keys" / "id_ed25519"
    key.parent.mkdir()
    done = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return key


@pytest.fixture
def pgp_key() -> Iterator[tuple[str, str]]:
    """A passphrase-less OpenPGP key in a throwaway GNUPGHOME (short path: agent sockets)."""
    if shutil.which("gpg") is None:
        pytest.skip("gpg is not installed")
    home = tempfile.mkdtemp(prefix="g", dir="/tmp")
    os.chmod(home, 0o700)
    env = {**os.environ, "GNUPGHOME": home}
    gen = ["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", ""]
    gen += ["--quick-generate-key", "Fixture <fixture@example.invalid>", "ed25519", "sign", "never"]
    made = subprocess.run(gen, env=env, capture_output=True, text=True, timeout=60)
    if made.returncode != 0:
        pytest.skip(f"cannot create a test OpenPGP key: {made.stderr[-200:]}")
    listing = subprocess.run(
        ["gpg", "--batch", "--with-colons", "--list-secret-keys"],
        env=env,
        capture_output=True,
        text=True,
    ).stdout
    fingerprint = next(
        line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
    )
    yield home, fingerprint
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


SIGNING = [["-S", "-m", "x"], ["--gpg-sign", "-m", "x"]]


class TestNoHumanSignatureBelowT2:
    """A bare `-S`, `--gpg-sign` and `git tag -s` fail instead of reaching the
    human's key. The block is tier-independent, so T0, T1 and a `max_tier` cap share it."""

    @pytest.mark.parametrize("tier", ["t0", "t1", "t1-by-cap"])
    @pytest.mark.parametrize("flags", SIGNING, ids=["-S", "--gpg-sign"])
    def test_ssh_key_file_without_a_passphrase(
        self, doc: dict, repo: Path, ssh_key: Path, tier: str, flags: list[str]
    ) -> None:
        git("config", "gpg.format", "ssh", cwd=repo)
        git("config", "user.signingkey", str(ssh_key), cwd=repo)
        before = commits(repo)
        env = isolated(doc).env
        done = git("commit", "--allow-empty", *flags, cwd=repo, env=env)
        assert done.returncode != 0, tier
        assert commits(repo) == before

    def test_tag_dash_s_with_an_ssh_key(self, doc: dict, repo: Path, ssh_key: Path) -> None:
        git("config", "gpg.format", "ssh", cwd=repo)
        git("config", "user.signingkey", str(ssh_key), cwd=repo)
        done = git("tag", "-s", "v1", "-m", "x", cwd=repo, env=isolated(doc).env)
        assert done.returncode != 0 and tags(repo) == []

    @pytest.mark.parametrize("flags", SIGNING, ids=["-S", "--gpg-sign"])
    def test_openpgp_user_signingkey(
        self, doc: dict, repo: Path, pgp_key, flags: list[str]
    ) -> None:
        home, fingerprint = pgp_key
        git("config", "user.signingkey", fingerprint, cwd=repo)
        env = isolated(doc, {"GNUPGHOME": home}).env
        before = commits(repo)
        done = git("commit", "--allow-empty", *flags, cwd=repo, env=env)
        assert done.returncode != 0 and commits(repo) == before

    def test_control_the_same_key_signs_without_the_block(self, repo: Path, pgp_key) -> None:
        home, fingerprint = pgp_key
        git("config", "user.signingkey", fingerprint, cwd=repo)
        env = {**os.environ, "GNUPGHOME": home}
        done = git("commit", "--allow-empty", "-S", "-m", "x", cwd=repo, env=env)
        assert done.returncode == 0, done.stderr
        assert "gpgsig" in git("cat-file", "-p", "HEAD", cwd=repo).stdout

    def test_tag_dash_s_with_openpgp(self, doc: dict, repo: Path, pgp_key) -> None:
        home, fingerprint = pgp_key
        git("config", "user.signingkey", fingerprint, cwd=repo)
        done = git(
            "tag", "-s", "v1", "-m", "x", cwd=repo, env=isolated(doc, {"GNUPGHOME": home}).env
        )
        assert done.returncode != 0 and tags(repo) == []

    def test_a_plain_commit_succeeds_unsigned_even_when_the_user_config_says_sign(
        self, doc: dict, repo: Path, ssh_key: Path
    ) -> None:
        git("config", "gpg.format", "ssh", cwd=repo)
        git("config", "user.signingkey", str(ssh_key), cwd=repo)
        git("config", "commit.gpgsign", "true", cwd=repo)
        env = isolated(doc).env
        done = git("commit", "--allow-empty", "-m", "plain", cwd=repo, env=env)
        assert done.returncode == 0, done.stderr
        assert git("cat-file", "-p", "HEAD", cwd=repo).stdout.count("gpgsig") == 0

    def test_the_human_shell_without_the_block_still_signs(
        self, repo: Path, ssh_key: Path, tmp_path: Path
    ) -> None:
        """Item 5: the same repository, no block: the user's own config signs as before."""
        allowed = tmp_path / "allowed_signers"
        pub = ssh_key.with_suffix(".pub").read_text().split()
        allowed.write_text(f"human@example.invalid {pub[0]} {pub[1]}\n")
        git("config", "gpg.format", "ssh", cwd=repo)
        git("config", "user.signingkey", str(ssh_key), cwd=repo)
        git("config", "commit.gpgsign", "true", cwd=repo)
        done = git("commit", "--allow-empty", "-m", "signed", cwd=repo)
        assert done.returncode == 0, done.stderr
        assert "gpgsig" in git("cat-file", "-p", "HEAD", cwd=repo).stdout


class TestBlockedCommits:
    """The blocking entries make every commit fail, never unsigned."""

    def test_a_plain_commit_fails_and_creates_nothing(self, doc: dict, repo: Path) -> None:
        before = commits(repo)
        env = isolated(doc, block=True).env
        done = git("commit", "--allow-empty", "-m", "x", cwd=repo, env=env)
        assert done.returncode != 0
        assert commits(repo) == before

    def test_even_with_a_passphraseless_key_configured(
        self, doc: dict, repo: Path, ssh_key: Path
    ) -> None:
        git("config", "user.signingkey", str(ssh_key), cwd=repo)
        before = commits(repo)
        env = isolated(doc, block=True).env
        assert git("commit", "--allow-empty", "-m", "x", cwd=repo, env=env).returncode != 0
        assert commits(repo) == before

    def test_the_signing_program_stays_the_resolved_false(self, doc: dict, repo: Path) -> None:
        env = isolated(doc, block=True).env
        assert git("config", "--get", "gpg.ssh.program", cwd=repo, env=env).stdout.strip() == FALSE
        assert git("config", "--get", "commit.gpgsign", cwd=repo, env=env).stdout.strip() == "true"

    def test_other_git_commands_still_work(self, doc: dict, repo: Path) -> None:
        env = isolated(doc, block=True).env
        assert git("status", "--short", cwd=repo, env=env).returncode == 0
        assert git("log", "--oneline", cwd=repo, env=env).returncode == 0


class TestCountAppend:
    @staticmethod
    def pairs(*kv: tuple[str, str]) -> dict[str, str]:
        env = {"GIT_CONFIG_COUNT": str(len(kv))}
        for i, (k, v) in enumerate(kv):
            env[f"GIT_CONFIG_KEY_{i}"] = k
            env[f"GIT_CONFIG_VALUE_{i}"] = v
        return env

    def scopes(self, repo: Path, env: dict[str, str], key: str) -> list[str]:
        out = git("config", "--show-scope", "--get-all", key, cwd=repo, env=env).stdout
        return [line.split("\t")[0] for line in out.splitlines()]

    def test_entries_are_command_scope_and_git_stays_usable(self, doc: dict, repo: Path) -> None:
        for base in (
            {},
            {"GIT_CONFIG_COUNT": "0"},
            self.pairs(("a.b", "1"), ("c.d", "2"), ("e.f", "3")),
        ):
            result = isolated(doc, base)
            assert result.flags == ["pat-dummy"]
            env = result.env
            assert git("status", cwd=repo, env=env).returncode == 0
            assert "command" in self.scopes(repo, env, "commit.gpgsign")
            assert (
                git("config", "--get", "remote.origin.pushurl", cwd=repo, env=env).stdout.strip()
                == "no_push"
            )

    def test_inherited_entries_are_kept_and_ours_come_after(self, doc: dict, repo: Path) -> None:
        env = isolated(doc, self.pairs(("user.nickname", "mine"), ("a.b", "1"), ("c.d", "2"))).env
        assert git("config", "--get", "user.nickname", cwd=repo, env=env).stdout.strip() == "mine"
        assert env["GIT_CONFIG_KEY_3"] == "credential.helper"  # appended at index N = 3

    def test_on_a_collision_carters_later_entry_wins(self, doc: dict, repo: Path) -> None:
        env = isolated(doc, self.pairs(("commit.gpgsign", "true"))).env
        assert git("config", "--get", "commit.gpgsign", cwd=repo, env=env).stdout.strip() == "false"

    @pytest.mark.parametrize(
        "bad",
        [
            {"GIT_CONFIG_COUNT": "abc"},
            {"GIT_CONFIG_COUNT": "-1"},
            {"GIT_CONFIG_COUNT": ""},
            {"GIT_CONFIG_COUNT": "1001"},
            {"GIT_CONFIG_COUNT": "99999999999999"},
            {"GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "1"},
            {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "nodot", "GIT_CONFIG_VALUE_0": "1"},
        ],
        ids=["abc", "negative", "empty", "over-cap", "huge", "keys-missing", "no-dot"],
    )
    def test_a_malformed_inherited_count_is_replaced_and_commits_are_blocked(
        self, doc: dict, repo: Path, bad: dict[str, str]
    ) -> None:
        if bad["GIT_CONFIG_COUNT"] == "":
            bad = {**bad, "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "1"}  # "empty with keys"
        # the inherited environment is unusable for git on its own ...
        raw = {**os.environ, **bad}
        if bad["GIT_CONFIG_COUNT"] != "":
            assert git("status", cwd=repo, env=raw).returncode == 128
        result = isolated(doc, bad)
        assert "count-malformed" in result.flags
        env = result.env
        # ... after the block it works, with a fresh count and the commit-blocking entries
        assert git("status", cwd=repo, env=env).returncode == 0
        before = commits(repo)
        assert git("commit", "--allow-empty", "-m", "x", cwd=repo, env=env).returncode != 0
        assert commits(repo) == before

    def test_an_inherited_config_parameters_is_deleted_so_dash_c_state_cannot_win(
        self, doc: dict, repo: Path
    ) -> None:
        inherited = {"GIT_CONFIG_PARAMETERS": "'commit.gpgsign=true'"}
        assert (
            git(
                "config", "--get", "commit.gpgsign", cwd=repo, env={**os.environ, **inherited}
            ).stdout.strip()
            == "true"
        )
        env = isolated(doc, inherited).env
        assert "GIT_CONFIG_PARAMETERS" not in env
        assert git("config", "--get", "commit.gpgsign", cwd=repo, env=env).stdout.strip() == "false"


class TestPush:
    GITHUB_FORMS = [
        "https://github.com/o/r.git",
        "git@github.com:o/r.git",
        "ssh://git@github.com/o/r.git",
    ]

    @pytest.mark.parametrize("url", GITHUB_FORMS)
    def test_a_push_to_a_github_remote_fails_locally_and_fetch_is_https(
        self, doc: dict, repo: Path, url: str
    ) -> None:
        git("remote", "add", "origin", url, cwd=repo)
        env = isolated(doc).env
        assert (
            git("ls-remote", "--get-url", "origin", cwd=repo, env=env).stdout.strip()
            == "https://github.com/o/r.git"
        )
        done = git("push", "origin", "HEAD:refs/heads/x", cwd=repo, env=env)
        assert done.returncode == 128 and "no_push" in done.stderr

    def test_origin_pointing_at_a_file_remote_is_stopped_too(
        self, doc: dict, repo: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "o.git"
        git("init", "-q", "--bare", str(bare))
        git("remote", "add", "origin", str(bare), cwd=repo)
        assert git("push", "origin", "HEAD:refs/heads/x", cwd=repo).returncode == 0  # human shell
        done = git("push", "origin", "HEAD:refs/heads/y", cwd=repo, env=isolated(doc).env)
        assert done.returncode == 128 and "no_push" in done.stderr

    def test_a_non_origin_file_remote_is_a_documented_residual(
        self, doc: dict, repo: Path, tmp_path: Path
    ) -> None:
        """Not stopped by the block: pre-push, the gate and the PAT's 403 cover these."""
        bare = tmp_path / "other.git"
        git("init", "-q", "--bare", str(bare))
        git("remote", "add", "other", str(bare), cwd=repo)
        assert (
            git("push", "other", "HEAD:refs/heads/z", cwd=repo, env=isolated(doc).env).returncode
            == 0
        )


class TestCredentialHelper:
    @pytest.fixture
    def with_system_helper(self, tmp_path: Path) -> tuple[dict[str, str], Path]:
        called = tmp_path / "system-helper-called"
        system = tmp_path / "system-gitconfig"
        system.write_text(
            f'[credential]\n\thelper = "!f() {{ echo called >> {called}; echo username=sys; '
            'echo password=SYSTEM-HELPER; }; f"\n'
        )
        return {"GIT_CONFIG_SYSTEM": str(system), "GIT_CONFIG_NOSYSTEM": "0"}, called

    def fill(self, host: str, repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return git(
            "credential", "fill", cwd=repo, env=env, stdin=f"protocol=https\nhost={host}\n\n"
        )

    def test_github_com_gets_the_token_and_others_nothing_even_with_a_system_helper_first(
        self, doc: dict, repo: Path, with_system_helper
    ) -> None:
        base, called = with_system_helper
        token = fine_grained("HELPER")
        assert (
            "SYSTEM-HELPER" in self.fill("github.com", repo, {**os.environ, **base}).stdout
        )  # control
        called.unlink()
        env = isolated(doc, base, pat=token).env
        ok = self.fill("github.com", repo, env)
        assert (
            ok.returncode == 0
            and f"password={token}" in ok.stdout
            and "username=x-access-token" in ok.stdout
        )
        for other in ("gitlab.com", "api.github.com", "github.com.evil.example"):
            denied = self.fill(other, repo, env)
            assert denied.returncode == 128 and token not in denied.stdout, other
        assert not called.exists()

    def test_the_dummy_is_offered_when_there_is_no_token(self, doc: dict, repo: Path) -> None:
        env = isolated(doc).env
        assert (
            f"password={doc['plugin']['gh_token_dummy']}"
            in self.fill("github.com", repo, env).stdout
        )

    def test_the_token_is_never_in_a_config_value(self, doc: dict) -> None:
        token = fine_grained("NEVERINCONFIG")
        env = isolated(
            doc,
            {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "x"},
            pat=token,
        ).env
        assert env["GH_TOKEN"] == token
        offenders = [k for k, v in env.items() if k != "GH_TOKEN" and token in v]
        assert offenders == []
        assert token not in isolation.canonical_bytes(doc).decode()
