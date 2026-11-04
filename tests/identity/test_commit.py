# ruff: noqa: E501
"""``carter commit``, the core (plan 005 step 21; RFC-0007 §4.3; D26, D36, D57, D64; freeze H14).

Real git, throwaway keys and a real throwaway agent. The human's own signing setup is a decoy at
every tier (its private key is made unreadable): any use of it fails the test.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from carter import identity_add
from carter.identity import commit
from carter.identity.commit import (
    REFUSED_FLAGS,
    CommitRefused,
    Plan,
    plan_commit,
    run_git,
    screen_args,
)
from carter.identity.config import load_identity
from carter.identity.errors import (
    E_CONFIG,
    E_SIGN_AGENT_REFUSE,
    E_TIER_REQUIRED,
    IdentityError,
)
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace
from carter.identity.writer import write_config
from gh_api import FakeGitHub, Reply
from ssh_rig import KeyPair, real_ssh

LOGIN, UID = "octocat", 583231
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
COAUTHOR = f"Co-authored-by: {LOGIN} <{EMAIL}>"
HUMAN = ("Hu Man", "human@example.invalid")


class TestScreen:
    @pytest.mark.parametrize(
        "args",
        [
            ["--no-verify"],
            ["-n"],
            ["--no-gpg-sign"],
            ["-Skeyid"],
            ["--gpg-sign=key"],
            ["-s"],
            ["--signoff"],
            ["--author=x <x@y>"],
            ["--author", "x <x@y>"],
            ["-an"],
            ["-nm", "msg"],
            ["-m", "x", "-s"],
            ["-aS1"],
        ],
    )
    def test_refused_flags(self, args: list[str]) -> None:
        with pytest.raises(CommitRefused) as err:
            screen_args(args)
        assert "does not accept" in str(err.value) and "git commit" in str(err.value)

    @pytest.mark.parametrize(
        "flag",
        ["--no-verif", "--no-ver", "--no-v", "--no-", "--no", "--n", "--no-gpg-s", "--no-gpg",
         "--gpg-s=KEYID", "--gpg=KEYID", "--gp=K", "--g=K", "--gpg-sig", "--auth=x <x@y>", "--au=x",
         "--a=x", "--sign", "--signo", "--s"],
    )  # fmt: skip
    def test_git_accepts_unambiguous_abbreviations_so_they_are_refused_too(self, flag: str) -> None:
        """Found by the step-29 review: only the spelled-out names were refused, so
        `--gpg-s=<keyid>` would have signed with the human's key."""
        with pytest.raises(CommitRefused):
            screen_args([flag, "-m", "x"])

    @pytest.mark.parametrize(
        "flag",
        ["--amend", "--all", "--allow-empty", "--no-edit", "--no-signoff", "--short", "--status",
         "--squash=HEAD", "--reset-author", "--reuse-message=HEAD", "--trailer=A: b", "--message=x",
         "--fixup=HEAD", "--dry-run", "--quiet", "--verbose", "--only", "--include", "--cleanup=strip"],
    )  # fmt: skip
    def test_legitimate_long_options_that_look_similar_pass(self, flag: str) -> None:
        assert screen_args([flag])[0] == [flag]

    @pytest.mark.parametrize(
        ("args", "kept"),
        [
            (["-a", "-m", "x"], ["-a", "-m", "x"]),
            (
                ["--reset-author", "--amend", "--no-edit"],
                ["--reset-author", "--amend", "--no-edit"],
            ),
            (["-m", "-n is text"], ["-m", "-n is text"]),  # the value of -m is not a flag
            (["-m", "--no-verify"], ["-m", "--no-verify"]),
            (["-mhello", "-a"], ["-mhello", "-a"]),
            (["--message=--author", "f"], ["--message=--author", "f"]),
            (["-m", "x", "--", "-n", "-s"], ["-m", "x", "--", "-n", "-s"]),  # after -- are paths
            (
                ["--trailer", "Signed-off-by: x", "-F", "-"],
                ["--trailer", "Signed-off-by: x", "-F", "-"],
            ),
            (["-uno", "-q"], ["-uno", "-q"]),
        ],
    )
    def test_everything_else_passes_through_untouched(
        self, args: list[str], kept: list[str]
    ) -> None:
        assert screen_args(args) == (kept, [])

    @pytest.mark.parametrize(
        ("args", "kept"),
        [(["-S", "-m", "x"], ["-m", "x"]), (["--gpg-sign", "-a"], ["-a"]), (["-aS"], ["-a"])],
    )
    def test_a_bare_dash_capital_s_is_dropped_with_a_note(
        self, args: list[str], kept: list[str]
    ) -> None:
        got, notes = screen_args(args)
        assert got == kept and len(notes) == 1 and "your key is never used" in notes[0]

    def test_the_refused_list_is_the_frozen_one(self) -> None:
        assert REFUSED_FLAGS == (
            "--no-verify",
            "-n",
            "--no-gpg-sign",
            "-S<arg>",
            "--gpg-sign=<arg>",
            "-s",
            "--signoff",
            "--author",
        )


