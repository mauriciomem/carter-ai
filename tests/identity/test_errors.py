"""The identity error registry (RFC-0007 Appendix B §2; plan 002 step 14)."""

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
    SLICES,
    registry,
    render_error_table,
)

REPO = Path(__file__).resolve().parents[2]
RFC_APPENDIX = (
    REPO / "docs" / "rfcs" / "0007-llm-attribution-signing" / "appendix-b-cli-and-errors.md"
)
CODE_RE = re.compile(r"^E-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
SLICE_1 = {E_CONFIG, E_ROLE_B_TIER, E_TIER_REQUIRED, E_COMMIT_T1}
ADDED_BEYOND_APPENDIX_B = {
    "E-HUMAN-TERMINAL",
    "E-STATE-INVALID",
    "E-APLUS-ARGS",
    "E-PROBE-SCOPE",  # plan 004 G14
    "E-FALSE-MISSING",
    "E-IDENTITY-CHECK",  # plan 005 H16
    "E-GITHUB-UNREACHABLE",
}


class TestRegistry:
    def test_codes_are_unique_stable_and_well_formed(self):
        raw = resources.files("carter.identity").joinpath("errors.json").read_text("utf-8")
        codes = re.findall(r'"code":\s*"([^"]+)"', raw)
        assert len(codes) == len(set(codes)) == len(registry())
        assert all(CODE_RE.match(c) for c in codes)

    def test_every_entry_is_complete(self):
        for entry in registry().values():
            assert entry.code and entry.where.strip() and entry.message.strip()
            assert entry.slice in SLICES
            assert isinstance(entry.remediation, str)

    def test_slice_1_codes(self):
        assert {c for c, e in registry().items() if e.slice == "1"} == SLICE_1

    def test_other_codes_are_registered_for_their_own_slice(self):
        others = {c: e.slice for c, e in registry().items() if c not in SLICE_1}
        assert others and "1" not in others.values()
        assert others["E-GATE"] == "2a"
        assert others["E-SIGN-LOCKED"] == "2b"
        assert others["E-B-DEFAULT"] == "B"
        assert others["E-PAT-TYPE"] == "1G"

    def test_slice_1_wording_is_appendix_b_verbatim(self):
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

    @pytest.mark.skipif(not RFC_APPENDIX.is_file(), reason="local RFC files are absent (CI)")
    def test_codes_match_the_rfc_error_table(self):
        text = RFC_APPENDIX.read_text(encoding="utf-8")
        table = text.split("## 2. Error table")[1].split("## 3.")[0]
        in_rfc: set[str] = set()
        for row in table.splitlines():
            if row.startswith("| E-"):
                first = row.split("|")[1]
                in_rfc.update(re.findall(r"E-[A-Z0-9-]+", first))
        # Codes the 1G architect gate added beyond Appendix B (plan 003 step 6, F10).
        assert set(registry()) - ADDED_BEYOND_APPENDIX_B == in_rfc


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
        assert len(Path(errors_mod.__file__).read_text().splitlines()) <= 120


class TestRenderErrorTable:
    def test_is_marked_and_deterministic(self):
        table = render_error_table()
        assert table.startswith(ERRORS_BEGIN + "\n") and table.rstrip().endswith(ERRORS_END)
        assert table == render_error_table()

    def test_slice_1_lists_only_slice_1_codes_in_registry_order(self):
        rows = [ln for ln in render_error_table(current="1").splitlines() if ln.startswith("| `E-")]
        codes = [re.match(r"\| `([^`]+)`", ln).group(1) for ln in rows]
        assert codes == [c for c in registry() if c in SLICE_1]

    def test_the_current_slice_is_2a_and_lists_every_code_up_to_it(self):
        # plan 004 step 34: one constant (rules.CURRENT_SLICE), imported by errors.py
        assert errors_mod.CURRENT_SLICE == "2a"
        rows = [ln for ln in render_error_table().splitlines() if ln.startswith("| `E-")]
        codes = {re.match(r"\| `([^`]+)`", ln).group(1) for ln in rows}
        upto = {c for c, e in registry().items() if e.slice in {"1", "1G", "2a"}}
        assert codes == upto
        assert {
            "E-POLICY", "E-GH-READONLY", "E-HANDOFF", "E-SECRET-SCAN", "E-HUMAN-TERMINAL",
            "E-ISOLATION-MISSING", "E-GATE", "E-GATE-FAIL", "E-PUSH-GUARD", "E-GIT-OLD",
            "E-OPENCODE-VERSION", "E-SIGN-UNAVAILABLE",
        } <= codes  # fmt: skip
        assert "E-GUARD-UNSIGNED" not in codes and "E-B-CALLER" not in codes  # 2b and B

    def test_earlier_slices_are_a_prefix_and_later_ones_extend_it(self):
        assert "E-GATE" not in render_error_table(current="1G")
        assert "E-GATE" in render_error_table(current="2a")
        assert "E-GUARD-UNSIGNED" in render_error_table(current="2b")

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
    """Spike 4 (plan 003, 2026-11-02): the strings GitHub really sent for a read-only PAT."""

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
        assert "carter push" in entry.remediation and "own terminal" in entry.remediation

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
        assert "this looks like" not in type_.message and "4-character prefix" in type_.message
        assert "0700" in perm.remediation and "carter github-token set" in perm.remediation
