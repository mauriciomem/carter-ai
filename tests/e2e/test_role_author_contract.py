# ruff: noqa: E501, F811
"""Role author on a real isolated OpenCode.

The signing rig (its ``lab`` fixture): a real OpenCode in its own HOME and ports, the mock model, a
loopback-only network namespace, the REAL plugin, gate, ``identity env`` entry, hooks, shim and
dedicated ssh-agent, a throwaway LLM key with a passphrase and a loopback fake GitHub. The human
is ``E2E Human <e2e-human@example.invalid>`` (the rig's git config). Opt-in: ``CARTER_E2E=1``;
2.1.4 required, 2.1.2 through ``CARTER_E2E_OPENCODE_ALT``. No TUI, no real GitHub, no user key.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from e2e.g2 import error_message, run_shell, status, wait_status
from e2e.test_signing_contract import EMAIL, LLM, LOGIN, REFUSED, Lab, lab  # noqa: F401 - lab is a fixture

pytestmark = pytest.mark.e2e

HUMAN_NAME, HUMAN_EMAIL = "E2E Human", "e2e-human@example.invalid"
HUMAN = f"{HUMAN_NAME} <{HUMAN_EMAIL}>"
HUMAN_LINE = f"Co-authored-by: {HUMAN_NAME} <{HUMAN_EMAIL}>"
LLM_LINE = f"Co-authored-by: {LOGIN} <{EMAIL}>"


def pin(lab: Lab, role: str = "author", extra: str = "") -> None:
    """The user's pin in config.toml for the agent's workspace (what `carter update` writes)."""
    config = lab.config()
    original = config.read_text()
    if "[workspaces." in original:
        original = original.split("[workspaces.")[0].rstrip("\n") + "\n"
    config.write_text(
        original + f'\n[workspaces."{lab.rig.ws.resolve()}"]\nrole = "{role}"\n{extra}'
    )
    lab.touch_config()


USER_BLOCK = f"[user]\n\tname = {HUMAN_NAME}\n\temail = {HUMAN_EMAIL}\n"


def set_human(lab: Lab, user_section: str) -> str:
    """Replace only the ``[user]`` section of the human's git config (the hook wiring that ``guard
    install`` added to it stays). Returns the previous text."""
    path = lab.rig.home / ".gitconfig"
    before = path.read_text()
    assert USER_BLOCK in before
    path.write_text(before.replace(USER_BLOCK, user_section))
    return before


def trailers(lab: Lab, rev: str = "HEAD") -> list[str]:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%B", rev],
        cwd=lab.rig.ws,
        env={"HOME": str(lab.rig.home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ln for ln in out.splitlines() if ln.lower().startswith("co-authored-by:")]


class TestRoleBShape:
    def test_a_pinned_role_author_agent_commit_is_l_l_g_with_the_humans_line_and_verifies(
        self, lab: Lab
    ) -> None:
        pin(lab)
        out = lab.agent_commit("role author by the llm")
        assert "rc=0" in out, out
        author, committer, sig, fpr = lab.show().split("|")
        assert (
            author == f"{LOGIN} <{EMAIL}>" == committer
            and sig == "G"
            and fpr == lab.key.fingerprint
        )
        assert trailers(lab) == [HUMAN_LINE]
        verified = subprocess.run(
            ["git", "-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={lab.rig.home / '.carter' / 'hooks' / 'allowed_signers'}", "-c", f"gpg.ssh.program={lab.rig.home / '.carter' / 'bin' / 'carter-ssh-sign'}", "verify-commit", "HEAD"],
            cwd=lab.rig.ws, env={"HOME": str(lab.rig.home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null"}, capture_output=True, text=True,
        )  # fmt: skip
        assert verified.returncode == 0, verified.stderr
        wait_status(lab.rig, "passed")
        assert not {"sign-unavailable", "config-error"} & set(status(lab.rig)[0]["flags"])

    def test_the_precedence_follows_the_real_plugin_cache_a_config_mtime_asks_again(
        self, lab: Lab
    ) -> None:
        assert "rc=0" in lab.agent_commit("role a first")
        assert lab.show().split("|")[0] == HUMAN and trailers(lab) == [LLM_LINE]
        pin(lab, "author")  # the pin wins over the user's co-author default
        assert "rc=0" in lab.agent_commit("now role author")
        assert lab.show().split("|")[0] == f"{LOGIN} <{EMAIL}>" and trailers(lab) == [HUMAN_LINE]
        pin(lab, "co-author")  # pinned back: role a again
        assert "rc=0" in lab.agent_commit("role a again")
        assert lab.show().split("|")[0] == HUMAN and trailers(lab) == [LLM_LINE]

    def test_a_user_default_of_author_is_overridden_by_a_workspace_pin_of_co_author(
        self, lab: Lab
    ) -> None:
        config = lab.config()
        config.write_text(
            config.read_text().replace('role = "co-author"', 'role = "author"')
            if 'role = "co-author"' in config.read_text()
            else config.read_text().replace("[identity]\n", '[identity]\nrole = "author"\n', 1)
        )
        lab.touch_config()
        assert "rc=0" in lab.agent_commit("user default b")
        assert lab.show().split("|")[0] == f"{LOGIN} <{EMAIL}>"
        pin(lab, "co-author")
        assert "rc=0" in lab.agent_commit("pinned a")
        assert lab.show().split("|")[0] == HUMAN


class TestNeverDegrades:
    def failed(self, lab: Lab, message: str) -> str:
        before = lab.count()
        out = lab.agent_commit(message)
        assert "rc=0" not in out and lab.count() == before, out
        assert "f.txt" in lab.staged(), "the changes must stay staged"
        return out

    def test_a_locked_key_a_missing_shim_and_a_corrupt_config_each_fail_with_changes_staged_and_no_llm_authored_commit(
        self, lab: Lab
    ) -> None:
        pin(lab)
        assert "rc=0" in lab.agent_commit("warm")
        lab.lock()
        out = self.failed(lab, "locked")
        assert any(s in out for s in ("Couldn't find key in agent?", "Couldn't get agent socket?"))
        lab.unlock()
        shim = lab.rig.home / ".carter" / "bin" / "carter-ssh-sign"
        kept = shim.read_bytes()
        shim.unlink()
        lab.touch_config()
        self.failed(lab, "shim gone")
        shim.write_bytes(kept)
        shim.chmod(0o755)
        lab.touch_config()
        good = lab.config().read_text()
        lab.config().write_text("schema = 2\n[identity\nbroken")
        lab.touch_config()
        self.failed(lab, "config corrupt")
        lab.config().write_text(good)
        lab.touch_config()
        assert "rc=0" in lab.agent_commit("recovered")
        # across the whole run, every LLM-authored commit carries a signature
        self.all_llm_commits_are_signed(lab)

    def all_llm_commits_are_signed(self, lab: Lab) -> None:
        env = {"HOME": str(lab.rig.home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null"}
        rows = subprocess.run(
            ["git", "log", "--format=%H %ae"],
            cwd=lab.rig.ws,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        for row in rows:
            sha, email = row.split()
            if email == EMAIL:
                raw = subprocess.run(
                    ["git", "cat-file", "commit", sha],
                    cwd=lab.rig.ws,
                    env=env,
                    capture_output=True,
                    text=True,
                ).stdout
                assert "gpgsig" in raw.split("\n\n")[0], sha

    def test_the_ttl_expiring_fails_like_a_lock(self, lab: Lab) -> None:
        pin(lab)
        lab.lock("--all")
        lab.unlock("--ttl", "3")
        assert "rc=0" in lab.agent_commit("inside the ttl")
        time.sleep(5)
        self.failed(lab, "expired")

    @pytest.mark.parametrize("how", ["t1", "cap", "t0"])
    def test_role_author_below_t2_is_refused_not_downgraded(self, lab: Lab, how: str) -> None:
        pin(lab)
        config = lab.config()
        text = config.read_text()
        try:
            self.below_t2(lab, how, text)
        finally:
            config.write_text(text)  # so the fixture can lock the agent it started
            lab.touch_config()

    def below_t2(self, lab: Lab, how: str, text: str) -> None:
        config = lab.config()
        if how == "t1":
            config.write_text(
                text.split("[identity.signing]")[0] + text[text.index("[workspaces.") :]
            )
        elif how == "cap":
            config.write_text(text.rstrip("\n") + '\nmax_tier = "t1"\n')
        else:
            # T0 has no identity at all, so no role: the commit is the plain unsigned human one
            config.write_text("schema = 2\n")
            lab.touch_config()
            upd = lab.carter_plain(
                "update", str(lab.rig.base / "proj"), "--yes"
            )  # the mirror says t0 now
            assert upd.returncode == 0, upd.stdout + upd.stderr
            out = lab.agent_commit("t0 has no role")
            assert "rc=0" in out, out
            author, committer, sig, _ = lab.show().split("|")
            assert author == committer == HUMAN and sig == "N"
            return
        lab.touch_config()
        out = self.failed(lab, f"below t2 {how}")
        assert status(lab.rig)[0]["flags"], out
        # and nothing reached the repo with the LLM as author
        log = subprocess.run(
            ["git", "log", "--format=%ae"],
            cwd=lab.rig.ws,
            env={
                "HOME": str(lab.rig.home),
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            },
            capture_output=True,
            text=True,
        ).stdout
        assert EMAIL not in log

    def test_an_unusable_human_identity_refuses_and_leaves_nothing(self, lab: Lab) -> None:
        pin(lab)
        gitconfig = lab.rig.home / ".gitconfig"
        original = gitconfig.read_text()
        cases = (
            ("no identity", "[user]\n"),
            ("the LLM's address", f"[user]\n\tname = X\n\temail = {EMAIL}\n"),
            ("a Carter fallback", "[user]\n\tname = Carter\n\temail = state@carter.invalid\n"),
        )
        for label, section in cases:
            gitconfig.write_text(original.replace(USER_BLOCK, section))
            lab.touch_config()
            self.failed(lab, label)
        gitconfig.write_text(original)
        lab.touch_config()
        assert "rc=0" in lab.agent_commit("identity back")
        assert lab.show().split("|")[0] == f"{LOGIN} <{EMAIL}>"

    def test_an_identity_that_breaks_after_the_plugin_decided_is_stopped_by_the_hook(
        self, lab: Lab
    ) -> None:
        """The plugin cache does not stamp ~/.gitconfig; the hook re-reads it and decides."""
        pin(lab)
        assert "rc=0" in lab.agent_commit("cache warm")
        original = set_human(lab, "[user]\n")
        try:
            out = self.failed(lab, "stale cache")
            assert "E-HUMAN-IDENTITY" in out, out
        finally:
            (lab.rig.home / ".gitconfig").write_text(original)


class TestRewrites:
    def test_an_agent_amend_and_rebase_keep_a_human_commit_s_author_and_a_reset_author_is_stopped(
        self, lab: Lab
    ) -> None:
        pin(lab)
        human = lab.human_commit("a human commit")
        assert "rc=0" in human, human
        assert lab.show().split("|")[0] == HUMAN
        before = lab.count()
        # the literal command is refused by the gate; the same thing from a script reaches git and the hook
        gate = error_message(run_shell(lab.rig, "git commit --amend --reset-author --no-edit"))
        assert gate.startswith(REFUSED) and "commit-flags" in gate
        path = lab.script("git commit -q --amend --reset-author --no-edit\necho rc=$?")
        hooked = run_shell(lab.rig, f"sh {path}")
        assert "rc=0" not in hooked and "may not change a commit's author" in hooked, hooked
        assert lab.show().split("|")[0] == HUMAN and lab.count() == before
        # a plain amend keeps the human as author, the LLM signs and credits itself
        plain = lab.script("git commit -q --amend --no-edit\necho rc=$?")
        out = run_shell(lab.rig, f"sh {plain}")
        assert "rc=0" in out, out
        author, committer, sig, _ = lab.show().split("|")
        assert author == HUMAN and committer == f"{LOGIN} <{EMAIL}>" and sig == "G"
        assert LLM_LINE in trailers(lab)

    def test_a_status_file_says_passed_and_no_agent_or_server_is_left(self, lab: Lab) -> None:
        pin(lab)
        assert "rc=0" in lab.agent_commit("last")
        assert wait_status(lab.rig, "passed")["state"] == "passed"