def cfg_of(tier: str, **over: object) -> IdentityConfig:
    sign = (
        Signing(
            public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY",
            fingerprint="SHA256:wrong",
        )
        if tier == "t2"
        else Signing()
    )
    ident = Identity(login=LOGIN, id=UID, email=EMAIL, name=LOGIN) if tier != "t0" else Identity()
    return IdentityConfig(identity=ident, signing=sign, state="current", **over)  # type: ignore[arg-type]


def plan(
    cfg: IdentityConfig, *args: str, agent: bool = False, tty: bool = True, offer=None, env=None
) -> Plan:  # type: ignore[no-untyped-def]
    return plan_commit(
        list(args),
        cfg=cfg,
        env=env or {},
        cwd=os.getcwd(),
        home=Path(os.environ["HOME"]),
        agent=agent,
        human_tty=tty,
        offer_unlock=offer,
    )


class TestPlanBelowT2:
    def test_t1_is_unsigned_with_the_trailer_the_four_programs_and_a_warning(self) -> None:
        got = plan(cfg_of("t1"), "-m", "x")
        assert got.shape == "unsigned" and got.argv[-4:] == ["-m", "x", "--trailer", COAUTHOR]
        assert got.argv[:2] == ["-c", "commit.gpgsign=false"]
        programs = [a for a in got.argv if a.startswith("gpg.") and "program=" in a]
        assert [p.split("=")[0] for p in programs] == [
            "gpg.program",
            "gpg.openpgp.program",
            "gpg.x509.program",
            "gpg.ssh.program",
        ]
        assert all(p.split("=")[1] in ("/usr/bin/false", "/bin/false") for p in programs)
        assert got.argv.index("commit") > got.argv.index("-c")  # -c entries come before the verb
        assert got.warnings and got.warnings[0].startswith("E-COMMIT-T1")

    def test_the_trailer_goes_before_the_double_dash_not_into_the_paths(self) -> None:
        got = plan(cfg_of("t1"), "-m", "--", "--", "a.txt", "--trailer")
        assert got.argv[-7:] == ["-m", "--", "--trailer", COAUTHOR, "--", "a.txt", "--trailer"]

    def test_t0_credits_assisted_by_without_an_email(self) -> None:
        got = plan(cfg_of("t0"), "-m", "x")
        assert got.argv[-2:] == ["--trailer", "Assisted-by: Carter"] and not got.warnings
        assert any("T0" in n for n in got.notes)

    def test_a_cap_makes_the_effective_tier_the_cap(self, tmp_path: Path) -> None:
        cfg = cfg_of("t2", workspaces={str(tmp_path): Workspace(max_tier="t1")})
        got = plan_commit(
            ["-m", "x"],
            cfg=cfg,
            env={},
            cwd=str(tmp_path),
            home=Path(os.environ["HOME"]),
            agent=False,
            human_tty=True,
        )
        assert got.shape == "unsigned" and got.warnings[0].startswith("E-COMMIT-T1")

    def test_the_environment_is_scrubbed_of_identity_and_config_overrides(self) -> None:
        env = {
            "GIT_AUTHOR_NAME": "evil",
            "GIT_COMMITTER_EMAIL": "evil@x",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "a.b",
            "GIT_CONFIG_VALUE_0": "c",
            "GIT_CONFIG_PARAMETERS": "'a.b=c'",
            "CARTER_IDENTITY": "x",
            "SSH_AUTH_SOCK": "/home/h/agent",
            "KEEP": "1",
            "GIT_CONFIG_GLOBAL": "/g",
        }
        got = plan(cfg_of("t1"), "-m", "x", env=env)
        assert got.env == {"KEEP": "1", "GIT_CONFIG_GLOBAL": "/g"}

    def test_refusals_come_before_anything_else(self) -> None:
        with pytest.raises(CommitRefused):
            plan(cfg_of("t1"), "--no-verify", "-m", "x")
        with pytest.raises(IdentityError) as err:
            plan(
                IdentityConfig(
                    identity=Identity(login=LOGIN, id=UID, email=EMAIL),
                    signing=Signing(public_key="ssh-ed25519 AAAA"),
                    state="current",
                ),
                "-m",
                "x",
            )
        assert err.value.code == E_CONFIG

    def test_role_author_does_not_refuse_carter_commit_it_ignores_the_role(self) -> None:
        """Plan 006 K9 (D26): the role is for agents; at your terminal you are always the author."""
        role_b = IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL, role="author"), state="current"
        )
        got = plan(role_b, "-m", "x")
        assert (
            got.shape == "unsigned"
        )  # T1 here: nothing to sign with; not an E-ROLE-B-TIER refusal
        assert any("role not applied (own terminal)" in n for n in got.notes)

    def test_an_unmet_require_tier_refuses(self, tmp_path: Path) -> None:
        cfg = cfg_of("t1", workspaces={str(tmp_path): Workspace(require_tier="t2")})
        with pytest.raises(IdentityError) as err:
            plan_commit(
                ["-m", "x"],
                cfg=cfg,
                env={},
                cwd=str(tmp_path),
                home=Path(os.environ["HOME"]),
                agent=False,
                human_tty=True,
            )
        assert err.value.code == E_TIER_REQUIRED and "required t2" in err.value.detail
        capped = cfg_of(
            "t2", workspaces={str(tmp_path): Workspace(max_tier="t1", require_tier="t2")}
        )
        with pytest.raises(IdentityError):
            plan_commit(
                ["-m", "x"],
                cfg=capped,
                env={},
                cwd=str(tmp_path),
                home=Path(os.environ["HOME"]),
                agent=False,
                human_tty=True,
            )


