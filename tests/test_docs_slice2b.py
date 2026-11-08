"""User docs for slice 2b (plan 005): documented options equal ``--help``, the error codes named in
the docs are the registered ones. Grows with each documented command (steps 11, 15-17, 22, 28)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from carter.identity.errors import registry
from test_docs_slice1g import documented, help_options, section, text

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestIdentityReference:
    @pytest.mark.parametrize("sub", ["unlock", "lock", "add", "show", "verify", "remove"])
    def test_documented_options_equal_help(self, sub: str) -> None:
        block = section(text("reference/cli.md"), f"carter identity {sub}", "###")
        assert documented(block) == help_options("identity", sub)

    def test_the_group_is_listed_in_the_command_table(self) -> None:
        assert "[`identity`](#carter-identity)" in text("reference/cli.md")

    def test_every_error_code_the_section_names_is_registered(self) -> None:
        block = section(text("reference/cli.md"), "carter identity")
        for code in set(re.findall(r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+", block)):
            assert code in registry(), code

    def test_the_unlock_refusals_are_documented(self) -> None:
        block = " ".join(section(text("reference/cli.md"), "carter identity unlock", "###").split())
        for needle in ("OPENCODE_TERMINAL", "E-UNLOCK-OPENCODE", "E-UNLOCK-TTY"):
            assert needle in block


class TestCommitReference:
    def test_the_refused_flags_documented_are_the_frozen_list(self) -> None:
        from carter.identity.commit import REFUSED_FLAGS

        block = " ".join(section(text("reference/cli.md"), "carter commit", "##").split())
        for flag in REFUSED_FLAGS:
            assert flag.replace("<arg>", "<key>") in block, flag

    def test_every_error_code_the_section_names_is_registered(self) -> None:
        for code in set(
            re.findall(
                r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+",
                section(text("reference/cli.md"), "carter commit", "##"),
            )
        ):
            assert code in registry(), code

    def test_the_help_names_the_same_refused_long_flags(self) -> None:
        refused = {"--no-verify", "--no-gpg-sign", "--gpg-sign", "--signoff", "--author"}
        assert refused <= help_options("commit") <= refused | {"--reset-author"}


GUIDE = "guides/identity-and-signing.md"
CODES_WITH_ROWS = (
    "E-SIGN-LOCKED", "E-SIGN-NOAGENT", "E-SIGN-UNAVAILABLE", "E-SHIM-REFUSED",
    "E-SIGN-HUMAN-FALLBACK", "E-UNLOCK-OPENCODE", "E-UNLOCK-TTY",
    "E-UNLOCK-PATH", "E-UNLOCK-BADPASS", "E-GUARD-NOIDENT", "E-GUARD-COMMITTER",
    "E-GUARD-SIGNCFG", "E-GUARD-TRAILER", "E-GUARD-T01SIGN", "E-GUARD-UNSIGNED",
    "E-TIER-CAPPED", "E-TIER-REQUIRED", "E-IDENTITY-CHECK", "E-GITHUB-UNREACHABLE",
    "E-SSH-OLD", "E-GIT-OLD", "E-ROLE-B-TIER",
)  # fmt: skip


class TestTroubleshootingRows2b:
    def table(self) -> str:
        return section(text("troubleshooting.md"), "Signing and the LLM identity")

    def test_every_code_in_the_doc_is_registered(self) -> None:
        for code in set(re.findall(r"`?(E-[A-Z0-9]+(?:-[A-Z0-9]+)+)", text("troubleshooting.md"))):
            assert code in registry(), code

    def test_every_2b_user_facing_code_has_a_row(self) -> None:
        body = text("troubleshooting.md")
        for code in CODES_WITH_ROWS:
            assert re.search(rf"`{code}\b", body), code

    def test_the_locked_key_row_has_the_raw_git_strings_and_the_one_fix(self) -> None:
        body = " ".join(self.table().split())
        assert "Couldn't find key in agent?" in body and "Couldn't get agent socket" in body
        assert "fatal: failed to write commit object" in body and "carter identity unlock" in body
        assert "changes are still staged" in body

    def test_the_unsigned_badge_row_points_at_the_vigilant_table(self) -> None:
        assert "#the-vigilant-mode-table" in self.table()


class TestIdentityGuide:
    def guide(self) -> str:
        return " ".join(text(GUIDE).split())

    def test_it_covers_what_the_plan_requires(self) -> None:
        guide = self.guide()
        for needle in (
            "## Roles",
            "## Tiers",
            "## The vigilant mode table",
            "## Merge strategy",
            "## Password managers",
            "## macOS notes",
            "## Workspace caps",
            "Worktree limit",
            "Signing key",
            "Authentication Key",
            "carter identity add",
            "carter identity unlock",
            "--extend",
            "carter commit",
            "git ai-commit",
            "CODEOWNERS",
            "Type, never paste",
            "What signing does not protect",
            "Squash and merge",
            "$TMPDIR/carter-<uid>/",
            "ssh_bin_dir",
            "agent.toml",
        ):
            assert needle in guide, needle

    def test_the_tier_table_quotes_the_trailers_the_emit_prints(self) -> None:
        guide = self.guide()
        assert (
            "Assisted-by: Carter" in guide
            and "Co-authored-by: <LLM login> <noreply address>" in guide
        )

    def test_the_agent_state_table_names_the_fixes_the_command_prints(self) -> None:
        from carter.identity_show import PROBE_TEXT

        guide = self.guide()
        fixes = {fix for _, _, fix in PROBE_TEXT.values() if fix}
        assert any("carter identity unlock" in f for f in fixes)
        assert (
            "`carter identity lock --all`, then `unlock`" in guide
            and "`carter identity unlock`" in guide
        )

    def test_no_link_into_the_local_only_folders(self) -> None:
        for target in re.findall(r"\]\(([^)]+)\)", text(GUIDE)):
            assert "/adr/" not in target and "/rfcs/" not in target, target

    def test_it_is_in_the_index_and_the_readme(self) -> None:
        assert "guides/identity-and-signing.md" in text("README.md")
        assert "identity-and-signing.md" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


class TestNoDocTeachesABypass:
    def docs(self) -> list[tuple[str, str]]:
        root = REPO_ROOT / "docs"
        skip = {"adr", "rfcs"}
        return [
            (str(p.relative_to(root)), p.read_text(encoding="utf-8"))
            for p in root.rglob("*.md")
            if not skip & set(p.parts)
        ]

    def test_the_removed_passphrase_flag_is_not_documented(self) -> None:
        for name, body in self.docs():
            assert "--allow-no-passphrase" not in body, name  # D68 d reversed D50

    def test_edit_automatically_only_appears_as_a_warning(self) -> None:
        for name, body in self.docs():
            for line in body.splitlines():
                if "Edit Automatically" in line:
                    assert (
                        re.search(r"never|would point", line, re.I)
                        or "Never" in body.split(line)[0][-200:]
                    ), (name, line)

    def test_signing_flags_are_only_ever_named_to_forbid_them(self) -> None:
        for name, body in self.docs():
            for para in body.split("\n\n"):
                if re.search(r"--no-gpg-sign|-S<key>|--gpg-sign=<key>", para):
                    assert re.search(
                        r"never|refus|not accept|forbid|fails|plain `git commit`", para, re.I
                    ), (name, para[:100])

    def test_a_pasted_bang_line_is_never_advice(self) -> None:
        for name, body in self.docs():
            for line in body.splitlines():
                if re.search(r"paste", line, re.I) and "`!" in line:
                    assert re.search(r"never|not|instead", line, re.I), (name, line)


class TestHooksRevision2ExplanationMatchesTheInstaller:
    def test_the_install_guide_row_quotes_the_installer_facts(self) -> None:
        from carter.identity.policyset import consent_groups

        hooks = next(g for g in consent_groups() if g.id == "hooks")
        row = " ".join(
            next(
                ln for ln in text("guides/install.md").splitlines() if ln.startswith("| `hooks`")
            ).split()
        )
        explained = " ".join(hooks.explain)
        for fact in ("prepare-commit-msg", "commit-msg", "post-commit"):
            assert fact in row and fact in explained, fact
        assert "pre-push" in row and "revision 2" in row and "revision 2" in explained
