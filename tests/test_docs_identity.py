"""The identity, signing and role-author docs match the code.

The guide covers the tiers and the role; the codes and constants it names are the code's own;
the troubleshooting rows quote what the commands print; and no doc teaches a way to sign or
author with the wrong key.
"""

from __future__ import annotations

import re
from pathlib import Path

from carter.identity import coauthor
from carter.identity.errors import registry
from carter.identity.rules import human_identity_rules
from docs_support import codes_in, norm, section, text, user_docs

GUIDE = "guides/identity-and-signing.md"
ROLE = "Role `author`: the LLM is the author"


def guide() -> str:
    return norm(text(GUIDE))


def role_section() -> str:
    return norm(section(text(GUIDE), ROLE))


class TestGuide:
    def test_it_covers_the_topic(self) -> None:
        body = guide()
        for needle in (
            "## Roles", "## Tiers", "## The vigilant mode table", "## Merge strategy",
            "## Password managers", "## macOS notes", "## Workspace caps",
            "Worktree limit", "Signing key", "Authentication Key", "carter identity add",
            "carter identity unlock", "--extend", "carter commit", "git ai-commit",
            "CODEOWNERS", "Type, never paste", "What signing does not protect",
            "Squash and merge", "$TMPDIR/carter-<uid>/", "ssh_bin_dir", "agent.toml",
        ):  # fmt: skip
            assert needle in body, needle

    def test_the_tier_table_quotes_the_trailers_the_emit_prints(self) -> None:
        body = guide()
        assert "Assisted-by: Carter" in body
        assert "Co-authored-by: <LLM login> <noreply address>" in body
        assert "Co-authored-by" in norm(text("guides/write-operations.md"))

    def test_the_agent_state_table_names_the_fixes_the_command_prints(self) -> None:
        from carter.identity_show import PROBE_TEXT

        fixes = {fix for _, _, fix in PROBE_TEXT.values() if fix}
        assert any("carter identity unlock" in f for f in fixes)
        assert "`carter identity lock --all`, then `unlock`" in guide()

    def test_a_locked_key_asks_nothing_at_carter_commit(self) -> None:
        body = guide()
        assert "Key locked: Carter asks nothing" in body
        assert "✗ key locked → carter identity unlock" in body

    def test_it_is_linked_from_the_index_and_the_readme(self) -> None:
        assert GUIDE in text("README.md")
        assert "identity-and-signing.md" in user_docs()["README.md"]

    def test_the_codes_it_names_are_registered(self) -> None:
        assert codes_in(text(GUIDE)) <= set(registry())


class TestRoleAuthor:
    def test_it_covers_the_role(self) -> None:
        body = role_section()
        for needle in (
            "author and the committer",
            "Co-authored-by: <your user.name> <your user.email>",
            "carter identity add --login <name> --role author",
            "CARTER_IDENTITY_ROLE",
            "The workspace pin, then `CARTER_IDENTITY_ROLE`, then `[identity] role`",
            "It never degrades",
            "E-ROLE-B-TIER",
            "E-HUMAN-IDENTITY",
            "includeIf",
            "yes (noreply)",
            "yes (verified)",
            "coauthor-link.json",
            "7 days",
            "Not for projects that check a DCO sign-off",
            "Squash-merging",
            "vigilant mode",
            "Partially verified",
            "carter commit` ignores the role",
        ):
            assert needle in body, needle

    def test_the_cache_name_and_lifetime_are_the_codes(self) -> None:
        body = role_section()
        assert Path(coauthor.LINK_CACHE_REL).name in body
        assert f"{coauthor.LINK_CACHE_TTL_S // 86400} days" in body
        files = norm(text("reference/files-and-paths.md"))
        assert coauthor.LINK_CACHE_REL.removeprefix(".carter/") in files

    def test_the_fallbacks_in_the_troubleshooting_row_are_the_rules_files(self) -> None:
        row = next(
            ln for ln in text("troubleshooting.md").splitlines() if "`E-HUMAN-IDENTITY`" in ln
        )
        rules = human_identity_rules()
        name, email = rules["fallback_pairs"][0]
        assert name in row and email in row
        assert all(e.split("*")[0] in row for e in rules["fallback_emails"])

    def test_the_dco_files_are_the_ones_check_host_looks_for(self) -> None:
        from carter.human_items import DCO_FILES

        body = role_section()
        for name in DCO_FILES:
            assert name in body, name

    def test_the_variable_is_set_before_opencode_starts_and_the_agent_cannot_change_it(
        self,
    ) -> None:
        body = guide()
        assert "**before** OpenCode starts" in body
        assert "The agent cannot change the role" in body

    def test_the_reference_describes_it(self) -> None:
        cli = norm(section(text("reference/cli.md"), "carter ops config --emit", "###"))
        for needle in (
            "`author`, `committer`",
            "`coauthor_linked`",
            "**your** line",
            "E-HUMAN-IDENTITY",
        ):
            assert needle in cli, needle
        host = norm(section(text("reference/cli.md"), "carter check --host", "###"))
        for needle in ("role `author`", "E-HUMAN-IDENTITY", "DCO file"):
            assert needle in host, needle
        commit = norm(section(text("reference/cli.md"), "carter commit"))
        assert "The role is ignored here" in commit
        assert "role not applied (own terminal)" in commit


class TestTroubleshootingRows:
    def table(self) -> str:
        return norm(section(text("troubleshooting.md"), "Signing and the LLM identity"))

    def test_the_locked_key_row_has_the_raw_git_strings_and_the_one_fix(self) -> None:
        body = self.table()
        assert "Couldn't find key in agent?" in body and "Couldn't get agent socket" in body
        assert "fatal: failed to write commit object" in body
        assert "carter identity unlock" in body and "changes are still staged" in body

    def test_the_unsigned_badge_row_points_at_the_vigilant_table(self) -> None:
        assert "#the-vigilant-mode-table" in self.table()

    def test_the_fallback_row_says_nothing_was_asked(self) -> None:
        row = next(ln for ln in self.table().split("| ") if "E-SIGN-HUMAN-FALLBACK" in ln)
        assert "unlock question" not in row and "carter identity unlock" in self.table()


class TestNoDocTeachesAWrongKey:
    def test_the_removed_passphrase_flag_is_not_documented(self) -> None:
        for name, body in user_docs().items():
            assert "--allow-no-passphrase" not in body, name

    def test_signing_and_author_flags_are_only_named_to_forbid_them(self) -> None:
        forbid = re.compile(
            r"never|refus|not accept|forbid|fails|rejects?|stopped|cannot|ignores"
            r"|plain `git commit`",
            re.I,
        )
        signing_or_author = re.compile(
            r"--no-gpg-sign|-S<key>|--gpg-sign=<key>|--reset-author|--author\b"
        )
        for name, body in user_docs().items():
            for para in body.split("\n\n"):
                if signing_or_author.search(para):
                    assert forbid.search(para), (name, para[:100])

    def test_edit_automatically_only_appears_as_a_warning(self) -> None:
        for name, body in user_docs().items():
            for line in body.splitlines():
                if "Edit Automatically" in line:
                    assert (
                        re.search(r"never|would point", line, re.I)
                        or "Never" in (body.split(line)[0][-200:])
                    ), (name, line)

    def test_no_doc_says_the_user_signs_or_that_every_commit_is_signed(self) -> None:
        for name, body in user_docs().items():
            assert "git commit -S" not in body, name
            assert "signed with your key" not in body, name