# --- real git, real agent ----------------------------------------------------------------------


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    server = FakeGitHub().start()
    monkeypatch.setenv("GITHUB_API_URL", server.url)
    server.public_world()
    yield server
    server.stop()


class Lab:
    """A T2 identity through the throwaway agent, a repo, and a decoy human signing setup."""

    def __init__(
        self, tmp: Path, key: KeyPair, decoy: KeyPair, sock: str, fake: FakeGitHub
    ) -> None:
        self.home = Path(os.environ["HOME"])
        items = [{"id": 1, "key": key.blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
        fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
        fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))
        identity_add.apply_add(
            identity_add.plan_add(
                identity_add.AddRequest(LOGIN, str(key.pub_path), None, sock, None)
            )
        )
        self.key, self.decoy = key, decoy
        self.repo = tmp / "repo"
        self.repo.mkdir()
        glob = Path(os.environ["GIT_CONFIG_GLOBAL"])
        glob.write_text(
            f"[user]\n\tname = {HUMAN[0]}\n\temail = {HUMAN[1]}\n\tsigningkey = {decoy.path}\n[gpg]\n\tformat = ssh\n[commit]\n\tgpgsign = true\n"
        )
        decoy.path.chmod(0)  # any use of the human's key fails loudly
        self.git("init", "-q", "-b", "main")
        (self.repo / "a").write_text("a\n")
        self.git("add", "a")

    def git(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.repo,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
        )

    def cfg(self) -> IdentityConfig:
        return load_identity(self.home / ".carter" / "config.toml")

    def commit(
        self, *args: str, agent: bool = False, tty: bool = True, offer=None, env=None
    ) -> tuple[int, Plan]:  # type: ignore[no-untyped-def]
        p = plan_commit(
            list(args),
            cfg=self.cfg(),
            env={**os.environ, **(env or {})},
            cwd=str(self.repo),
            home=self.home,
            agent=agent,
            human_tty=tty,
            offer_unlock=offer,
        )
        return run_git(p, str(self.repo)), p

    def show(self, rev: str = "HEAD") -> dict[str, str]:
        allowed = self.home / ".carter" / "hooks" / "allowed_signers"
        shim = self.home / ".carter" / "bin" / "carter-ssh-sign"
        out = self.git(
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.allowedSignersFile={allowed}",
            "-c",
            f"gpg.ssh.program={shim}",
            "log",
            "-1",
            "--format=%G?|%GF|%an <%ae>|%cn <%ce>|%ad|%B",
            "--date=raw",
            rev,
        ).stdout
        status, fpr, author, committer, date, body = out.split("|", 5)
        return {
            "status": status,
            "fpr": fpr,
            "author": author,
            "committer": committer,
            "date": date,
            "body": body,
        }

    def raw(self, rev: str = "HEAD") -> str:
        return self.git("cat-file", "commit", rev).stdout


