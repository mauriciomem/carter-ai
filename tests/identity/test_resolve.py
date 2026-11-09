"""The pure tier and role resolver (tiers, cap)."""

from __future__ import annotations

import pytest

from carter.identity import (
    IdentityConfig,
    IdentityError,
    configured_tier,
    effective_tier,
    is_noreply_email,
    resolve,
    resolve_role,
)
from carter.identity.schema import Identity, Signing, Workspace

LOGIN, UID = "llm-bot", 12345
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
KEY = {"fingerprint": "SHA256:abc", "public_key": "ssh-ed25519 AAAA"}
WS = "/abs/ws"


def cfg(
    *,
    identity: Identity | None = None,
    signing: Signing | None = None,
    workspaces: dict[str, Workspace] | None = None,
    state: str = "current",
) -> IdentityConfig:
    return IdentityConfig(
        identity=identity or Identity(),
        signing=signing or Signing(),
        workspaces=workspaces or {},
        state=state,  # type: ignore[arg-type]
    )


T1_ID = Identity(login=LOGIN, id=UID, email=EMAIL)
T2_SIGNING = Signing(**KEY)


class TestNoreplyEmail:
    @pytest.mark.parametrize(
        "email",
        [
            EMAIL,
            "1+a@users.noreply.github.com",
            "99+octo-cat_1@users.noreply.github.com",
        ],
    )
    def test_accepts_id_plus_login_form(self, email):
        assert is_noreply_email(email)

    @pytest.mark.parametrize(
        "email",
        [
            "carter-bot@users.noreply.github.com",  # the old default: no id
            "llm-bot@users.noreply.github.com",
            "+llm-bot@users.noreply.github.com",
            "12345+@users.noreply.github.com",
            "abc+llm-bot@users.noreply.github.com",
            "12345+llm-bot@example.com",
            "12345+llm-bot@users.noreply.github.com.evil.io",
            "x12345+llm-bot@users.noreply.github.com",
            "12345+llm bot@users.noreply.github.com",
            "12345+llm-bot@users.noreply.github.com\n",
            "",
        ],
    )
    def test_rejects_everything_else(self, email):
        assert not is_noreply_email(email)

    def test_login_and_id_must_match_when_given(self):
        assert is_noreply_email(EMAIL, login=LOGIN, uid=UID)
        assert is_noreply_email(EMAIL, login="LLM-Bot", uid=UID)  # logins are case-insensitive
        assert not is_noreply_email(EMAIL, login="other", uid=UID)
        assert not is_noreply_email(EMAIL, login=LOGIN, uid=1)


class TestConfiguredTier:
    def test_nothing_configured_is_t0(self):
        assert configured_tier(cfg()) == "t0"

    def test_login_id_email_is_t1(self):
        assert configured_tier(cfg(identity=T1_ID)) == "t1"

    def test_email_may_be_left_empty_and_is_derived(self):
        assert configured_tier(cfg(identity=Identity(login=LOGIN, id=UID))) == "t1"

    def test_signing_key_on_top_is_t2(self):
        assert configured_tier(cfg(identity=T1_ID, signing=T2_SIGNING)) == "t2"

    @pytest.mark.parametrize(
        "identity",
        [
            Identity(login=LOGIN),  # no numeric id: cannot form a noreply address
            Identity(id=UID),  # no login
            Identity(login=LOGIN, id=UID, email="carter-bot@users.noreply.github.com"),
            Identity(login=LOGIN, id=UID, email="someone@example.com"),
            Identity(login="other", id=UID, email=EMAIL),  # email disagrees with login
        ],
        ids=["login-only", "id-only", "old-default", "foreign", "mismatch"],
    )
    def test_incomplete_or_inconsistent_identity_without_a_key_stays_t0(self, identity):
        assert configured_tier(cfg(identity=identity)) == "t0"

    def test_signing_key_on_top_of_t1_needs_blob_and_fingerprint_for_t2(self):
        assert configured_tier(cfg(identity=T1_ID, signing=T2_SIGNING)) == "t2"

    def test_public_key_path_alone_is_not_the_public_half(self):
        # Architect: the reader cannot open the file; the shim works on the blob.
        signing = Signing(fingerprint="SHA256:abc", public_key_path="~/.ssh/k.pub")
        assert configured_tier(cfg(identity=T1_ID, signing=signing)) == "t0"

    def test_custody_fields_are_not_part_of_the_tier(self):
        # private_key_path / agent_socket / program fail at signing time, not here.
        bare = Signing(**KEY)
        with_agent = Signing(**KEY, agent_socket="/run/a.sock", program="op-ssh-sign")
        assert configured_tier(cfg(identity=T1_ID, signing=bare)) == "t2"
        assert configured_tier(cfg(identity=T1_ID, signing=with_agent)) == "t2"


