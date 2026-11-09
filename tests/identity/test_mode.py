"""CI mode and context E: the resolver refuses commits in review mode.

Precedence ``CARTER_IDENTITY_MODE`` > ``[identity] mode`` > auto; auto in a detected CI is
``review``; Carter never infers that it may commit. Contexts C and D are not built.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from carter.identity import mode
from carter.identity.errors import E_CI_REVIEW, E_CONFIG, IdentityError, registry
from carter.identity.resolve import resolve
from carter.identity.schema import Identity, IdentityConfig, Signing

CI = {"GITHUB_ACTIONS": "true", "CI": "true"}


def cfg(mode_value: str = "", **kw) -> IdentityConfig:
    return IdentityConfig(identity=Identity(mode=mode_value), **kw)


class TestDetection:
    @pytest.mark.parametrize(
        "env",
        [
            {"GITHUB_ACTIONS": "true"},
            {"CI": "true"},
            {"CI": "1"},
            {"CI": "TRUE"},
            {"CI": "yes"},
        ],
    )
    def test_ci_is_detected(self, env: Mapping[str, str]) -> None:
        assert mode.in_ci(env)

    @pytest.mark.parametrize(
        "env",
        [
            {},
            {"CI": ""},
            {"CI": "false"},
            {"CI": "0"},
            {"GITHUB_ACTIONS": "false"},
            {"GITHUB_ACTIONS": ""},
        ],
    )
    def test_ci_is_not_detected(self, env: Mapping[str, str]) -> None:
        assert not mode.in_ci(env)


class TestPrecedence:
    def test_the_default_outside_ci_is_interactive(self) -> None:
        got = mode.resolve_mode("", {})
        assert (got.mode, got.source, got.error) == ("interactive", "default", "")

    def test_the_default_in_ci_is_review(self) -> None:
        got = mode.resolve_mode("", CI)
        assert (got.mode, got.source) == ("review", "auto")

    def test_config_beats_auto(self) -> None:
        got = mode.resolve_mode("review", {})
        assert (got.mode, got.source) == ("review", "config")

    def test_env_beats_config(self) -> None:
        got = mode.resolve_mode("review", {"CARTER_IDENTITY_MODE": "interactive"})
        assert (got.mode, got.source) == ("interactive", "env")

    def test_an_empty_env_value_is_unset(self) -> None:
        got = mode.resolve_mode("review", {"CARTER_IDENTITY_MODE": ""})
        assert (got.mode, got.source) == ("review", "config")

    def test_auto_spelled_out_is_the_default(self) -> None:
        assert mode.resolve_mode("auto", CI).mode == "review"
        assert mode.resolve_mode("auto", {}).mode == "interactive"
        assert mode.resolve_mode("", {"CARTER_IDENTITY_MODE": "auto"}).mode == "interactive"


class TestRefusedModes:
    def test_interactive_in_ci_is_refused_that_is_context_c(self) -> None:
        got = mode.resolve_mode("", {**CI, "CARTER_IDENTITY_MODE": "interactive"})
        assert got.error and "context C" in got.error and "not built" in got.error

    def test_config_interactive_in_ci_is_refused_too(self) -> None:
        assert mode.resolve_mode("interactive", CI).error

    @pytest.mark.parametrize("value", ["commit", "scheduled", "ci", "C", "D"])
    def test_unbuilt_contexts_c_and_d_are_errors(self, value: str) -> None:
        got = mode.resolve_mode(value, {})
        assert got.error and "not built" in got.error and "only `review`" in got.error

    @pytest.mark.parametrize("value", ["Review", "yes", "rview", " review", "review "])
    def test_an_unknown_value_is_an_error_and_never_echoed(self, value: str) -> None:
        got = mode.resolve_mode("", {"CARTER_IDENTITY_MODE": value})
        assert got.error and f"'{value}'" not in got.error and f'"{value}"' not in got.error

    def test_an_unknown_value_never_falls_back(self) -> None:
        got = mode.resolve_mode("review", {"CARTER_IDENTITY_MODE": "nope"})
        assert got.error and got.mode == ""


class TestResolver:
    def test_review_mode_refuses_commits_with_the_registered_code(self) -> None:
        res = resolve(cfg(), workspace=None, env=CI)
        assert (res.mode, res.mode_source) == ("review", "auto")
        assert (res.commits, res.refusal_reason) == ("refused", E_CI_REVIEW)
        with pytest.raises(IdentityError) as exc:
            res.ensure_commits_allowed()
        assert exc.value.code == E_CI_REVIEW and str(exc.value) == registry()[E_CI_REVIEW].message

    @pytest.mark.parametrize("env", [CI, {"CARTER_IDENTITY_MODE": "review"}])
    def test_both_ways_into_review_refuse(self, env: Mapping[str, str]) -> None:
        assert resolve(cfg(), workspace=None, env=env).commits == "refused"

    def test_outside_ci_nothing_changes(self) -> None:
        res = resolve(cfg(), workspace=None, env={})
        assert (res.mode, res.commits, res.refusal_reason) == ("interactive", "allowed", "")

    def test_a_pinned_config_mode_review_refuses_outside_ci(self) -> None:
        assert resolve(cfg("review"), workspace=None, env={}).refusal_reason == E_CI_REVIEW

    def test_an_invalid_mode_is_e_config_with_no_fallback(self) -> None:
        res = resolve(cfg(), workspace=None, env={"CARTER_IDENTITY_MODE": "bogus"})
        assert (res.commits, res.refusal_reason) == ("refused", E_CONFIG)
        assert "CARTER_IDENTITY_MODE" in res.refusal_detail and "bogus" not in res.refusal_detail
        with pytest.raises(IdentityError) as exc:
            res.ensure_commits_allowed()
        assert exc.value.code == E_CONFIG

    def test_a_bad_config_mode_names_the_key_not_the_value(self) -> None:
        res = resolve(cfg("bogus"), workspace=None, env={})
        assert res.refusal_reason == E_CONFIG and "[identity] mode" in res.refusal_detail
        assert "bogus" not in res.refusal_detail

    def test_unbuilt_context_via_the_env_is_e_config(self) -> None:
        res = resolve(cfg(), workspace=None, env={"CARTER_IDENTITY_MODE": "commit"})
        assert res.refusal_reason == E_CONFIG and "not built" in res.refusal_detail

    def test_role_b_below_t2_in_ci_reports_review_first(self) -> None:
        res = resolve(IdentityConfig(identity=Identity(role="author")), workspace=None, env=CI)
        assert res.refusal_reason == E_CI_REVIEW

    def test_incomplete_signing_is_still_e_config_before_review(self) -> None:
        broken = replace(cfg(), signing=Signing(public_key="ssh-ed25519 AAAA"))
        assert resolve(broken, workspace=None, env=CI).refusal_reason == E_CONFIG

    def test_the_workflow_file_is_never_an_input(self, tmp_path: Path) -> None:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "x.yml").write_text("on: pull_request\n")
        assert resolve(cfg(), workspace=str(tmp_path), env={}).commits == "allowed"


def test_the_registry_has_the_review_code() -> None:
    entry = registry()[E_CI_REVIEW]
    assert "review run" in entry.message
    assert "\n" not in entry.message