@pytest.fixture
def lab(
    tmp_path: Path, fake: FakeGitHub, throwaway_key: Callable[..., KeyPair], real_ssh_agent
) -> Lab:  # type: ignore[no-untyped-def]
    key, decoy = throwaway_key("ed25519"), throwaway_key("ed25519")
    out = Lab(tmp_path, key, decoy, str(real_ssh_agent.sock), fake)
    out.agent = real_ssh_agent  # type: ignore[attr-defined]
    yield out  # type: ignore[misc]
    decoy.path.chmod(0o600)


@real_ssh
class TestK1:
    def test_in_a_role_author_config_it_is_still_human_author_and_llm_committer(
        self, lab: Lab
    ) -> None:
        """Plan 006 K9: `carter commit` ignores the role; a polluted GIT_AUTHOR_* changes nothing."""
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        cfg_file = lab.home / ".carter" / "config.toml"
        text = cfg_file.read_text()
        cfg_file.write_text(
            text.replace('role = "co-author"', 'role = "author"')
            if 'role = "co-author"' in text
            else text.replace("[identity]\n", '[identity]\nrole = "author"\n', 1)
        )
        code, plan_ = lab.commit(
            "-m", "ignores the role", env={"GIT_AUTHOR_NAME": "evil", "GIT_AUTHOR_EMAIL": "evil@x"}
        )
        assert code == 0 and plan_.shape == "k1"
        got = lab.show()
        assert got["status"] == "G" and got["author"] == f"{HUMAN[0]} <{HUMAN[1]}>"
        assert got["committer"] == f"{LOGIN} <{EMAIL}>"
        assert any("role not applied" in n for n in plan_.notes)
        assert got["body"].strip().splitlines() == ["ignores the role", "", COAUTHOR]

    def test_a_loaded_key_gives_human_author_llm_committer_good_signature_and_the_trailer(
        self, lab: Lab
    ) -> None:
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        code, plan_ = lab.commit(
            "-m",
            "k1 commit",
            env={
                "GIT_AUTHOR_NAME": "evil",
                "GIT_COMMITTER_EMAIL": "evil@x",
                "SSH_AUTH_SOCK": "/home/h/other",
            },
        )
        assert code == 0 and plan_.shape == "k1"
        got = lab.show()
        assert got["status"] == "G" and got["fpr"] == lab.key.fingerprint
        assert (
            got["author"] == f"{HUMAN[0]} <{HUMAN[1]}>" and got["committer"] == f"{LOGIN} <{EMAIL}>"
        )
        assert got["body"].strip().splitlines() == ["k1 commit", "", COAUTHOR]

    def test_the_role_is_ignored_and_the_message_passes_through_untouched(self, lab: Lab) -> None:
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        msg = lab.repo / "msg.txt"
        msg.write_text("subject\n\nbody with  spaces\n\tand a tab\n")
        code, _ = lab.commit("-F", str(msg))
        assert code == 0
        assert (
            lab.show()["body"]
            == "subject\n\nbody with  spaces\n\tand a tab\n\n" + COAUTHOR + "\n\n"
        )

    def test_amend_keeps_author_and_date_resigns_as_the_llm_and_never_duplicates(
        self, lab: Lab
    ) -> None:
        lab.git(
            "commit",
            "-q",
            "-m",
            "plain human commit",
            env={"GIT_AUTHOR_DATE": "2020-01-02T03:04:05+0000"},
        )
        before = lab.show()
        assert before["status"] == "N"
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        for _ in range(2):
            code, _ = lab.commit("--amend", "--no-edit")
            assert code == 0
        got = lab.show()
        assert (
            got["status"] == "G"
            and got["author"] == before["author"]
            and got["date"] == before["date"]
        )
        assert (
            got["committer"] == f"{LOGIN} <{EMAIL}>" and got["body"].count("Co-authored-by:") == 1
        )

    def test_reset_author_passes_through(self, lab: Lab) -> None:
        lab.git(
            "commit",
            "-q",
            "-m",
            "x",
            env={"GIT_AUTHOR_NAME": "Other", "GIT_AUTHOR_EMAIL": "o@x.invalid"},
        )
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        assert lab.commit("--amend", "--no-edit", "--reset-author")[0] == 0
        assert lab.show()["author"] == f"{HUMAN[0]} <{HUMAN[1]}>"

    def test_the_humans_decoy_key_is_never_touched(self, lab: Lab) -> None:
        assert lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]
        assert (
            lab.commit("-m", "x")[0] == 0
        )  # the decoy private key is mode 000: any use would fail
        assert lab.show()["fpr"] != lab.decoy.fingerprint


