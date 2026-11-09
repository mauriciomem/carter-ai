"""The identity error registry."""

from __future__ import annotations

import ast
import re
from importlib import resources
from pathlib import Path

import pytest

from carter.identity import ConfigError, IdentityError
from carter.identity import errors as errors_mod
from carter.identity.errors import (
    E_COMMIT_T1,
    E_CONFIG,
    E_ROLE_B_TIER,
    E_TIER_REQUIRED,
    ERRORS_BEGIN,
    ERRORS_END,
    registry,
    render_error_table,
)

REPO = Path(__file__).resolve().parents[2]
CODE_RE = re.compile(r"^E-[A-Z0-9]+(?:-[A-Z0-9]+)*$")


class TestRegistry:
    def test_codes_are_unique_stable_and_well_formed(self):
        raw = resources.files("carter.identity").joinpath("errors.json").read_text("utf-8")
        codes = re.findall(r'"code":\s*"([^"]+)"', raw)
        assert len(codes) == len(set(codes)) == len(registry())
        assert all(CODE_RE.match(c) for c in codes)

    def test_every_entry_is_complete(self):
        for entry in registry().values():
            assert entry.code and entry.where.strip() and entry.message.strip()
            assert isinstance(entry.remediation, str)

    def test_core_wording(self):
        r = registry()
        assert (
            r[E_CONFIG].message == "config.toml is invalid; agent commits are disabled until fixed."
        )
        assert r[E_CONFIG].remediation == "Never falls back to defaults."
        assert (
            r[E_ROLE_B_TIER].message
            == "Role `author` needs a signing key; refusing (no downgrade)."
        )
        assert (
            r[E_TIER_REQUIRED].message
            == "This workspace requires tier `<t>`; configure the LLM identity."
        )
        assert (
            r[E_COMMIT_T1].message
            == "No LLM signing key (T1): committed unsigned with `Co-authored-by: LLM`."
        )


class TestUsedByCode:
    def test_config_error_carries_its_registry_code_and_text(self):
        err = ConfigError("TOML syntax error")
        assert err.code == E_CONFIG
        assert str(err) == registry()[E_CONFIG].message
        assert err.detail == "TOML syntax error"

    def test_identity_error_defaults_to_the_registry_message(self):
        err = IdentityError(E_ROLE_B_TIER)
        assert str(err) == registry()[E_ROLE_B_TIER].message

    def test_resolver_refusals_use_registry_codes(self):
        from carter.identity import resolve
        from carter.identity.schema import Identity, IdentityConfig

        res = resolve(IdentityConfig(identity=Identity(role="author")), workspace=None, env={})
        assert res.refusal_reason == E_ROLE_B_TIER
        with pytest.raises(IdentityError) as exc:
            res.ensure_commits_allowed()
        assert str(exc.value) == registry()[E_ROLE_B_TIER].message

    def test_pin_command_reports_the_registry_code(self):
        # cli.py formats the code from the exception, not from a typed string.
        source = (REPO / "carter" / "cli.py").read_text(encoding="utf-8")
        assert "exc.code" in source


class TestNoSecretsInMessages:
    LEAKY = [
        r"ghp_[A-Za-z0-9]{8,}",
        r"github_pat_[A-Za-z0-9_]{10,}",
        r"-----BEGIN",
        r"ssh-(?:ed25519|rsa) AAAA",
        r"SHA256:[A-Za-z0-9+/]{20,}",
        r"\$\{?[A-Z_]{3,}",  # an expanded environment variable
        r"\b[A-Z][A-Z0-9_]{3,}=\S",  # NAME=value
        r"Bearer \S+",
    ]

    @pytest.mark.parametrize("entry", list(registry().values()), ids=lambda e: e.code)
    def test_no_env_values_tokens_or_key_material(self, entry):
        text = f"{entry.where} {entry.message} {entry.remediation}"
        for pattern in self.LEAKY:
            assert not re.search(pattern, text), (entry.code, pattern)

    def test_the_hermetic_environment_values_never_appear(self):
        import os

        values = [v for k, v in os.environ.items() if k in {"HOME", "XDG_CONFIG_HOME"}]
        blob = "\n".join(f"{e.message} {e.remediation}" for e in registry().values())
        assert all(v not in blob for v in values)


class TestSingleSource:
    def test_no_other_module_defines_error_code_strings(self):
        pattern = re.compile(r"\bE-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b")
        offenders: dict[str, list[str]] = {}
        for src in (REPO / "carter").rglob("*.py"):
            if src.name == "errors.py" and src.parent.name == "identity":
                continue
            tree = ast.parse(src.read_text(encoding="utf-8"))
            docstrings = {
                id(n.body[0].value)
                for n in ast.walk(tree)
                if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef)
                and n.body
                and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
            }
            hits = [
                m
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                for m in pattern.findall(node.value)
            ]
            if hits:
                offenders[str(src.relative_to(REPO))] = hits
        assert offenders == {}

    def test_errors_module_stays_small(self):
        assert len(Path(errors_mod.__file__).read_text().splitlines()) <= 160


