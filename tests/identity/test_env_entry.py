"""``python -I -m carter.identity.env --json`` (plan 004 step 15, freeze G13)."""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

from carter.identity import env as entry
from carter.identity.payload import fingerprint_of, shim_path
from identity import vectors

LOGIN, UID = "llm-bot", 12345
IDENT = (
    f'[identity]\nlogin = "{LOGIN}"\nid = {UID}\nemail = "{UID}+{LOGIN}@users.noreply.github.com"\n'
)
BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
SIGNING = (
    f'[identity.signing]\nfingerprint = "{fingerprint_of(BLOB)}"\n'
    f'public_key = "{BLOB} llm@laptop"\nprivate_key_path = "/secret/dir/llm_key"\n'
)
KEYS = vectors.load()["tier"]["env_keys"]


def install_shim(home: Path, *, record: bool = True) -> Path:
    """A shim as ``identity add`` leaves it: executable, hash recorded in guard-state."""
    shim = shim_path(home)
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text("#!/bin/sh\n# Managed by Carter\n")
    shim.chmod(0o755)
    if record:
        digest = hashlib.sha256(shim.read_bytes()).hexdigest()
        files = [{"path": str(shim), "sha256": f"sha256:{digest}"}]
        (home / ".carter" / "guard-state.json").write_text(json.dumps({"files": files}))
    return shim


def run(tmp_path: Path, config: str | None, cwd: Path | None = None, *, shim: bool = True) -> dict:
    path = tmp_path / "config.toml"
    if config is not None:
        path.write_text("schema = 2\n" + config if "schema" not in config else config)
    home = tmp_path / "home"
    (home / ".carter").mkdir(parents=True, exist_ok=True)
    if shim:
        install_shim(home)
    return entry.answer(str(cwd or tmp_path), {}, str(path), home)


