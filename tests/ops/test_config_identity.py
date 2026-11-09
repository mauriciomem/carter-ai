"""``carter ops config`` against the schema-2 identity.

The human's signing key must never be read, detected or substituted; the identity comes
from the resolver at runtime; E-CONFIG is a refusal, not a fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from carter.ops import carter_ops
from carter.ops.config import Config

REPO = Path(__file__).resolve().parents[2]
EMAIL = "12345+llm-bot@users.noreply.github.com"
T1 = f'schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\nemail = "{EMAIL}"\n'
T2 = T1 + '[identity.signing]\npublic_key = "ssh-ed25519 AAAA"\nfingerprint = "SHA256:abc"\n'
DEFAULT_FOOTER = "_This comment was generated with Carter._"


@pytest.fixture
def home() -> Path:
    return Path(os.environ["HOME"])


@pytest.fixture
def cfg_file(home: Path) -> Path:
    path = home / ".carter" / "config.toml"
    path.parent.mkdir(parents=True)
    return path


def emit(capsys: pytest.CaptureFixture[str]) -> dict:
    assert carter_ops.main(["config", "--emit"]) == 0
    return json.loads(capsys.readouterr().out)


class TestEmitField:
    def test_one_field_is_printed_as_plain_text(self, cfg_file, capsys):
        cfg_file.write_text(T1)
        assert carter_ops.main(["config", "--emit", "--field", "coauthor_trailer"]) == 0
        out = capsys.readouterr().out
        assert out == f"Co-authored-by: llm-bot <{EMAIL}>\n"  # not JSON, no other key

    def test_booleans_and_an_unknown_field(self, cfg_file, capsys):
        cfg_file.write_text(T1)
        assert carter_ops.main(["config", "--emit", "--field", "has_github_token"]) == 0
        assert capsys.readouterr().out == "false\n"
        assert carter_ops.main(["config", "--emit", "--field", "nope"]) == 1
        assert "--field must be one of" in capsys.readouterr().err


class TestNoHumanKey:
    def test_config_has_no_signing_key_field(self):
        assert not hasattr(Config(), "signing_key")

    def test_module_exposes_no_key_reader(self):
        import carter.ops.config as ops_config

        for name in ("git_signing_key", "_detect_signing_key", "read_config_toml", "_parse_toml"):
            assert not hasattr(ops_config, name), name

    def test_key_never_appears_in_config_or_emit(self, home, cfg_file, capsys):
        subprocess.run(
            ["git", "config", "--global", "user.signingkey", "SECRET-HUMAN-KEY-ID"], check=True
        )
        ssh = home / ".ssh"
        ssh.mkdir()
        (ssh / "id_ed25519").write_text("PRIVATE-MATERIAL")
        cfg_file.write_text(T1)

        out = json.dumps(emit(capsys)) + repr(Config.load(cfg_file))

        for needle in ("SECRET-HUMAN-KEY-ID", "id_ed25519", "PRIVATE-MATERIAL", str(ssh)):
            assert needle not in out

    def test_an_old_git_signing_key_is_an_unknown_key_and_ignored(self, cfg_file, capsys):
        cfg_file.write_text('[git]\nsigning_key = "/home/dev/.ssh/HUMAN"\n')
        assert "HUMAN" not in json.dumps(emit(capsys))

    def test_no_code_path_reads_the_humans_key(self):
        pattern = re.compile(r"git_signing_key|user\.signingkey|id_ed25519|id_rsa|_detect_signing")
        offenders = {
            str(p.relative_to(REPO)): pattern.findall(p.read_text(encoding="utf-8"))
            for p in (REPO / "carter").rglob("*.py")
            if "_data" not in p.parts and pattern.search(p.read_text(encoding="utf-8"))
        }
        # 2b: the *LLM's* signing block names the git key it sets; it never reads one.
        block = offenders.pop("carter/identity/payload.py", [])
        # ... and `identity add` compares the LLM key with the human's `user.signingkey` so it can
        # refuse it: it reads only a `key::` literal or a `.pub` file, never a private key
        compare = offenders.pop("carter/identity_add.py", [])
        # ... and `check --probe` asks the agent shell's effective config whether the key is the
        # LLM's `key::` literal (a scratch repo, the agent's own environment; never a file)
        probe = offenders.pop("carter/guard/probe.py", [])
        assert offenders == {}
        assert set(block) == {"user.signingkey"} and set(compare) == {"user.signingkey"}
        assert set(probe) == {"user.signingkey"}
        assert "key::" in (REPO / "carter/guard/probe.py").read_text(encoding="utf-8")
        add = (REPO / "carter/identity_add.py").read_text(encoding="utf-8")
        assert "a private key file is never opened" in add
        text = (REPO / "carter/identity/payload.py").read_text(encoding="utf-8")
        assert "subprocess" not in text and "git config" not in text

    def test_the_carter_bot_default_email_no_longer_exists(self):
        allowed: set[str] = set()  # the global AGENTS.md text no longer quotes it
        offenders = [
            str(p.relative_to(REPO))
            for p in (REPO / "carter").rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".j2", ".md", ".json", ".toml"}
            and "_data" not in p.parts
            and "carter-bot@users.noreply.github.com" in p.read_text(encoding="utf-8")
            and str(p.relative_to(REPO)) not in allowed
        ]
        assert offenders == []


class TestIdentityFromTheResolver:
    def test_missing_file_is_t0(self, capsys):
        data = emit(capsys)
        assert (data["tier"], data["role"], data["role_source"]) == ("t0", "co-author", "default")
        assert (data["commits"], data["refusal_reason"]) == ("allowed", "")
        assert data["coauthor_trailer"] == "Assisted-by: Carter"
        assert data["footer"] == DEFAULT_FOOTER

    def test_t1_gets_the_noreply_co_author(self, cfg_file, capsys):
        cfg_file.write_text(T1)
        data = emit(capsys)
        assert data["tier"] == "t1"
        assert data["coauthor_trailer"] == f"Co-authored-by: llm-bot <{EMAIL}>"

    def test_t2_uses_the_t1_style_trailer_in_slice_1(self, cfg_file, capsys):
        cfg_file.write_text(T2)
        data = emit(capsys)
        assert data["tier"] == "t2"
        assert data["coauthor_trailer"] == f"Co-authored-by: llm-bot <{EMAIL}>"

    def test_email_may_be_derived(self, cfg_file, capsys):
        cfg_file.write_text('schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\n')
        assert emit(capsys)["coauthor_trailer"].endswith(f"<{EMAIL}>")

    def test_a_file_of_old_keys_only_is_t0_and_untouched(self, cfg_file, capsys):
        text = '[attribution]\nname = "x"\nemail = "x@y.z"\nfooter = "Mine."\n'
        cfg_file.write_text(text)
        before = hashlib.sha256(cfg_file.read_bytes()).hexdigest()

        data = emit(capsys)

        assert data["tier"] == "t0"
        assert data["coauthor_trailer"] == "Assisted-by: Carter"
        assert data["footer"] == "Mine."  # an existing footer is kept as written
        assert hashlib.sha256(cfg_file.read_bytes()).hexdigest() == before
        assert [p.name for p in cfg_file.parent.iterdir()] == ["config.toml"]

    def test_emit_keys_are_exactly_the_slice_2b_set(self, capsys):
        assert set(emit(capsys)) == {
            "tier",
            "role",
            "role_source",
            "mode",
            "author",
            "committer",
            "signer_fpr",
            "coauthor_trailer",
            "coauthor_linked",
            "commits",
            "refusal_reason",
            "footer",
            "has_github_token",
        }

    def test_a_ci_run_is_a_review_run_and_commits_are_refused(self, cfg_file, capsys, monkeypatch):
        cfg_file.write_text(T1)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        data = emit(capsys)
        assert (data["mode"], data["commits"], data["refusal_reason"]) == (
            "review",
            "refused",
            "E-CI-REVIEW",
        )
        assert data["coauthor_trailer"] == "" and data["committer"] == "human"

    def test_outside_ci_the_mode_is_interactive(self, cfg_file, capsys, monkeypatch):
        cfg_file.write_text(T1)
        for name in ("GITHUB_ACTIONS", "CI", "CARTER_IDENTITY_MODE"):
            monkeypatch.delenv(name, raising=False)
        assert emit(capsys)["mode"] == "interactive"

    def test_values_follow_the_process_environment_at_runtime(self, cfg_file, capsys, monkeypatch):
        cfg_file.write_text(T1)
        monkeypatch.setenv("CARTER_IDENTITY_ROLE", "author")
        data = emit(capsys)
        assert (data["role"], data["role_source"]) == ("author", "env")
        assert (data["commits"], data["refusal_reason"]) == ("refused", "E-ROLE-B-TIER")


class TestRefusals:
    @pytest.mark.parametrize(
        "body",
        [
            'schema = 2\n[identity]\nrole = "author"\n',
            T1.replace("[identity]\n", '[identity]\nrole = "author"\n'),
        ],
        ids=["t0", "t1"],
    )
    def test_role_author_below_t2_is_refused(self, cfg_file, capsys, body):
        cfg_file.write_text(body)
        data = emit(capsys)
        assert data["role"] == "author"  # never silently downgraded
        assert (data["commits"], data["refusal_reason"]) == ("refused", "E-ROLE-B-TIER")
        assert data["coauthor_trailer"] == ""

    def test_role_author_at_t2_is_allowed(self, cfg_file, capsys):
        cfg_file.write_text(T2.replace("[identity]\n", '[identity]\nrole = "author"\n'))
        assert emit(capsys)["commits"] == "allowed"

    def test_malformed_toml_is_e_config_with_empty_identity(self, cfg_file, capsys):
        cfg_file.write_text("schema = 2\n[identity\n")
        data = emit(capsys)
        assert (data["commits"], data["refusal_reason"]) == ("refused", "E-CONFIG")
        for key in ("tier", "role", "role_source", "coauthor_trailer"):
            assert data[key] == ""
        assert data["footer"] == DEFAULT_FOOTER  # the footer degrades, it does not fail

    def test_invalid_identity_keeps_a_valid_footer(self, cfg_file, capsys):
        cfg_file.write_text(
            'schema = 2\n[identity]\nrole = "root"\n[attribution]\nfooter = "Mine."\n'
        )
        data = emit(capsys)
        assert data["refusal_reason"] == "E-CONFIG"
        assert data["footer"] == "Mine."

    def test_incomplete_signing_setup_is_e_config(self, cfg_file, capsys):
        cfg_file.write_text(T1 + '[identity.signing]\nfingerprint = "SHA256:abc"\n')
        data = emit(capsys)
        assert (data["commits"], data["refusal_reason"]) == ("refused", "E-CONFIG")

    def test_config_load_reports_the_refusal(self, cfg_file):
        cfg_file.write_text("schema = 2\n[identity\n")
        cfg = Config.load(cfg_file)
        assert (cfg.commits, cfg.refusal_reason) == ("refused", "E-CONFIG")
        assert cfg.coauthor_trailer == ""


class TestWorkspaceLookup:
    def _workspace(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / ".carter").mkdir(parents=True)
        (ws / ".carter" / "carter.yaml").write_text("mode: umbrella\n")
        (ws / "repo" / "sub").mkdir(parents=True)
        return ws

    def test_pinned_cap_applies_from_a_nested_directory(
        self, tmp_path, cfg_file, capsys, monkeypatch
    ):
        ws = self._workspace(tmp_path)
        cfg_file.write_text(T2 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t1"\n')
        monkeypatch.chdir(ws / "repo" / "sub")
        assert emit(capsys)["tier"] == "t1"

    def test_other_directories_do_not_get_the_cap(self, tmp_path, cfg_file, capsys, monkeypatch):
        ws = self._workspace(tmp_path)
        cfg_file.write_text(T2 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t0"\n')
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        assert emit(capsys)["tier"] == "t2"

    def test_symlinked_workspace_resolves_to_the_pinned_key(
        self, tmp_path, cfg_file, capsys, monkeypatch
    ):
        ws = self._workspace(tmp_path)
        link = tmp_path / "link"
        link.symlink_to(ws, target_is_directory=True)
        cfg_file.write_text(T2 + f'[workspaces."{ws.resolve()}"]\nmax_tier = "t0"\n')
        monkeypatch.chdir(link / "repo")
        assert emit(capsys)["tier"] == "t0"

    def test_pinned_workspace_role_wins_over_the_session_env(
        self, tmp_path, cfg_file, capsys, monkeypatch
    ):
        ws = self._workspace(tmp_path)
        cfg_file.write_text(T1 + f'[workspaces."{ws.resolve()}"]\nrole = "co-author"\n')
        monkeypatch.setenv("CARTER_IDENTITY_ROLE", "author")
        monkeypatch.chdir(ws)
        data = emit(capsys)
        assert (data["role_source"], data["commits"]) == ("workspace", "allowed")


class TestFooter:
    def test_default_footer_names_carter_not_carter_bot(self):
        assert Config.load(Path("/nonexistent/config.toml")).footer == DEFAULT_FOOTER

    def test_an_existing_footer_is_kept_exactly(self, cfg_file):
        cfg_file.write_text('schema = 2\n[attribution]\nfooter = "Mine."\n')
        assert Config.load(cfg_file).footer == "Mine."


class TestReadsNeverWrite:
    def test_load_and_emit_leave_the_directory_alone(self, cfg_file, capsys):
        cfg_file.write_text(T1)
        before = sorted(p.name for p in cfg_file.parent.iterdir())
        Config.load(cfg_file)
        emit(capsys)
        assert sorted(p.name for p in cfg_file.parent.iterdir()) == before


class TestRuntimeFields2b:
    """who the author, the committer and the signer are right here."""

    def test_t0_everything_is_the_human(self, capsys):
        data = emit(capsys)
        assert (data["author"], data["committer"], data["signer_fpr"]) == ("human", "human", "")
        assert data["coauthor_linked"] is False  # `Assisted-by: Carter` carries no address

    def test_t1_is_human_author_and_committer_with_a_linked_co_author(self, cfg_file, capsys):
        cfg_file.write_text(T1)
        data = emit(capsys)
        assert (data["author"], data["committer"], data["signer_fpr"]) == ("human", "human", "")
        assert data["coauthor_linked"] is True

    def test_t2_has_the_llm_as_committer_and_the_public_fingerprint(self, cfg_file, capsys):
        cfg_file.write_text(T2 + 'private_key_path = "/home/u/.ssh/llm_secret_key"\n')
        data = emit(capsys)
        assert (data["author"], data["committer"], data["signer_fpr"]) == (
            "human",
            "llm",
            "SHA256:abc",
        )
        assert data["commits"] == "allowed"
        assert "llm_secret_key" not in json.dumps(data) and "private" not in json.dumps(data)

    def test_a_cap_below_t2_drops_the_signer(self, cfg_file, capsys, tmp_path, monkeypatch):
        cfg_file.write_text(T2 + f'[workspaces."{tmp_path.resolve()}"]\nmax_tier = "t1"\n')
        monkeypatch.chdir(tmp_path)
        data = emit(capsys)
        assert (data["tier"], data["committer"], data["signer_fpr"]) == ("t1", "human", "")

    def test_a_refusal_keeps_the_reason_and_allows_nothing(self, cfg_file, capsys):
        cfg_file.write_text("schema = 2\n[identity\nbroken")
        data = emit(capsys)
        assert data["commits"] == "refused" and data["refusal_reason"] == "E-CONFIG"
        assert (data["committer"], data["signer_fpr"], data["coauthor_trailer"]) == ("", "", "")
