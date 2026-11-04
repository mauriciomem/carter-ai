"""Role resolution for role b (plan 006 step 5; freeze K8; RFC-0007 §4.1; D20, D22, D62)."""

from __future__ import annotations

from pathlib import Path

import pytest

from carter.identity import ConfigError, load_identity
from carter.identity import env as entry
from carter.identity.errors import E_CONFIG, E_ROLE_B_TIER
from carter.identity.mirror import MirrorError, check_caps
from carter.identity.pin import plan_pin
from carter.identity.resolve import ENV_ROLE, resolve, resolve_role
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace

LOGIN, UID = "llm-bot", 12345
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
FPR = "SHA256:2uXQrkCgLxqvXxMrbBJwmanqsboZn/lN5PAQyHhQDtQ"


def cfg(
    role: str = "co-author", *, t2: bool = True, ws: dict[str, Workspace] | None = None
) -> IdentityConfig:
    return IdentityConfig(
        identity=Identity(role=role, login=LOGIN, id=UID, email=EMAIL),
        signing=Signing(public_key=BLOB, fingerprint=FPR) if t2 else Signing(),
        workspaces=ws or {},
        state="current",
    )


class TestPrecedence:
    @pytest.mark.parametrize(
        ("pin", "env", "config", "role", "source"),
        [
            ("author", "co-author", "co-author", "author", "workspace"),
            ("co-author", "author", "author", "co-author", "workspace"),
            ("", "author", "co-author", "author", "env"),
            ("", "co-author", "author", "co-author", "env"),
            ("", "", "author", "author", "config"),
            ("", "", "co-author", "co-author", "default"),
            ("author", "", "", "author", "workspace"),
        ],
    )
    def test_pinned_workspace_over_env_over_config_over_default(
        self, pin: str, env: str, config: str, role: str, source: str
    ) -> None:
        c = cfg(config or "co-author", ws={"/w": Workspace(role=pin)})
        got = resolve_role(c, "/w", {ENV_ROLE: env} if env else {})
        assert (got.role, got.source) == (role, source)

    def test_a_pin_outside_this_workspace_does_not_apply(self) -> None:
        c = cfg(ws={"/other": Workspace(role="author")})
        assert resolve_role(c, "/w", {}).source == "default"


class TestConflictsWarnAndNeverRefuse:
    def test_env_against_a_pin_warns_without_echoing_a_value(self) -> None:
        got = resolve_role(cfg(ws={"/w": Workspace(role="co-author")}), "/w", {ENV_ROLE: "author"})
        assert got.role == "co-author" and len(got.warnings) == 1
        assert "pin" in got.warnings[0] and "author" not in got.warnings[0].replace("co-author", "")

    def test_config_against_a_pin_warns(self) -> None:
        got = resolve_role(cfg("author", ws={"/w": Workspace(role="co-author")}), "/w", {})
        assert got.role == "co-author" and any("config.toml" in w for w in got.warnings)

    def test_config_against_env_warns(self) -> None:
        got = resolve_role(cfg("author"), None, {ENV_ROLE: "co-author"})
        assert got.role == "co-author" and any("config.toml" in w for w in got.warnings)

    def test_agreeing_sources_are_silent(self) -> None:
        got = resolve_role(
            cfg("author", ws={"/w": Workspace(role="author")}), "/w", {ENV_ROLE: "author"}
        )
        assert got.warnings == ()

    def test_an_unknown_env_value_is_ignored_with_a_warning_that_does_not_echo_it(self) -> None:
        got = resolve_role(cfg("author"), None, {ENV_ROLE: "root-please"})
        assert (got.role, got.source) == ("author", "config")
        assert got.warnings and "root-please" not in " ".join(got.warnings)

    def test_a_conflict_never_changes_the_commit_decision(self) -> None:
        res = resolve(
            cfg(ws={"/w": Workspace(role="co-author")}), workspace="/w", env={ENV_ROLE: "author"}
        )
        assert (res.commits, res.refusal_reason) == ("allowed", "") and res.warnings


