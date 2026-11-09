"""A declined commit-hook group is never silently lost, and `check --host` names the real fix.

With the LLM signing key (T2) configured, the commit hooks are the guard that keeps agent commits
honest. A user who declined them once is asked again in the one install question, with one line
that says why; `--only hooks` asks again too; and a user who still says no keeps the decision.
"""

from __future__ import annotations

from click.testing import CliRunner

from carter.cli import main
from carter.guard import consent
from carter.guard.state import GuardState, load, save
from carter.install.paths import guard_state_path
from guard.helpers import verbose

T2 = (
    'schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\n'
    'email = "12345+llm-bot@users.noreply.github.com"\n'
    '[identity.signing]\npublic_key = "ssh-ed25519 AAAA"\nfingerprint = "SHA256:abc"\n'
)
T1 = T2.split("[identity.signing]")[0]


def guard(*args: str, **kw):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def configure(home, text: str) -> None:  # type: ignore[no-untyped-def]
    (home / ".carter").mkdir(exist_ok=True)
    (home / ".carter" / "config.toml").write_text(text)


def declined_hooks_state() -> None:
    """What the user's machine had: everything accepted, `hooks` declined at revision 2."""
    state = GuardState()
    for name in ("g2", "sudo-docker", "read-edit-denies", "config-edit"):
        state.consent(name, "accepted", "2026-11-03", 3 if name == "g2" else 1)
    state.consent("hooks", "declined", "2026-11-08", 2)
    path = guard_state_path(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(state, path)


class TestToOffer:
    def state(self) -> GuardState:
        declined_hooks_state()
        return load(guard_state_path(None))

    def test_a_declined_group_stays_out_of_the_question_by_default(self, home) -> None:
        assert "hooks" not in consent.to_offer(self.state(), only=None)

    def test_a_declined_group_that_the_config_needs_is_offered_again(self, home) -> None:
        assert "hooks" in consent.to_offer(self.state(), only=None, reoffer=["hooks"])

    def test_it_is_not_offered_when_it_is_unavailable_on_this_git(self, home) -> None:
        got = consent.to_offer(
            self.state(), only=None, reoffer=["hooks"], unavailable={"hooks": "git is old"}
        )
        assert "hooks" not in got

    def test_the_needed_groups_are_the_declined_commit_guards_when_none_is_accepted(
        self, home
    ) -> None:
        state = self.state()
        assert consent.declined_commit_guards(state) == ["hooks"]
        assert consent.declined_commit_guards(state, unavailable={"hooks": "old git"}) == []
        state.consent("repo_hooks", "accepted", "2026-11-09", 2)
        assert consent.declined_commit_guards(state) == []


class TestTheInstallQuestion:
    def test_t2_with_declined_hooks_asks_again_in_the_one_question_and_says_why(
        self, stack, human_tty
    ) -> None:
        configure(stack.home, T2)
        declined_hooks_state()
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n")
        assert res.exit_code == 0, res.output
        assert res.output.count("Install?") == 1
        head = res.output.split("Install?")[0]
        assert "hooks" in head
        why = [ln for ln in head.splitlines() if "declined" in ln]
        assert len(why) == 1 and "T2" in why[0]
        assert load(guard_state_path(None)).consents["hooks"]["decision"] == "accepted"

    def test_without_t2_a_declined_group_is_left_alone(self, stack, human_tty) -> None:
        configure(stack.home, T1)
        declined_hooks_state()
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n")
        assert "Install?" not in res.output or "hooks" not in res.output.split("Install?")[0]
        assert load(guard_state_path(None)).consents["hooks"]["decision"] == "declined"

    def test_a_no_keeps_the_decision_and_installs_nothing(self, stack, human_tty) -> None:
        configure(stack.home, T2)
        declined_hooks_state()
        human_tty(True)
        stack.fake()
        before = guard_state_path(None).read_bytes()
        res = guard("install", input="n\n")
        assert "Nothing installed" in res.output
        assert guard_state_path(None).read_bytes() == before

    def test_only_hooks_asks_a_declined_group_again_with_one_question(
        self, stack, human_tty
    ) -> None:
        declined_hooks_state()
        human_tty(True)
        stack.fake()
        res = guard("install", "--only", "hooks", input="y\n")
        assert res.exit_code == 0, res.output
        assert res.output.count("Install?") == 1
        assert load(guard_state_path(None)).consents["hooks"]["decision"] == "accepted"

    def test_a_bare_yes_does_not_flip_a_declined_group(self, stack) -> None:
        configure(stack.home, T2)
        declined_hooks_state()
        stack.fake()
        guard("install", "--yes")
        assert load(guard_state_path(None)).consents["hooks"]["decision"] == "declined"