class TestT2FailsClosed:
    """Once signing is configured, a broken config disables agent commits;
    it never falls back to T1 or T0."""

    MATERIAL = [
        {"public_key": "ssh-ed25519 AAAA"},
        {"public_key_path": "~/.ssh/k.pub"},
        {"fingerprint": "SHA256:abc"},
        {"private_key_path": "~/.ssh/k"},
        {"agent_socket": "/run/a.sock"},
        {"program": "op-ssh-sign"},
    ]

    @pytest.mark.parametrize("material", MATERIAL, ids=lambda m: next(iter(m)))
    def test_incomplete_signing_material_refuses_with_e_config(self, material):
        r = resolve(cfg(identity=T1_ID, signing=Signing(**material)), workspace=WS, env={})
        # Material alone is partial unless it happens to be blob + fingerprint.
        assert (r.commits, r.refusal_reason) == ("refused", "E-CONFIG")
        assert r.tier == "t0"  # no usable identity or key; never t1

    def test_partial_signing_block_is_refused_not_downgraded_to_t1(self):
        for signing in (Signing(fingerprint="SHA256:abc"), Signing(public_key="ssh-ed25519 A")):
            r = resolve(cfg(identity=T1_ID, signing=signing), workspace=WS, env={})
            assert (r.tier, r.commits, r.refusal_reason) == ("t0", "refused", "E-CONFIG")

    def test_public_key_path_without_blob_is_refused(self):
        signing = Signing(fingerprint="SHA256:abc", public_key_path="~/.ssh/k.pub")
        r = resolve(cfg(identity=T1_ID, signing=signing), workspace=WS, env={})
        assert (r.commits, r.refusal_reason) == ("refused", "E-CONFIG")

    @pytest.mark.parametrize(
        "identity",
        [
            Identity(),
            Identity(login=LOGIN),
            Identity(login=LOGIN, id=UID, email="carter-bot@users.noreply.github.com"),
            Identity(login="other", id=UID, email=EMAIL),
        ],
        ids=["no-identity", "login-only", "old-default", "mismatch"],
    )
    def test_key_with_incomplete_identity_is_refused(self, identity):
        r = resolve(cfg(identity=identity, signing=T2_SIGNING), workspace=WS, env={})
        assert (r.tier, r.commits, r.refusal_reason) == ("t0", "refused", "E-CONFIG")

    def test_refusal_applies_even_under_a_cap(self):
        c = cfg(
            identity=T1_ID,
            signing=Signing(fingerprint="SHA256:abc"),
            workspaces={WS: Workspace(max_tier="t1")},
        )
        assert resolve(c, workspace=WS, env={}).refusal_reason == "E-CONFIG"

    def test_complete_t2_is_not_refused(self):
        r = resolve(cfg(identity=T1_ID, signing=T2_SIGNING), workspace=WS, env={})
        assert (r.tier, r.commits, r.refusal_reason) == ("t2", "allowed", "")

    def test_names_the_missing_keys_without_values(self):
        signing = Signing(fingerprint="SHA256:SECRETPRINT")
        r = resolve(cfg(identity=T1_ID, signing=signing), workspace=WS, env={})
        text = " ".join(r.warnings) + r.refusal_detail
        assert "identity.signing.public_key" in text
        assert "SECRETPRINT" not in text

    def test_config_refusal_wins_over_role_refusal(self):
        c = cfg(
            identity=Identity(role="author", **vars_of(T1_ID)),
            signing=Signing(fingerprint="SHA256:abc"),
        )
        assert resolve(c, workspace=WS, env={}).refusal_reason == "E-CONFIG"

    def test_ensure_commits_allowed_raises_e_config(self):
        r = resolve(cfg(identity=T1_ID, signing=Signing(program="x")), workspace=WS, env={})
        with pytest.raises(IdentityError) as exc:
            r.ensure_commits_allowed()
        assert exc.value.code == "E-CONFIG"
        assert "disabled" in str(exc.value)
        assert "identity.signing.public_key" in exc.value.detail