class TestAnswer:
    def test_absent_file_is_t0_and_not_blocked(self, tmp_path: Path) -> None:
        got = run(tmp_path, None)
        assert got == {
            "schema_version": 1, "tier": "t0", "cap": None, "effective": "t0",
            "require_tier": None, "reason": None,
        }  # fmt: skip

    def test_only_the_documented_keys(self, tmp_path: Path) -> None:
        assert list(run(tmp_path, IDENT)) == KEYS

    def test_a_schema_1_file_is_recognised_as_t0_not_an_error(self, tmp_path: Path) -> None:
        got = run(tmp_path, '[attribution]\nfooter = "x"\n')  # no schema key = schema 1
        assert (got["effective"], got["reason"]) == ("t0", None)

    def test_t1_has_no_reason(self, tmp_path: Path) -> None:
        got = run(tmp_path, IDENT)
        assert (got["tier"], got["effective"], got["reason"]) == ("t1", "t1", None)

    def test_t2_with_a_complete_setup_carries_the_signing_block_and_no_reason(
        self, tmp_path: Path
    ) -> None:
        got = run(tmp_path, IDENT + SIGNING)
        assert (got["tier"], got["effective"], got["reason"]) == ("t2", "t2", None)
        assert list(got) == [*KEYS, "signing"]
        shim = str(shim_path(tmp_path / "home"))
        assert got["signing"]["git_config"] == [
            ["gpg.format", "ssh"],
            ["user.signingkey", f"key::{BLOB}"],
            ["gpg.ssh.program", shim],
            ["commit.gpgsign", "true"],
        ]
        assert got["signing"]["fingerprint"] == fingerprint_of(BLOB)

    @pytest.mark.parametrize(
        ("config", "shim", "reason"),
        [
            (IDENT + SIGNING, False, "shim-missing"),
            (
                IDENT + SIGNING.replace(fingerprint_of(BLOB), "SHA256:" + "A" * 43),
                True,
                "fingerprint-mismatch",
            ),
            (IDENT + SIGNING.replace(BLOB, "ssh-ed25519 !!!"), True, "key-missing"),
            (
                IDENT.replace("[identity]\n", '[identity]\nrole = "author"\n') + SIGNING,
                True,
                "role-b-not-built",
            ),
        ],
        ids=["no shim", "fingerprint of another key", "public key not a blob", "role b"],
    )
    def test_each_failure_has_its_reason_and_no_block(
        self, tmp_path: Path, config: str, shim: bool, reason: str
    ) -> None:
        got = run(tmp_path, config, shim=shim)
        assert (got["effective"], got["reason"]) == ("t2", reason)
        assert "signing" not in got

    def test_a_shim_without_a_guard_state_record_is_shim_missing(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".carter").mkdir(parents=True)
        install_shim(home, record=False)
        path = tmp_path / "config.toml"
        path.write_text("schema = 2\n" + IDENT + SIGNING)
        assert entry.answer(str(tmp_path), {}, str(path), home)["reason"] == "shim-missing"

    def test_the_old_reason_is_retired(self, tmp_path: Path) -> None:
        for shim in (True, False):
            assert run(tmp_path, IDENT + SIGNING, shim=shim)["reason"] != "signing-not-built"

    def test_the_entry_never_touches_the_agent_or_the_private_key(self, tmp_path: Path) -> None:
        # the private key path in the fixture does not exist; the answer is the same
        assert run(tmp_path, IDENT + SIGNING)["reason"] is None

    def test_the_workspace_cap_lowers_the_effective_tier_and_unblocks(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        sub = ws / "src" / "pkg"
        sub.mkdir(parents=True)
        cfg = IDENT + SIGNING + f'[workspaces."{ws}"]\nmax_tier = "t1"\n'
        got = run(tmp_path, cfg, cwd=sub)
        assert (got["tier"], got["cap"], got["effective"], got["reason"]) == (
            "t2",
            "t1",
            "t1",
            None,
        )
        outside = run(tmp_path, cfg, cwd=tmp_path)
        assert (outside["cap"], outside["effective"], outside["reason"]) == (None, "t2", None)
        assert "signing" not in got and "signing" in outside  # a cap means no block at all

    def test_a_sibling_directory_with_the_same_prefix_is_not_the_workspace(
        self, tmp_path: Path
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        other = tmp_path / "ws-other"
        other.mkdir()
        got = run(tmp_path, IDENT + SIGNING + f'[workspaces."{ws}"]\nmax_tier = "t1"\n', cwd=other)
        assert got["cap"] is None

    def test_require_tier_not_met_is_tier_required(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        got = run(tmp_path, IDENT + f'[workspaces."{ws}"]\nrequire_tier = "t2"\n', cwd=ws)
        assert (got["effective"], got["require_tier"], got["reason"]) == (
            "t1",
            "t2",
            "tier-required",
        )

    def test_role_author_below_t2_is_tier_required(self, tmp_path: Path) -> None:
        got = run(tmp_path, IDENT.replace("[identity]\n", '[identity]\nrole = "author"\n'))
        assert got["reason"] == "tier-required"

    @pytest.mark.parametrize(
        "config",
        [
            "schema = 2\nnot toml [[[",
            "schema = 9\n",
            "schema = 2\n[identity]\nlogin = 5\n",
            'schema = 2\n[identity]\nrole = "nonsense"\n',
            "schema = 2\n"
            + IDENT
            + '[identity.signing]\nfingerprint = "SHA256:abc"\n',  # incomplete
        ],
        ids=["unparseable", "unknown-schema", "wrong-type", "bad-enum", "incomplete-signing"],
    )
    def test_any_defect_in_an_existing_file_is_config_error_never_t0_silently(
        self, tmp_path: Path, config: str
    ) -> None:
        (tmp_path / "config.toml").write_text(config)
        got = entry.answer(str(tmp_path), {}, str(tmp_path / "config.toml"))
        assert got["reason"] == "config-error"

    def test_below_t2_no_value_of_the_config_is_printed(self, tmp_path: Path) -> None:
        text = json.dumps(run(tmp_path, IDENT))
        assert LOGIN not in text and "SHA256" not in text and "ssh-ed25519" not in text

    def test_at_t2_only_the_block_is_printed_no_comment_no_private_path_no_socket(
        self, tmp_path: Path
    ) -> None:
        text = json.dumps(run(tmp_path, IDENT + SIGNING + 'agent_socket = "/run/x/agent.sock"\n'))
        assert "laptop" not in text and "/secret/dir" not in text and "agent.sock" not in text
        assert "socket" not in text and "private" not in text


class TestCommandLine:
    def invoke(self, tmp_path: Path, *args: str, config: str | None = None):
        home = tmp_path / "home"
        (home / ".carter").mkdir(parents=True)
        if config is not None:
            (home / ".carter" / "config.toml").write_text(config)
            install_shim(home)
        env = {"HOME": str(home), "PATH": os.environ["PATH"]}
        return subprocess.run(
            [sys.executable, "-I", "-m", "carter.identity.env", *args],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        )  # fmt: skip

    def test_json_output_is_one_line_and_exit_zero(self, tmp_path: Path) -> None:
        done = self.invoke(tmp_path, "--json", config="schema = 2\n" + IDENT + SIGNING)
        assert done.returncode == 0 and done.stdout.count("\n") == 1
        doc = json.loads(done.stdout)
        assert doc["reason"] is None and doc["signing"]["fingerprint"] == fingerprint_of(BLOB)
        assert doc["signing"]["git_config"][2][1] == str(shim_path(tmp_path / "home"))

    def test_it_stays_fast_with_the_signing_block(self, tmp_path: Path) -> None:
        """The 2 s env_timeout_ms has ~40x margin (plan 004 notes: ~41 ms); keep it that way."""
        times = []
        for _ in range(7):
            start = time.perf_counter()
            done = self.invoke_again(tmp_path)
            times.append((time.perf_counter() - start) * 1000)
            assert done.returncode == 0
        assert statistics.median(times) < 250, times

    def invoke_again(self, tmp_path: Path):
        home = tmp_path / "home"
        if not (home / ".carter" / "config.toml").exists():
            (home / ".carter").mkdir(parents=True, exist_ok=True)
            (home / ".carter" / "config.toml").write_text("schema = 2\n" + IDENT + SIGNING)
            install_shim(home)
        env = {"HOME": str(home), "PATH": os.environ["PATH"]}
        return subprocess.run(
            [sys.executable, "-I", "-m", "carter.identity.env", "--json"],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        )  # fmt: skip

    def test_a_missing_config_is_t0(self, tmp_path: Path) -> None:
        assert json.loads(self.invoke(tmp_path, "--json").stdout)["effective"] == "t0"

    def test_a_broken_config_still_answers_with_config_error(self, tmp_path: Path) -> None:
        done = self.invoke(tmp_path, "--json", config="{{{")
        assert done.returncode == 0 and json.loads(done.stdout)["reason"] == "config-error"

    def test_without_json_it_is_a_usage_error(self, tmp_path: Path) -> None:
        assert self.invoke(tmp_path).returncode == 2

    def test_it_does_not_import_the_cli_or_third_party_modules(self, tmp_path: Path) -> None:
        code = (
            "import sys; import carter.identity.env; "
            "bad = [m for m in ('click', 'jinja2', 'yaml', 'carter.cli') if m in sys.modules]; "
            "print(bad)"
        )
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        assert out.stdout.strip() == "[]"