class TestRenderErrorTable:
    def test_is_marked_and_deterministic(self):
        table = render_error_table()
        assert table.startswith(ERRORS_BEGIN + "\n") and table.rstrip().endswith(ERRORS_END)
        assert table == render_error_table()

    def test_it_lists_every_agent_facing_code_and_no_human_facing_one(self):
        rows = [ln for ln in render_error_table().splitlines() if ln.startswith("| `E-")]
        codes = {re.match(r"\| `([^`]+)`", ln).group(1) for ln in rows}
        assert codes == set(registry()) - errors_mod.HUMAN_FACING
        agent_2b = {
            "E-SIGN-LOCKED", "E-SIGN-NOAGENT", "E-SIGN-UNAVAILABLE", "E-SIGN-AGENT-REFUSE",
            "E-SHIM-REFUSED", "E-GUARD-NOIDENT", "E-GUARD-COMMITTER", "E-GUARD-SIGNCFG",
            "E-GUARD-TRAILER", "E-GUARD-T01SIGN", "E-GUARD-UNSIGNED", "E-TIER-CAPPED",
            "E-TIER-REQUIRED", "E-ROLE-B-TIER",
        }  # fmt: skip
        assert agent_2b <= codes and "E-HUMAN-IDENTITY" in codes
        human = {
            "E-UNLOCK-TTY",
            "E-UNLOCK-OPENCODE",
            "E-UNLOCK-PATH",
            "E-UNLOCK-BADPASS",
            "E-SIGN-HUMAN-FALLBACK",
            "E-SSH-OLD",
            "E-IDENTITY-CHECK",
            "E-GITHUB-UNREACHABLE",
        }
        assert not human & codes and human <= set(registry())  # in the docs, not in the agent table
        assert {
            "E-POLICY", "E-GH-READONLY", "E-HUMAN-TERMINAL",
            "E-ISOLATION-MISSING", "E-GATE", "E-GATE-FAIL", "E-PUSH-GUARD", "E-GIT-OLD",
            "E-OPENCODE-VERSION", "E-SIGN-UNAVAILABLE",
        } <= codes  # fmt: skip
        assert {
            "E-B-CALLER", "E-B-DWELL", "E-B-TIMEOUT", "E-B-HEADLESS", "E-B-POLLUTED", "E-B-NOAGENT",
            "E-B-HTTPS", "E-B-MOVED", "E-B-DEFAULT", "E-B-ARGS", "E-B-REJECTED",
        } <= codes  # fmt: skip

    def test_cells_escape_pipes(self):
        assert "\\|" not in render_error_table() or all(
            row.count("|") - row.count("\\|") == 5
            for row in render_error_table().splitlines()
            if row.startswith("| `E-")
        )

    def test_every_row_has_four_cells(self):
        for row in render_error_table().splitlines():
            if row.startswith("| `E-"):
                assert row.count("|") - row.count("\\|") == 5


class TestObservedTexts:
    """The strings GitHub sends for a token that cannot write."""

    def test_gh_readonly_stores_the_observed_lines_and_the_api_message(self):
        entry = registry()["E-GH-READONLY"]
        assert entry.observed == (
            "remote: Permission to <o>/<r>.git denied to <login>.",
            "fatal: unable to access 'https://github.com/<o>/<r>.git/': "
            "The requested URL returned error: 403",
            "gh: Resource not accessible by personal access token (HTTP 403)",
        )
        assert "Resource not accessible by personal access token" in entry.message
        assert "unverified" not in entry.message
        assert "carter push" in entry.remediation and "!carter push" in entry.remediation

    def test_observed_is_data_only_and_empty_elsewhere(self):
        assert all(e.observed == () for c, e in registry().items() if c != "E-GH-READONLY")
        assert "observed" not in render_error_table()

    def test_the_policy_remediation_says_which_gh_verbs_are_positional(self):
        text = registry()["E-POLICY"].remediation
        assert "-R <owner>/<repo>" in text and "after the subcommand" in text
        assert "gh repo view <owner>/<repo>" in text and "gh search repos <query>" in text
        assert "no `-R`" in text


class TestPatCodes:
    def test_pat_type_and_perm_say_what_to_do_and_never_promise_to_quote(self):
        type_, perm = registry()["E-PAT-TYPE"], registry()["E-PAT-PERM"]
        assert (
            "carter github-token set" in type_.remediation and "own terminal" in type_.remediation
        )
        assert "this looks like" not in type_.message and "github_pat_" in type_.message
        assert "0700" in perm.remediation and "carter github-token set" in perm.remediation