class TestT1Warning:
    """Login-only or inconsistent identities stay T0 and say why (no values echoed)."""

    @pytest.mark.parametrize(
        "identity",
        [
            Identity(login=LOGIN),
            Identity(id=UID),
            Identity(email=EMAIL),
            Identity(login=LOGIN, id=UID, email="carter-bot@users.noreply.github.com"),
            Identity(login="other", id=UID, email=EMAIL),
        ],
        ids=["login-only", "id-only", "email-only", "old-default", "mismatch"],
    )
    def test_warns_and_stays_t0_but_commits_are_allowed(self, identity):
        r = resolve(cfg(identity=identity), workspace=WS, env={})
        assert (r.tier, r.commits) == ("t0", "allowed")
        assert len(r.warnings) == 1
        assert "T0" in r.warnings[0]
        assert "carter-bot" not in r.warnings[0] and LOGIN not in r.warnings[0]

    @pytest.mark.parametrize(
        "identity",
        [Identity(), T1_ID, Identity(login=LOGIN, id=UID)],
        ids=["none", "t1", "derived"],
    )
    def test_no_warning_when_nothing_or_everything_is_set(self, identity):
        assert resolve(cfg(identity=identity), workspace=WS, env={}).warnings == ()

    def test_name_and_mode_alone_do_not_trigger_it(self):
        r = resolve(cfg(identity=Identity(name="x", mode="review")), workspace=WS, env={})
        assert r.warnings == ()


class TestEffectiveTier:
    @pytest.mark.parametrize(
        ("configured", "cap", "expected"),
        [
            ("t2", "", "t2"),
            ("t2", "t1", "t1"),
            ("t2", "t0", "t0"),
            ("t1", "t0", "t0"),
            ("t1", "t1", "t1"),
            ("t0", "t1", "t0"),  # a cap never raises
            ("t0", "t0", "t0"),
        ],
    )
    def test_is_min_of_configured_and_cap(self, configured, cap, expected):
        assert effective_tier(configured, cap) == expected

    def test_unknown_cap_fails_safe_to_t0(self):
        assert effective_tier("t2", "t9") == "t0"


class TestRolePrecedence:
    def test_default_is_co_author(self):
        r = resolve_role(cfg(), WS, {})
        assert (r.role, r.source) == ("co-author", "default")

    def test_config_role_beats_default(self):
        r = resolve_role(cfg(identity=Identity(role="author")), WS, {})
        assert (r.role, r.source) == ("author", "config")

    def test_session_env_beats_config(self):
        c = cfg(identity=Identity(role="co-author"))
        r = resolve_role(c, WS, {"CARTER_IDENTITY_ROLE": "author"})
        assert (r.role, r.source) == ("author", "env")

    def test_pinned_workspace_beats_env_and_config(self):
        c = cfg(
            identity=Identity(role="author"),
            workspaces={WS: Workspace(role="co-author")},
        )
        r = resolve_role(c, WS, {"CARTER_IDENTITY_ROLE": "author"})
        assert (r.role, r.source) == ("co-author", "workspace")

    def test_workspace_entry_without_role_does_not_pin(self):
        c = cfg(workspaces={WS: Workspace(max_tier="t1")})
        assert resolve_role(c, WS, {}).source == "default"

    def test_other_workspaces_do_not_apply(self):
        c = cfg(workspaces={"/other": Workspace(role="author")})
        assert resolve_role(c, WS, {}).source == "default"

    def test_empty_env_is_unset(self):
        r = resolve_role(cfg(), WS, {"CARTER_IDENTITY_ROLE": ""})
        assert r.source == "default"

    def test_invalid_env_role_is_ignored_with_a_warning(self):
        r = resolve_role(cfg(), WS, {"CARTER_IDENTITY_ROLE": "root"})
        assert (r.role, r.source) == ("co-author", "default")
        assert len(r.warnings) == 1
        assert "CARTER_IDENTITY_ROLE" in r.warnings[0]
        assert "root" not in r.warnings[0]  # never echo env values

    def test_no_workspace_means_no_pin(self):
        c = cfg(workspaces={WS: Workspace(role="author")})
        assert resolve_role(c, None, {}).source == "default"


