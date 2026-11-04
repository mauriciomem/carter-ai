"""``build_payload`` / ``to_git_env`` (plan 005 step 8, freeze H3, RFC-0007 §4.3)."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from carter.identity import payload
from carter.identity.isolation_apply import apply_isolation
from carter.identity.payload import (
    ShimState,
    build_payload,
    fingerprint_of,
    public_blob,
    to_git_env,
)
from carter.identity.resolve import resolve
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace
from carter.identity.scrub import scrub_git_env
from identity import vectors
from ssh_rig import real_ssh

V = vectors.load()
BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
LOGIN, UID = "llm-bot", 12345
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
SHIM = ShimState("/home/test/.carter/bin/carter-ssh-sign", True)
NO_SHIM = ShimState("/home/test/.carter/bin/carter-ssh-sign", False)


def cfg(
    *,
    comment: str = "",
    fingerprint: str | None = None,
    role: str = "co-author",
    name: str = "LLM Bot",
    signing: Signing | None = None,
    workspaces: dict[str, Workspace] | None = None,
) -> IdentityConfig:
    key = BLOB + (f" {comment}" if comment else "")
    return IdentityConfig(
        identity=Identity(role=role, login=LOGIN, id=UID, name=name, email=EMAIL),
        signing=signing or Signing(public_key=key, fingerprint=fingerprint or fingerprint_of(BLOB)),
        workspaces=workspaces or {},
        state="current",
    )


def build(c: IdentityConfig, shim: ShimState = SHIM, ws: str | None = None, env=None):  # type: ignore[no-untyped-def]
    return build_payload(c, resolve(c, workspace=ws, env=env or {}), shim)


class TestBlock:
    def test_the_t2_co_author_block_is_exactly_the_frozen_shape(self) -> None:
        got = build(cfg())
        assert got.reason is None and got.block is not None
        assert tuple(got.block) == payload.SIGNING_KEYS
        assert got.block == {
            "env": {
                "GIT_COMMITTER_NAME": "LLM Bot",
                "GIT_COMMITTER_EMAIL": EMAIL,
                "CARTER_IDENTITY": LOGIN,
            },
            "git_config": [
                ["gpg.format", "ssh"],
                ["user.signingkey", f"key::{BLOB}"],
                ["gpg.ssh.program", SHIM.path],
                ["commit.gpgsign", "true"],
            ],
            "fingerprint": fingerprint_of(BLOB),
        }
        assert tuple(got.block["env"]) == payload.SIGNING_ENV_KEYS
        assert tuple(k for k, _ in got.block["git_config"]) == payload.SIGNING_GIT_CONFIG_KEYS

    def test_the_key_comment_never_reaches_the_block(self) -> None:
        got = build(cfg(comment="llm@laptop some comment"))
        assert got.block is not None
        text = json.dumps(got.block)
        assert "laptop" not in text and "comment" not in text
        assert got.block["git_config"][1] == ["user.signingkey", f"key::{BLOB}"]

    def test_the_committer_name_falls_back_to_the_login(self) -> None:
        got = build(cfg(name=""))
        assert got.block is not None and got.block["env"]["GIT_COMMITTER_NAME"] == LOGIN

    def test_only_the_ssh_program_is_in_the_block_the_other_gpg_programs_stay_false(self) -> None:
        got = build(cfg())
        assert got.block is not None
        keys = [k for k, _ in got.block["git_config"]]
        assert [k for k in keys if k.endswith(".program")] == ["gpg.ssh.program"]
        assert "gpg.openpgp.program" not in keys and "gpg.x509.program" not in keys

    @pytest.mark.parametrize(
        "signing",
        [
            {"agent_socket": "/home/test/.1password/agent.sock"},
            {"program": "/opt/vault/sign"},
            {"private_key_path": "/home/test/.ssh/llm", "ttl": "2h"},
        ],
        ids=["agent socket", "program", "private key and ttl"],
    )
    def test_password_manager_and_key_file_setups_keep_the_same_block(self, signing: dict) -> None:
        base = cfg()
        other = cfg(signing=replace(base.signing, **signing))
        assert build(other).block == build(base).block  # the shim, not the block, differs (H8)

    def test_no_private_key_path_or_socket_is_ever_printed(self) -> None:
        c = cfg(
            signing=replace(cfg().signing, private_key_path="/secret/path/id", agent_socket="/s")
        )
        text = json.dumps(build(c).block)
        assert "/secret/path" not in text and '"/s"' not in text and "socket" not in text


class TestReasons:
    """All or nothing: a reason and no block, or a block and no reason."""

    def test_a_cap_below_t2_has_neither_block_nor_reason(self) -> None:
        c = cfg(workspaces={"/w": Workspace(max_tier="t1")})
        assert build(c, ws="/w") == payload.Built()

    def test_a_t1_identity_and_an_absent_one_have_neither(self) -> None:
        t1 = IdentityConfig(identity=Identity(login=LOGIN, id=UID, email=EMAIL), state="current")
        assert build(t1) == payload.Built()
        assert build(IdentityConfig(state="absent")) == payload.Built()

    def test_role_author_at_t2_is_role_b_not_built_and_never_a_co_author_block(self) -> None:
        assert build(cfg(role="author")) == payload.Built(reason="role-b-not-built")

    def test_role_author_below_t2_is_tier_required(self) -> None:
        t1 = IdentityConfig(
            identity=Identity(role="author", login=LOGIN, id=UID, email=EMAIL), state="current"
        )
        assert build(t1).reason == "tier-required"

    def test_an_unmet_require_tier_is_tier_required(self) -> None:
        t1 = IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL),
            workspaces={"/w": Workspace(require_tier="t2")},
            state="current",
        )
        assert build(t1, ws="/w") == payload.Built(reason="tier-required")

    def test_a_cap_below_the_required_tier_is_tier_required(self) -> None:
        c = cfg(workspaces={"/w": Workspace(max_tier="t1", require_tier="t2")})
        assert build(c, ws="/w") == payload.Built(reason="tier-required")

    def test_an_incomplete_signing_setup_is_a_config_error(self) -> None:
        c = cfg(signing=Signing(fingerprint=fingerprint_of(BLOB)))  # blob missing
        assert build(c) == payload.Built(reason="config-error")
        c = cfg(signing=Signing(public_key=BLOB))  # fingerprint missing
        assert build(c) == payload.Built(reason="config-error")

    @pytest.mark.parametrize(
        "key", ["ssh-ed25519", "ssh-ed25519 !!notbase64!!", "rsa AAAA", "x y z"]
    )
    def test_a_public_key_that_is_not_a_type_and_blob_is_key_missing(self, key: str) -> None:
        c = cfg(signing=Signing(public_key=key, fingerprint=fingerprint_of(BLOB)))
        assert build(c) == payload.Built(reason="key-missing")

    def test_a_fingerprint_that_does_not_belong_to_the_key_is_a_mismatch(self) -> None:
        other = "SHA256:" + "A" * 43
        assert build(cfg(fingerprint=other)) == payload.Built(reason="fingerprint-mismatch")

    def test_a_missing_or_changed_shim_is_shim_missing(self) -> None:
        assert build(cfg(), NO_SHIM) == payload.Built(reason="shim-missing")

    def test_the_order_of_reasons_puts_the_config_first_and_the_shim_last(self) -> None:
        assert (
            build(cfg(fingerprint="SHA256:" + "A" * 43), NO_SHIM).reason == "fingerprint-mismatch"
        )
        assert build(cfg(role="author"), NO_SHIM).reason == "role-b-not-built"

    def test_every_reason_is_registered_and_none_comes_with_a_block(self) -> None:
        seen = set()
        cases = [
            build(cfg(workspaces={"/w": Workspace(max_tier="t1", require_tier="t2")}), ws="/w"),
            build(cfg(role="author")),
            build(cfg(signing=Signing(public_key="x"))),
            build(cfg(signing=Signing(public_key="ssh-ed25519", fingerprint="SHA256:x"))),
            build(cfg(fingerprint="SHA256:" + "A" * 43)),
            build(cfg(), NO_SHIM),
        ]
        for got in cases:
            assert (got.block is None) != (got.reason is None) or got == payload.Built()
            if got.reason:
                seen.add(got.reason)
                assert got.block is None
        assert seen <= set(payload.REASONS)
        assert seen >= {
            "tier-required",
            "role-b-not-built",
            "config-error",
            "key-missing",
            "fingerprint-mismatch",
            "shim-missing",
        }


class TestShimState:
    def record(self, home: Path, shim: Path, data: bytes | None = None) -> None:
        digest = hashlib.sha256(shim.read_bytes() if data is None else data).hexdigest()
        state = home / ".carter" / "guard-state.json"
        state.write_text(json.dumps({"files": [{"path": str(shim), "sha256": f"sha256:{digest}"}]}))

    def make(self, home: Path, mode: int = 0o755) -> Path:
        shim = payload.shim_path(home)
        shim.parent.mkdir(parents=True)
        shim.write_text("#!/bin/sh\n# Managed by Carter\n")
        shim.chmod(mode)
        return shim

    def test_the_path_is_under_carter_bin(self, tmp_path: Path) -> None:
        assert payload.shim_path(tmp_path) == tmp_path / ".carter" / "bin" / "carter-ssh-sign"

    def test_an_absent_shim_is_not_ok(self, tmp_path: Path) -> None:
        assert payload.shim_state(tmp_path).ok is False

    def test_a_recorded_unchanged_executable_shim_is_ok(self, tmp_path: Path) -> None:
        shim = self.make(tmp_path)
        self.record(tmp_path, shim)
        assert payload.shim_state(tmp_path) == ShimState(str(shim), True)

    def test_an_edited_shim_is_not_ok(self, tmp_path: Path) -> None:
        shim = self.make(tmp_path)
        self.record(tmp_path, shim)
        shim.write_text("#!/bin/sh\nexec /bin/true\n")
        assert payload.shim_state(tmp_path).ok is False

    def test_no_record_or_a_broken_record_is_not_ok(self, tmp_path: Path) -> None:
        shim = self.make(tmp_path)
        assert payload.shim_state(tmp_path).ok is False  # no guard-state at all
        (tmp_path / ".carter" / "guard-state.json").write_text("{not json")
        assert payload.shim_state(tmp_path).ok is False
        (tmp_path / ".carter" / "guard-state.json").write_text('{"files": "x"}')
        assert payload.shim_state(tmp_path).ok is False
        assert shim.exists()

    def test_a_shim_that_is_not_executable_or_is_a_symlink_is_not_ok(self, tmp_path: Path) -> None:
        shim = self.make(tmp_path, 0o644)
        self.record(tmp_path, shim)
        assert payload.shim_state(tmp_path).ok is False
        shim.chmod(0o755)
        assert payload.shim_state(tmp_path).ok is True
        real = tmp_path / "real"
        real.write_text(shim.read_text())
        real.chmod(0o755)
        shim.unlink()
        shim.symlink_to(real)
        self.record(tmp_path, shim, real.read_bytes())
        assert payload.shim_state(tmp_path).ok is False
        assert stat.S_ISLNK(shim.lstat().st_mode)


class TestFingerprint:
    def test_the_blob_helper_drops_the_comment(self) -> None:
        assert public_blob(BLOB + " me@host") == BLOB
        assert public_blob("") == "" and public_blob("ssh-ed25519") == ""

    @real_ssh
    @pytest.mark.parametrize("kind", ["ed25519", "ecdsa", "rsa"])
    def test_the_computed_fingerprint_is_the_one_ssh_keygen_prints(
        self,
        throwaway_key,
        kind: str,  # type: ignore[no-untyped-def]
    ) -> None:
        key = throwaway_key(kind)
        assert fingerprint_of(key.blob) == key.fingerprint


class TestToGitEnv:
    BLOCK = V["signing"]["block"]

    def test_the_golden_apply_vectors(self) -> None:
        for case in V["signing"]["apply"]:
            before = vectors.expand(case["env"])
            snapshot = dict(before)
            got = to_git_env(before, self.BLOCK)
            assert before == snapshot, case["name"]  # the input is not modified
            assert (got.env, got.flags) == (case["expected"]["env"], case["expected"]["flags"]), (
                case["name"]
            )

    def test_carters_entries_come_last_and_win_a_collision(self) -> None:
        env = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "commit.gpgsign",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_COMMITTER_NAME": "Someone Else",
            "GIT_CONFIG_PARAMETERS": "'commit.gpgsign=false'",
        }
        got = to_git_env(env, self.BLOCK).env
        assert got["GIT_CONFIG_COUNT"] == "5" and "GIT_CONFIG_PARAMETERS" not in got
        assert got["GIT_CONFIG_KEY_4"] == "commit.gpgsign" and got["GIT_CONFIG_VALUE_4"] == "true"
        assert got["GIT_COMMITTER_NAME"] == self.BLOCK["env"]["GIT_COMMITTER_NAME"]

    def test_it_appends_after_the_isolation_block(self) -> None:
        iso = V["isolation"]["doc"]
        applied = apply_isolation({}, iso, None)
        n = int(applied.env["GIT_CONFIG_COUNT"])
        got = to_git_env(applied.env, self.BLOCK)
        assert got.env["GIT_CONFIG_COUNT"] == str(n + 4) and got.flags == []
        assert got.env[f"GIT_CONFIG_KEY_{n}"] == "gpg.format"
        assert got.env["GIT_CONFIG_KEY_0"] == applied.env["GIT_CONFIG_KEY_0"]
        # the isolation block's `gpg.ssh.program=false` is overridden by the later shim entry
        keys = [got.env[f"GIT_CONFIG_KEY_{i}"] for i in range(n + 4)]
        last_program = max(i for i, k in enumerate(keys) if k == "gpg.ssh.program")
        assert got.env[f"GIT_CONFIG_VALUE_{last_program}"] == self.BLOCK["git_config"][2][1]
        for other in ("gpg.openpgp.program", "gpg.x509.program"):
            idx = [i for i, k in enumerate(keys) if k == other]
            assert idx and got.env[f"GIT_CONFIG_VALUE_{idx[-1]}"] != self.BLOCK["git_config"][2][1]


def test_the_scrub_removes_everything_the_block_can_set() -> None:
    env = to_git_env({"PATH": "/usr/bin"}, V["signing"]["block"]).env
    assert scrub_git_env(env) == {"PATH": "/usr/bin"}
