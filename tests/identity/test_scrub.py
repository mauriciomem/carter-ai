"""``scrub_git_env``: strip everything that can change who a git commit is by."""

from __future__ import annotations

import pytest

from carter.identity.scrub import scrub_git_env

POLLUTED = {
    "GIT_AUTHOR_NAME": "x",
    "GIT_AUTHOR_EMAIL": "x@y",
    "GIT_AUTHOR_DATE": "2000-01-01",
    "GIT_COMMITTER_NAME": "x",
    "GIT_COMMITTER_EMAIL": "x@y",
    "GIT_COMMITTER_DATE": "2000-01-01",
    "GIT_CONFIG": "/etc/evil",
    "GIT_CONFIG_COUNT": "3",
    "GIT_CONFIG_KEY_0": "commit.gpgsign",
    "GIT_CONFIG_VALUE_0": "true",
    "GIT_CONFIG_KEY_17": "user.signingkey",
    "GIT_CONFIG_VALUE_17": "k",
    "GIT_CONFIG_KEY_9999": "a.b",
    "GIT_CONFIG_PARAMETERS": "'user.name=evil'",
    "CARTER_IDENTITY": "x",
    "CARTER_IDENTITY_ROLE": "author",
    "CARTER_IDENTITY_MODE": "ci",
    "EMAIL": "x@y",
    "GIT_DIR": "/elsewhere/.git",
    "GIT_WORK_TREE": "/elsewhere",
    "GIT_INDEX_FILE": "/elsewhere/index",
    "GIT_COMMON_DIR": "/elsewhere/.git",
}


class TestScrub:
    @pytest.mark.parametrize("name", sorted(POLLUTED))
    def test_removes_every_identity_variable(self, name):
        out = scrub_git_env({name: POLLUTED[name], "KEEP": "1"})
        assert name not in out
        assert out == {"KEEP": "1"}

    def test_removes_all_at_once(self):
        assert scrub_git_env({**POLLUTED, "PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}

    @pytest.mark.parametrize(
        "name",
        [
            "PATH",
            "HOME",
            "LANG",
            "TMPDIR",
            "SSH_AUTH_SOCK",
            "GIT_CONFIG_GLOBAL",  # where the human's own config lives
            "GIT_CONFIG_SYSTEM",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_TERMINAL_PROMPT",
            "CARTER_HOME_UNRELATED_NOT_A_THING",
        ],
    )
    def test_keeps_unrelated_variables(self, name):
        assert scrub_git_env({name: "v"}) == {name: "v"}

    def test_every_config_index_is_removed_not_just_the_first(self):
        env = {f"GIT_CONFIG_KEY_{i}": "k" for i in range(0, 200)}
        env |= {f"GIT_CONFIG_VALUE_{i}": "v" for i in range(0, 200)}
        assert scrub_git_env(env) == {}

    def test_is_pure_and_returns_a_new_dict(self):
        env = {"GIT_AUTHOR_NAME": "x", "PATH": "/bin"}
        before = dict(env)
        out = scrub_git_env(env)
        assert env == before
        assert out is not env

    def test_accepts_any_mapping(self):
        from types import MappingProxyType

        assert scrub_git_env(MappingProxyType({"GIT_AUTHOR_NAME": "x", "A": "b"})) == {"A": "b"}

    def test_case_is_significant_like_the_real_environment(self):
        assert scrub_git_env({"git_author_name": "x"}) == {"git_author_name": "x"}