class TestRoleBRows:
    """Report 10 §3, the Carter-layer column."""

    def test_t2_role_author_is_allowed(self) -> None:
        res = resolve(cfg("author"), workspace=None, env={})
        assert (res.role, res.tier, res.commits, res.refusal_reason) == (
            "author",
            "t2",
            "allowed",
            "",
        )

    def test_below_t2_it_refuses_and_never_degrades(self) -> None:
        res = resolve(cfg("author", t2=False), workspace=None, env={})
        assert (res.role, res.commits, res.refusal_reason) == ("author", "refused", E_ROLE_B_TIER)

    def test_under_a_cap_it_refuses(self) -> None:
        res = resolve(cfg("author", ws={"/w": Workspace(max_tier="t1")}), workspace="/w", env={})
        assert (res.tier, res.commits, res.refusal_reason) == ("t1", "refused", E_ROLE_B_TIER)

    def test_role_author_implies_no_require_tier(self) -> None:
        assert resolve(cfg("author"), workspace=None, env={}).require_tier == ""

    def test_a_broken_signing_setup_is_a_config_error_before_the_role(self) -> None:
        c = cfg("author")
        c = IdentityConfig(identity=c.identity, signing=Signing(public_key=BLOB), state="current")
        assert resolve(c, workspace=None, env={}).refusal_reason == E_CONFIG

    def test_the_env_cannot_turn_a_pinned_co_author_into_role_b(self) -> None:
        res = resolve(
            cfg(ws={"/w": Workspace(role="co-author")}), workspace="/w", env={ENV_ROLE: "author"}
        )
        assert res.role == "co-author"


class TestInvalidValues:
    def write(self, tmp_path: Path, extra: str) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(
            f'schema = 2\n[identity]\nlogin = "{LOGIN}"\nid = {UID}\nemail = "{EMAIL}"\n{extra}'
        )
        return path

    @pytest.mark.parametrize(
        "text",
        ['role = "root"\n', "role = 3\n"],
    )
    def test_an_invalid_config_role_is_a_config_error(self, tmp_path: Path, text: str) -> None:
        path = self.write(tmp_path, text)
        with pytest.raises(ConfigError):
            load_identity(path)
        assert entry.answer(str(tmp_path), {}, str(path), tmp_path)["reason"] == "config-error"

    def test_an_invalid_pinned_role_is_a_config_error(self, tmp_path: Path) -> None:
        path = self.write(tmp_path, f'[workspaces."{tmp_path}"]\nrole = "boss"\n')
        with pytest.raises(ConfigError):
            load_identity(path)
        assert entry.answer(str(tmp_path), {}, str(path), tmp_path)["reason"] == "config-error"


class TestPinningRoleB:
    def test_pinning_author_next_to_a_cap_is_refused_with_the_code(self) -> None:
        c = cfg(ws={"/w": Workspace(max_tier="t1")})
        plan = plan_pin(c, "/w", role="author", require_tier="")
        assert plan.refusal.startswith(E_ROLE_B_TIER) and "max_tier t1" in plan.refusal

    def test_pinning_author_without_a_cap_is_fine_and_pins_no_require_tier(self) -> None:
        plan = plan_pin(cfg(), "/w", role="author", require_tier="")
        assert plan.refusal == "" and [(c.field, c.new) for c in plan.changes] == [
            ("role", "author")
        ]

    def test_pinning_co_author_next_to_a_cap_is_fine(self) -> None:
        assert (
            plan_pin(
                cfg(ws={"/w": Workspace(max_tier="t1")}), "/w", role="co-author", require_tier=""
            ).refusal
            == ""
        )

    def test_the_mirror_refuses_a_cap_added_by_hand_to_a_pinned_role_author(self) -> None:
        with pytest.raises(MirrorError, match=E_ROLE_B_TIER):
            check_caps(cfg(ws={"/w": Workspace(role="author", max_tier="t1")}))
        check_caps(cfg(ws={"/w": Workspace(role="co-author", max_tier="t1")}))
