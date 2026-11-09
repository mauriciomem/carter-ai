"""The ``carter.*`` mirror and the cap fragments."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from carter.identity import mirror
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace

LOGIN, UID = "llm-bot", 4242
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
FP = "SHA256:fingerprint"


def cfg(*, signing: bool = True, workspaces: dict[str, Workspace] | None = None) -> IdentityConfig:
    return IdentityConfig(
        identity=Identity(login=LOGIN, id=UID, email=EMAIL),
        signing=Signing(public_key=BLOB, fingerprint=FP) if signing else Signing(),
        workspaces=workspaces or {},
        state="current",
    )


class TestRender:
    def test_t2_has_tier_email_and_fingerprint_in_that_order(self, tmp_path: Path) -> None:
        assert mirror.mirror_entries(cfg(), tmp_path) == [
            ("carter.tier", "t2"),
            ("carter.llmEmail", EMAIL),
            ("carter.llmFingerprint", FP),
        ]

    def test_t1_has_no_fingerprint_and_t0_has_nothing(self, tmp_path: Path) -> None:
        assert mirror.mirror_entries(cfg(signing=False), tmp_path) == [
            ("carter.tier", "t1"),
            ("carter.llmEmail", EMAIL),
        ]
        assert mirror.mirror_entries(IdentityConfig(state="absent"), tmp_path) == []

    def test_a_cap_adds_one_include_if_after_the_base_value(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        c = cfg(workspaces={str(ws): Workspace(max_tier="t1")})
        got = mirror.mirror_entries(c, tmp_path / ".carter")
        *base, last = got
        assert [k for k, _ in base] == list(mirror.CARTER_KEYS)
        real = os.path.realpath(ws)
        assert last == (
            f"includeIf.gitdir:{real}/.path",
            str(
                tmp_path
                / ".carter"
                / "gitconfig.d"
                / hashlib.sha256(real.encode()).hexdigest()[:16]
            ),
        )

    def test_the_fragment_sets_the_minimum_of_tier_and_cap(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        for cap, tier in (("t1", "t1"), ("t0", "t0")):
            frag = mirror.fragments(cfg(workspaces={str(ws): Workspace(max_tier=cap)}), tmp_path)
            assert list(frag.values()) == [f"[carter]\n\ttier = {tier}\n"]
        frag = mirror.fragments(
            cfg(signing=False, workspaces={str(ws): Workspace(max_tier="t1")}), tmp_path
        )
        assert list(frag.values()) == ["[carter]\n\ttier = t1\n"]  # a cap never raises the tier

    def test_a_symlinked_workspace_uses_the_real_path_and_a_trailing_slash(
        self, tmp_path: Path
    ) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        key = mirror.includeif_key(str(link))
        assert key == f"includeIf.gitdir:{os.path.realpath(real)}/.path"
        assert mirror.fragment_name(str(link)) == mirror.fragment_name(str(real))

    def test_a_macos_style_private_prefix_is_normalised_by_realpath(self, tmp_path: Path) -> None:
        private = tmp_path / "private" / "var" / "ws"
        private.mkdir(parents=True)
        (tmp_path / "var").symlink_to(tmp_path / "private" / "var")
        assert mirror.real_workspace(str(tmp_path / "var" / "ws")) == str(private.resolve())

    @pytest.mark.parametrize("bad", ["a*b", "a?b", "a[b", "a\\b"])
    def test_a_glob_character_in_the_path_is_refused(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(mirror.MirrorError, match="glob"):
            mirror.real_workspace(str(tmp_path / bad))

    def test_a_cap_below_the_pinned_require_tier_is_refused(self, tmp_path: Path) -> None:
        c = cfg(workspaces={str(tmp_path): Workspace(max_tier="t1", require_tier="t2")})
        with pytest.raises(mirror.MirrorError, match="E-TIER-REQUIRED"):
            mirror.mirror_entries(c, tmp_path)
        ok = cfg(workspaces={str(tmp_path): Workspace(max_tier="t1", require_tier="t1")})
        assert mirror.mirror_entries(ok, tmp_path)

    def test_entries_are_deterministic_and_sorted(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        one = cfg(workspaces={str(b): Workspace(max_tier="t0"), str(a): Workspace(max_tier="t1")})
        two = cfg(workspaces={str(a): Workspace(max_tier="t1"), str(b): Workspace(max_tier="t0")})
        assert mirror.mirror_entries(one, tmp_path) == mirror.mirror_entries(two, tmp_path)


class TestKeys:
    def test_mirror_keys_are_recognised_in_gits_lower_case_too(self) -> None:
        assert mirror.is_mirror_key("carter.llmemail") and mirror.is_mirror_key(
            "includeif.gitdir:/x/.path"
        )
        assert not mirror.is_mirror_key("hook.carter-guard-pre-push.event")
        assert not mirror.is_mirror_key("alias.ai-commit")

    def test_canonical_spelling_is_restored(self) -> None:
        assert mirror.canonical_key("carter.llmemail") == "carter.llmEmail"
        assert mirror.canonical_key("carter.llmfingerprint") == "carter.llmFingerprint"
        assert mirror.canonical_key("includeif.gitdir:/x/.path") == "includeIf.gitdir:/x/.path"
        assert mirror.canonical_key("hook.x.event") == "hook.x.event"


class TestState:
    def test_in_sync_and_both_stale_directions(self, tmp_path: Path) -> None:
        ws = str(tmp_path)
        plain = cfg()
        capped = cfg(workspaces={ws: Workspace(max_tier="t1")})
        assert mirror.mirror_state(plain, {"tier": "t2"}) == "in-sync"
        assert mirror.mirror_state(capped, {"tier": "t1"}, ws) == "in-sync"
        # a cap was added in config.toml without `carter update`: the mirror still says t2
        assert mirror.mirror_state(capped, {"tier": "t2"}, ws) == "stale-added"
        # the cap was removed without `carter update`: the mirror still says t1
        assert mirror.mirror_state(plain, {"tier": "t1"}, ws) == "stale-removed"

    def test_an_absent_value_is_t0(self) -> None:
        assert mirror.mirror_state(IdentityConfig(state="absent"), {"tier": None}) == "in-sync"
        assert mirror.mirror_state(cfg(), {"tier": None}) == "stale-removed"
        assert mirror.mirror_state(cfg(), {}) == "stale-removed"
