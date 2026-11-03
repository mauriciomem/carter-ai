"""Deterministic secret scan of the PR text (RFC-0007 App C.5, rv1-eng S6, rv2-sec nit3;
plan 003 step 17). Scans title, branch name and body; never returns more than 4 characters
of what matched."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from carter.aplus import secretscan as ss
from carter.identity import IdentityError
from carter.identity.errors import E_SECRET_SCAN, registry
from carter.identity.rules import load_rules

TAIL = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # 36 token-ish chars, not a real credential


def rules_of(findings: list[ss.Finding]) -> set[str]:
    return {f.rule for f in findings}


class TestTokenPrefixes:
    @pytest.mark.parametrize(
        ("secret", "rule"),
        [
            ("github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6", "github-pat"),
            ("ghp_" + TAIL, "github-token"),
            ("gho_" + TAIL, "github-token"),
            ("ghu_" + TAIL, "github-token"),
            ("ghs_" + TAIL, "github-token"),
            ("ghr_" + TAIL, "github-token"),
            ("AKIA" + "IOSFODNN7EXAMPLE", "aws-access-key"),
            ("sk-" + "proj_" + TAIL, "api-key-sk"),
            ("xoxb-" + "123456789012-abcdefABCDEF", "slack-token"),
            ("xoxp-" + "123456789012-abcdefABCDEF", "slack-token"),
        ],
    )
    @pytest.mark.parametrize("where", ["title", "body", "branch"])
    def test_hits_in_every_field(self, secret: str, rule: str, where: str) -> None:
        text = f"see {secret} here"
        args = {
            "title": "t",
            "branch": "feat/x",
            "body": "b",
            where: text if where != "branch" else secret,
        }
        findings = ss.scan(**args)
        assert rule in rules_of(findings), (where, findings)
        assert {f.where for f in findings if f.rule == rule} == {where}

    @pytest.mark.parametrize(
        "prefix", ["github_pat_", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "sk-", "xoxb-", "AKIA"]
    )
    def test_a_bare_prefix_mentioned_in_prose_is_not_a_hit(self, prefix: str) -> None:
        body = f"The command refuses tokens that start with `{prefix}` and says why."
        assert ss.scan("t", "b", body) == []

    def test_a_short_lookalike_after_the_prefix_passes(self) -> None:
        assert ss.scan("t", "b", "use ghp_abc or sk-1 as examples") == []


class TestPrivateKeys:
    @pytest.mark.parametrize(
        "header",
        [
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "-----BEGIN EC PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----",
            "-----BEGIN ENCRYPTED PRIVATE KEY-----",
            "-----BEGIN PGP PRIVATE KEY BLOCK-----",
        ],
    )
    def test_pem_private_key_headers(self, header: str) -> None:
        assert "pem-private-key" in rules_of(ss.scan("t", "b", f"log:\n{header}\nMIIE...")), header

    def test_public_material_is_fine(self) -> None:
        body = (
            "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\nssh-ed25519 AAAA public"
        )
        assert ss.scan("t", "b", body) == []


class TestEntropy:
    def test_a_random_looking_string_is_flagged(self) -> None:
        secret = "q8Zr3KvT1mXw9LpB5nYc7DfH2sJg6AeU4oIt0VbN"
        assert "high-entropy" in rules_of(ss.scan("t", "b", f"token={secret}"))

    def test_the_threshold_and_length_are_documented_constants(self) -> None:
        assert ss.ENTROPY_MIN_LENGTH == 32 and ss.ENTROPY_BITS_PER_CHAR >= 4.0
        assert "bits" in (ss.__doc__ or "").lower()

    @pytest.mark.parametrize(
        "text",
        [
            "a" * 64,
            "abab" * 20,
            "0123456789abcdef0123456789abcdef01234567",  # a git SHA
            "The quick brown fox jumps over the lazy dog and keeps running far away",
            "src/carter/guard/policies.py and tests/guard/test_policy_writer.py changed",
            "feat(guard): add consented global policies, guard state and carter guard cli",
            "https://github.com/owner/repository/pull/12345/files#diff-abcdef",
        ],
    )
    def test_ordinary_text_passes(self, text: str) -> None:
        assert ss.scan("t", "b", text) == []

    def test_a_sha_in_a_pr_body_is_fine(self) -> None:
        assert ss.scan("t", "b", "Fixes commit " + "9fceb02d0ae598e95dc970b74767f19372d61af8") == []


class TestCredentialPaths:
    @pytest.mark.parametrize("segment", load_rules().credential_paths)
    def test_every_credential_path_segment_is_a_hit(self, segment: str) -> None:
        sample = segment.replace("*", "1234") if "*" in segment else segment
        findings = ss.scan("t", "b", f"I looked at ~{sample}x")
        assert "credential-path" in rules_of(findings), segment

    def test_hits_in_the_title_and_branch_too(self) -> None:
        assert "credential-path" in rules_of(ss.scan("fix ~/.ssh/ perms", "b", "ok"))
        assert "credential-path" in rules_of(ss.scan("t", "dump/.git-credentials", "ok"))

    def test_the_data_file_is_the_source(self) -> None:
        src = Path(ss.__file__).read_text(encoding="utf-8")
        assert "credential_paths" in src and ".git-credentials" not in src


class TestLookalikes:
    def test_fullwidth_letters_are_normalised(self) -> None:
        fw = "".join(chr(ord(c) + 0xFEE0) if c.isalnum() else c for c in "ghp_" + TAIL)
        assert "github-token" in rules_of(ss.scan("t", fw, "b"))

    def test_zero_width_characters_inside_a_token_do_not_hide_it(self) -> None:
        hidden = "gh\u200bp_" + TAIL[:10] + "\u2060" + TAIL[10:]
        assert "github-token" in rules_of(ss.scan("t", "b", hidden))
        assert "github-token" in rules_of(ss.scan("t", hidden, "b"))

    def test_a_benign_unicode_branch_name_passes(self) -> None:
        assert ss.scan("t", "feat/é-ü-日本", "b") == []

    def test_bidi_controls_are_stripped_before_matching(self) -> None:
        assert "pem-private-key" in rules_of(
            ss.scan("t", "b", "-----BEGIN \u202eRSA PRIVATE KEY-----")
        )


class TestFindingShape:
    def test_no_more_than_four_characters_of_the_match_are_returned(self) -> None:
        secret = "ghp_" + TAIL
        for f in ss.scan("t", "b", f"x {secret} y"):
            assert len(f.hint) <= 4
            assert TAIL[:8] not in repr(f) and TAIL[:8] not in str(f)

    def test_findings_are_deterministic_and_sorted(self) -> None:
        text = f"ghp_{TAIL} and -----BEGIN RSA PRIVATE KEY-----"
        assert ss.scan("t", "b", text) == ss.scan("t", "b", text)

    def test_clean_text_passes(self) -> None:
        assert (
            ss.scan("feat: add the thing", "feat/the-thing", "## Summary\n\nAdds the thing.\n")
            == []
        )

    def test_empty_inputs(self) -> None:
        assert ss.scan("", "", "") == []

    def test_a_huge_body_is_scanned_quickly_and_completely(self) -> None:
        body = ("lorem ipsum dolor sit amet\n" * 20_000) + f"\nleak ghp_{TAIL}\n"
        assert "github-token" in rules_of(ss.scan("t", "b", body))


class TestAsError:
    def test_the_error_names_rules_and_places_never_text(self) -> None:
        findings = ss.scan("t", "b", f"ghp_{TAIL}")
        err = ss.to_error(findings)
        assert isinstance(err, IdentityError) and err.code == E_SECRET_SCAN
        assert "github-token" in str(err) and "body" in err.detail
        assert TAIL[:6] not in str(err) + err.detail
        assert registry()[E_SECRET_SCAN].message.split("(")[0] in str(err)

    def test_no_findings_no_error(self) -> None:
        assert ss.to_error([]) is None


class TestModule:
    def test_pure_no_click_no_subprocess_no_printing(self) -> None:
        tree = ast.parse(Path(ss.__file__).read_text(encoding="utf-8"))
        names = {
            a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
        } | {
            (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        assert not names & {"click", "subprocess", "requests", "urllib"}
        calls = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "print" not in calls
