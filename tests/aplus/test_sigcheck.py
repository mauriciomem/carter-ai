"""The shared signature choke point: every commit
in the range whose committer is the LLM must verify (``%G?`` = ``G``) with a key whose
``%GF`` fingerprint is one Carter stored. Real throwaway ed25519 keys, in tmp only."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from aplus.helpers import git
from carter.aplus import run, sigcheck
from carter.aplus.findings import Finding
from carter.identity import IdentityError
from carter.identity.errors import E_B_UNSIGNED
from carter.identity.schema import Identity, IdentityConfig, Signing

LLM = "4242+llm-bot@users.noreply.github.com"
HUMAN = "human@example.invalid"


class Keys:
    def __init__(self, tmp: Path, bindir: str) -> None:
        self.tmp, self.bindir = tmp, bindir
        self.made: dict[str, tuple[Path, str]] = {}

    def make(self, name: str) -> tuple[Path, str]:
        priv = self.tmp / f"key-{name}"
        proc = run.run(
            [
                f"{self.bindir}/ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                name,
                "-f",
                str(priv),
            ]
        )
        assert proc.returncode == 0, proc.stderr
        pub = " ".join((self.tmp / f"key-{name}.pub").read_text().split()[:2])
        self.made[name] = (priv, pub)
        return priv, pub


@pytest.fixture
def keys(tmp_path: Path, ssh_keygen_dir: str) -> Keys:
    d = tmp_path / "keys"
    d.mkdir()
    return Keys(d, ssh_keygen_dir)


@pytest.fixture
def signing_repo(tmp_path: Path, ssh_keygen_dir: str) -> Path:
    from aplus.helpers import make_repo

    repo = make_repo(tmp_path / "srepo")
    git("config", "user.name", "T", cwd=repo)
    git("config", "user.email", HUMAN, cwd=repo)
    git("config", "gpg.format", "ssh", cwd=repo)
    git("config", "gpg.ssh.program", f"{ssh_keygen_dir}/ssh-keygen", cwd=repo)
    return repo


def commit(repo: Path, name: str, *, as_llm: bool, key: Path | None = None) -> str:
    (repo / name).write_text(name)
    git("add", name, cwd=repo)
    env = {"GIT_COMMITTER_EMAIL": LLM, "GIT_COMMITTER_NAME": "LLM"} if as_llm else {}
    args = ["commit", "-q", "-m", name]
    if key is not None:
        args = ["-c", f"user.signingkey={key}", "commit", "-q", "-S", "-m", name]
    git(*args, cwd=repo, env=env)
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def ident(*pubs: str, bindir: str) -> sigcheck.SigIdentity:
    return sigcheck.SigIdentity(email=LLM, public_keys=tuple(pubs), ssh_bin_dir=bindir)


def codes(findings: list[Finding]) -> set[str]:
    return {f.code for f in findings}


class TestAllowedSigners:
    def test_one_line_per_key_in_the_documented_format(self) -> None:
        text = sigcheck.build_allowed_signers(
            sigcheck.SigIdentity(
                LLM, ("ssh-ed25519 AAAAcur comment-dropped", "sk-ssh-ed25519@openssh.com AAAAold")
            )
        )
        assert text.splitlines() == [
            f'{LLM} namespaces="git" ssh-ed25519 AAAAcur',
            f'{LLM} namespaces="git" sk-ssh-ed25519@openssh.com AAAAold',
        ]

    def test_garbage_keys_are_skipped_not_written(self) -> None:
        text = sigcheck.build_allowed_signers(
            sigcheck.SigIdentity(LLM, ("", "just-one-token", "a b c d"))
        )
        assert text.splitlines() == [f'{LLM} namespaces="git" a b']

    def test_an_email_with_whitespace_is_refused(self) -> None:
        with pytest.raises(ValueError):
            sigcheck.build_allowed_signers(sigcheck.SigIdentity("a b@c", ("x y",)))


class TestFromConfig:
    def test_t0_and_t1_have_nothing_to_check(self) -> None:
        assert sigcheck.SigIdentity.from_config(IdentityConfig()) is None
        t1 = IdentityConfig(identity=Identity(login="llm-bot", id=4242))
        assert sigcheck.SigIdentity.from_config(t1) is None

    def test_t2_gives_email_current_and_previous_keys_and_the_ssh_dir(self) -> None:
        t2 = IdentityConfig(
            identity=Identity(login="llm-bot", id=4242),
            signing=Signing(
                public_key="ssh-ed25519 AAAAcur",
                fingerprint="SHA256:abc",
                previous_public_keys=("ssh-ed25519 AAAAold",),
                ssh_bin_dir="/opt/openssh/bin",
            ),
        )
        got = sigcheck.SigIdentity.from_config(t2)
        assert got == sigcheck.SigIdentity(
            LLM, ("ssh-ed25519 AAAAcur", "ssh-ed25519 AAAAold"), "/opt/openssh/bin", ("SHA256:abc",)
        )


class TestVerification:
    def test_a_commit_signed_with_the_current_key_passes(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        priv, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True, key=priv)
        assert sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir)) == []

    def test_an_unsigned_llm_commit_is_refused_with_its_sha(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        _, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True)
        (f,) = sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir))
        assert (f.code, f.scope, f.key) == (E_B_UNSIGNED, "commit", c) and "not signed" in f.reason

    def test_a_commit_signed_with_a_wrong_key_is_refused(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        _, pub = keys.make("cur")
        stranger, _ = keys.make("stranger")
        c = commit(signing_repo, "a", as_llm=True, key=stranger)
        (f,) = sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir))
        assert f.key == c and codes([f]) == {E_B_UNSIGNED}

    def test_a_previous_key_still_passes_after_rotation(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        old, old_pub = keys.make("old")
        _, new_pub = keys.make("new")
        c = commit(signing_repo, "a", as_llm=True, key=old)
        assert (
            sigcheck.check_signatures(
                signing_repo, [c], ident(new_pub, old_pub, bindir=ssh_keygen_dir)
            )
            == []
        )

    def test_a_rotated_out_key_is_refused(self, signing_repo, keys, ssh_keygen_dir) -> None:
        old, _ = keys.make("old")
        _, new_pub = keys.make("new")
        c = commit(signing_repo, "a", as_llm=True, key=old)
        assert [
            f.key
            for f in sigcheck.check_signatures(
                signing_repo, [c], ident(new_pub, bindir=ssh_keygen_dir)
            )
        ] == [c]

    def test_human_committed_commits_are_ignored_signed_or_not(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        priv, pub = keys.make("cur")
        stranger, _ = keys.make("stranger")
        a = commit(signing_repo, "a", as_llm=False)
        b = commit(signing_repo, "b", as_llm=False, key=stranger)
        assert (
            sigcheck.check_signatures(signing_repo, [a, b], ident(pub, bindir=ssh_keygen_dir)) == []
        )

    def test_only_the_bad_commits_in_a_mixed_range_are_listed(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        priv, pub = keys.make("cur")
        good = commit(signing_repo, "g", as_llm=True, key=priv)
        human = commit(signing_repo, "h", as_llm=False)
        bad = commit(signing_repo, "b", as_llm=True)
        found = sigcheck.check_signatures(
            signing_repo, [good, human, bad], ident(pub, bindir=ssh_keygen_dir)
        )
        assert [f.key for f in found] == [bad]

    def test_committer_email_matching_ignores_case(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        priv, pub = keys.make("cur")
        (signing_repo / "a").write_text("a")
        git("add", "a", cwd=signing_repo)
        git("-c", f"user.signingkey={priv}", "commit", "-q", "-S", "-m", "a", cwd=signing_repo,
            env={"GIT_COMMITTER_EMAIL": LLM.upper()})  # fmt: skip
        c = git("rev-parse", "HEAD", cwd=signing_repo).stdout.strip()
        assert sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir)) == []

    def test_no_identity_means_nothing_to_check(self, signing_repo) -> None:
        c = commit(signing_repo, "a", as_llm=True)
        assert sigcheck.check_signatures(signing_repo, [c], None) == []

    def test_an_empty_range_passes(self, signing_repo, keys, ssh_keygen_dir) -> None:
        _, pub = keys.make("cur")
        assert sigcheck.check_signatures(signing_repo, [], ident(pub, bindir=ssh_keygen_dir)) == []

    def test_no_agent_is_needed(self, signing_repo, keys, ssh_keygen_dir, monkeypatch) -> None:
        priv, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True, key=priv)
        monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
        assert sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir)) == []

    def test_a_polluted_config_cannot_make_it_trust_a_different_signers_file(
        self, signing_repo, keys, ssh_keygen_dir, monkeypatch
    ) -> None:
        priv, pub = keys.make("cur")
        stranger, stranger_pub = keys.make("stranger")
        c = commit(signing_repo, "a", as_llm=True, key=stranger)
        evil = keys.tmp / "evil_signers"
        evil.write_text(f'{LLM} namespaces="git" {stranger_pub}\n')
        git("config", "gpg.ssh.allowedSignersFile", str(evil), cwd=signing_repo)
        found = sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir))
        assert [f.key for f in found] == [c]  # our -c wins over the repo's setting

    def test_the_configured_ssh_dir_is_used_not_path(
        self, signing_repo, keys, tmp_path, monkeypatch
    ) -> None:
        priv, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True, key=priv)
        empty = tmp_path / "no-ssh-here"
        empty.mkdir()
        with pytest.raises(sigcheck.SigCheckError, match="ssh-keygen"):
            sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=str(empty)))


class TestTempFile:
    def test_it_is_0600_in_a_0700_dir_and_gone_afterwards(
        self, signing_repo, keys, ssh_keygen_dir, tmp_path, monkeypatch
    ) -> None:
        priv, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True, key=priv)
        root = tmp_path / "scratch"
        root.mkdir()
        seen: dict[str, int] = {}
        real = run.git

        def spy(args, cwd, **kw):
            for arg in kw.get("config", ()):
                if arg.startswith("gpg.ssh.allowedSignersFile="):
                    f = Path(arg.split("=", 1)[1])
                    seen["file"] = stat.S_IMODE(f.stat().st_mode)
                    seen["dir"] = stat.S_IMODE(f.parent.stat().st_mode)
            return real(args, cwd, **kw)

        monkeypatch.setattr(run, "git", spy)
        sigcheck.check_signatures(
            signing_repo, [c], ident(pub, bindir=ssh_keygen_dir), tmp_root=root
        )
        assert seen == {"file": 0o600, "dir": 0o700}
        assert list(root.iterdir()) == []

    def test_it_is_deleted_when_the_check_raises(
        self, signing_repo, keys, ssh_keygen_dir, tmp_path, monkeypatch
    ) -> None:
        _, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True)
        root = tmp_path / "scratch"
        root.mkdir()

        def boom(*_a, **_k):
            raise run.RunError("git timed out")

        monkeypatch.setattr(run, "git", boom)
        with pytest.raises(sigcheck.SigCheckError):
            sigcheck.check_signatures(
                signing_repo, [c], ident(pub, bindir=ssh_keygen_dir), tmp_root=root
            )
        assert list(root.iterdir()) == []

    def test_hardening_and_signature_overrides_are_passed(
        self, signing_repo, keys, ssh_keygen_dir, monkeypatch
    ) -> None:
        _, pub = keys.make("cur")
        c = commit(signing_repo, "a", as_llm=True)
        calls: list[tuple] = []
        real = run.git

        def spy(args, cwd, **kw):
            calls.append((tuple(args), tuple(kw.get("config", ()))))
            return real(args, cwd, **kw)

        monkeypatch.setattr(run, "git", spy)
        sigcheck.check_signatures(signing_repo, [c], ident(pub, bindir=ssh_keygen_dir))
        (_, config), *_ = [x for x in calls if "log" in x[0]]
        joined = " ".join(config)
        assert (
            "gpg.format=ssh" in joined and f"gpg.ssh.program={ssh_keygen_dir}/ssh-keygen" in joined
        )


class TestError:
    def test_the_error_lists_short_shas_and_nothing_else(
        self, signing_repo, keys, ssh_keygen_dir
    ) -> None:
        _, pub = keys.make("cur")
        shas = [commit(signing_repo, f"u{i}", as_llm=True) for i in range(2)]
        err = sigcheck.to_error(
            sigcheck.check_signatures(signing_repo, shas, ident(pub, bindir=ssh_keygen_dir))
        )
        assert isinstance(err, IdentityError) and err.code == E_B_UNSIGNED
        assert all(s[:12] in str(err) for s in shas) and "refused" in str(err)
        assert sigcheck.to_error([]) is None