class TestResolve:
    def test_t0_defaults_allow_commits_as_co_author(self):
        r = resolve(cfg(), workspace=WS, env={})
        assert (r.configured_tier, r.tier, r.role) == ("t0", "t0", "co-author")
        assert (r.commits, r.refusal_reason) == ("allowed", "")

    def test_t1_resolution(self):
        r = resolve(cfg(identity=T1_ID), workspace=WS, env={})
        assert (r.tier, r.commits) == ("t1", "allowed")

    def test_t2_cap_applies_from_the_pinned_workspace(self):
        c = cfg(
            identity=T1_ID,
            signing=T2_SIGNING,
            workspaces={WS: Workspace(max_tier="t1")},
        )
        r = resolve(c, workspace=WS, env={})
        assert (r.configured_tier, r.cap, r.tier) == ("t2", "t1", "t1")

    def test_cap_of_another_workspace_is_not_applied(self):
        c = cfg(
            identity=T1_ID,
            signing=T2_SIGNING,
            workspaces={"/other": Workspace(max_tier="t0")},
        )
        assert resolve(c, workspace=WS, env={}).tier == "t2"

    @pytest.mark.parametrize("tier_cfg", ["t0", "t1"])
    def test_role_author_below_t2_is_refused_never_downgraded(self, tier_cfg):
        c = cfg(
            identity=T1_ID if tier_cfg == "t1" else Identity(),
            workspaces={WS: Workspace(role="author")},
        )
        r = resolve(c, workspace=WS, env={})
        assert r.role == "author"  # not rewritten to co-author
        assert r.role_source == "workspace"
        assert (r.commits, r.refusal_reason) == ("refused", "E-ROLE-B-TIER")

    def test_role_author_at_t2_is_allowed(self):
        c = cfg(identity=Identity(role="author", **vars_of(T1_ID)), signing=T2_SIGNING)
        r = resolve(c, workspace=WS, env={})
        assert (r.tier, r.role, r.commits) == ("t2", "author", "allowed")

    def test_cap_can_make_role_author_refuse(self):
        c = cfg(
            identity=Identity(role="author", **vars_of(T1_ID)),
            signing=T2_SIGNING,
            workspaces={WS: Workspace(max_tier="t1")},
        )
        r = resolve(c, workspace=WS, env={})
        assert (r.tier, r.refusal_reason) == ("t1", "E-ROLE-B-TIER")

    def test_session_env_cannot_unlock_role_b_below_t2(self):
        r = resolve(cfg(identity=T1_ID), workspace=WS, env={"CARTER_IDENTITY_ROLE": "author"})
        assert (r.role, r.role_source, r.commits) == ("author", "env", "refused")

    def test_pinned_require_tier_is_reported_not_enforced_here(self):
        c = cfg(workspaces={WS: Workspace(require_tier="t2")})
        r = resolve(c, workspace=WS, env={})
        assert r.require_tier == "t2"
        assert (
            r.commits == "allowed"
        )  # E-TIER-REQUIRED is enforced by the plugin and the commit command

    def test_ensure_commits_allowed_raises_with_the_registry_code(self):
        c = cfg(workspaces={WS: Workspace(role="author")})
        r = resolve(c, workspace=WS, env={})
        with pytest.raises(IdentityError) as exc:
            r.ensure_commits_allowed()
        assert exc.value.code == "E-ROLE-B-TIER"
        assert "no downgrade" in str(exc.value)

    def test_ensure_commits_allowed_is_silent_when_allowed(self):
        resolve(cfg(), workspace=WS, env={}).ensure_commits_allowed()

    def test_resolver_ignores_the_process_environment(self, monkeypatch):
        monkeypatch.setenv("CARTER_IDENTITY_ROLE", "author")
        assert resolve(cfg(), workspace=WS, env={}).role == "co-author"

    def test_resolver_inputs_are_not_mutated(self):
        env = {"CARTER_IDENTITY_ROLE": "author"}
        c = cfg(identity=T1_ID)
        before = repr(c)
        resolve(c, workspace=WS, env=env)
        assert repr(c) == before
        assert env == {"CARTER_IDENTITY_ROLE": "author"}


def vars_of(identity: Identity) -> dict:
    return {"login": identity.login, "id": identity.id, "email": identity.email}