@real_ssh
class TestLocked:
    def test_an_agent_shell_refuses_and_nothing_is_created_and_changes_stay_staged(
        self, lab: Lab
    ) -> None:
        with pytest.raises(IdentityError) as err:
            lab.commit("-m", "x", agent=True)
        assert err.value.code == E_SIGN_AGENT_REFUSE and "Changes left staged" in str(err.value)
        assert lab.git("rev-list", "--count", "--all").stdout.strip() in ("0", "")
        assert "A  a" in lab.git("status", "--short").stdout

    def test_a_human_is_offered_the_unlock_once_and_a_no_falls_back_to_unsigned(
        self, lab: Lab
    ) -> None:
        asked: list[int] = []
        code, plan_ = lab.commit("-m", "fallback", offer=lambda: asked.append(1) or False)
        assert code == 0 and asked == [1]
        assert (
            plan_.warnings
            and plan_.warnings[0].startswith("E-SIGN-HUMAN-FALLBACK")
            and "Unverified" in plan_.warnings[0]
        )
        raw = lab.raw()
        assert "gpgsig" not in raw  # never signed, and never by the human's decoy key
        got = lab.show()
        assert got["author"] == got["committer"] == f"{HUMAN[0]} <{HUMAN[1]}>"
        assert got["body"].strip().splitlines()[-1] == COAUTHOR

    def test_a_successful_unlock_continues_as_k1(self, lab: Lab) -> None:
        def unlock() -> bool:
            return lab.agent.add(lab.key) == 0  # type: ignore[attr-defined]

        code, plan_ = lab.commit("-m", "after unlock", offer=unlock)
        assert code == 0 and plan_.shape == "k1" and lab.show()["status"] == "G"

    def test_no_terminal_means_no_offer_and_the_fallback(self, lab: Lab) -> None:
        asked: list[int] = []
        code, plan_ = lab.commit("-m", "x", tty=False, offer=lambda: asked.append(1) or True)
        assert code == 0 and asked == [] and plan_.shape == "unsigned"

    def test_an_amend_with_the_agent_locked_in_an_agent_shell_leaves_the_commit_unchanged(
        self, lab: Lab
    ) -> None:
        lab.git("commit", "-q", "-m", "orig")
        before = lab.git("rev-parse", "HEAD").stdout
        with pytest.raises(IdentityError):
            lab.commit("--amend", "--no-edit", agent=True)
        assert lab.git("rev-parse", "HEAD").stdout == before


@real_ssh
class TestBelowT2WithDecoys:
    def test_t1_with_a_bare_dash_capital_s_and_the_humans_signing_config_is_unsigned_human_human(
        self, lab: Lab
    ) -> None:
        write_config(
            IdentityConfig(
                identity=Identity(login=LOGIN, id=UID, email=EMAIL, name=LOGIN), state="current"
            ),
            lab.home / ".carter" / "config.toml",
        )
        code, plan_ = lab.commit("-S", "-m", "t1")
        assert code == 0, "the decoy key (mode 000) must not have been used"
        assert plan_.notes and "gpgsig" not in lab.raw()
        got = lab.show()
        assert (
            got["author"] == got["committer"] == f"{HUMAN[0]} <{HUMAN[1]}>"
            and COAUTHOR in got["body"]
        )
        assert plan_.warnings[0].startswith("E-COMMIT-T1")

    def test_t0_commits_with_assisted_by_and_never_prompts(self, lab: Lab) -> None:
        write_config(IdentityConfig(state="absent"), lab.home / ".carter" / "config.toml")
        asked: list[int] = []
        code, _ = lab.commit("-m", "t0", offer=lambda: asked.append(1) or True)
        assert (
            code == 0 and not asked and lab.show()["body"].strip().endswith("Assisted-by: Carter")
        )

    def test_git_exit_codes_are_propagated(self, lab: Lab) -> None:
        write_config(IdentityConfig(state="absent"), lab.home / ".carter" / "config.toml")
        lab.git("commit", "-q", "-m", "first")
        code, _ = lab.commit("-m", "nothing staged")
        assert code == 1


def test_commit_module_exports(tmp_path: Path) -> None:
    assert commit.REFUSED_FLAGS and callable(commit.run_git)
