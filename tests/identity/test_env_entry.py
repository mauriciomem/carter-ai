"""``python -I -m carter.identity.env --json`` (plan 004 step 15, freeze G13)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from carter.identity import env as entry
from identity import vectors

LOGIN, UID = "llm-bot", 12345
IDENT = (
    f'[identity]\nlogin = "{LOGIN}"\nid = {UID}\nemail = "{UID}+{LOGIN}@users.noreply.github.com"\n'
)
SIGNING = '[identity.signing]\nfingerprint = "SHA256:abc"\npublic_key = "ssh-ed25519 AAAA"\n'
KEYS = vectors.load()["tier"]["env_keys"]


def run(tmp_path: Path, config: str | None, cwd: Path | None = None) -> dict:
    path = tmp_path / "config.toml"
    if config is not None:
        path.write_text("schema = 2\n" + config if "schema" not in config else config)
    return entry.answer(str(cwd or tmp_path), {}, str(path))


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

    def test_t2_before_2b_is_signing_not_built(self, tmp_path: Path) -> None:
        got = run(tmp_path, IDENT + SIGNING)
        assert (got["tier"], got["effective"], got["reason"]) == ("t2", "t2", "signing-not-built")

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
        assert (outside["cap"], outside["effective"], outside["reason"]) == (
            None,
            "t2",
            "signing-not-built",
        )

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

    def test_no_value_of_the_config_is_printed(self, tmp_path: Path) -> None:
        text = json.dumps(run(tmp_path, IDENT + SIGNING))
        assert LOGIN not in text and "SHA256" not in text and "ssh-ed25519" not in text


class TestCommandLine:
    def invoke(self, tmp_path: Path, *args: str, config: str | None = None):
        home = tmp_path / "home"
        (home / ".carter").mkdir(parents=True)
        if config is not None:
            (home / ".carter" / "config.toml").write_text(config)
        env = {"HOME": str(home), "PATH": os.environ["PATH"]}
        return subprocess.run(
            [sys.executable, "-I", "-m", "carter.identity.env", *args],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        )  # fmt: skip

    def test_json_output_is_one_line_and_exit_zero(self, tmp_path: Path) -> None:
        done = self.invoke(tmp_path, "--json", config="schema = 2\n" + IDENT + SIGNING)
        assert done.returncode == 0 and done.stdout.count("\n") == 1
        assert json.loads(done.stdout)["reason"] == "signing-not-built"

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
