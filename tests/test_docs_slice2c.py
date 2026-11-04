"""User docs for slice 2c, role b (plan 006 step 11): the guide covers the role, the docs equal the
code (``--help``, the registry, the cache name and TTL), nothing teaches a bypass."""

from __future__ import annotations

import re
from pathlib import Path

from carter.identity import coauthor
from carter.identity.errors import registry
from carter.identity.rules import human_identity_rules
from test_docs_slice1g import documented, help_options, section, text

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = "guides/identity-and-signing.md"
ROLE = "Role `author`: the LLM is the author"


def role_section() -> str:
    return " ".join(section(text(GUIDE), ROLE).split())


class TestGuide:
    def test_it_covers_what_the_plan_requires(self) -> None:
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
            ".github/dco.yml",
            "Squash-merging",
            "vigilant mode",
            "Partially verified",
            "carter commit` ignores the role",
            "carter guard install",
        ):
            assert needle in body, needle

    def test_the_codes_it_names_are_registered(self) -> None:
        for code in set(re.findall(r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+", role_section())):
            assert code in registry(), code

    def test_the_cache_name_and_lifetime_are_the_code_s(self) -> None:
        body = role_section()
        assert Path(coauthor.LINK_CACHE_REL).name in body
        assert f"{coauthor.LINK_CACHE_TTL_S // 86400} days" in body
        files = " ".join(text("reference/files-and-paths.md").split())
        assert coauthor.LINK_CACHE_REL.removeprefix(".carter/") in files

    def test_the_fallbacks_named_in_the_troubleshooting_row_are_the_rules_file_s(self) -> None:
        row = next(
            ln for ln in text("troubleshooting.md").splitlines() if "`E-HUMAN-IDENTITY`" in ln
        )
        rules = human_identity_rules()
        assert rules["fallback_pairs"][0][0] in row and rules["fallback_pairs"][0][1] in row
        assert "carter-bot@" in row and "carter-bot@" in " ".join(rules["fallback_emails"])

    def test_the_dco_files_it_lists_are_the_ones_check_host_looks_for(self) -> None:
        from carter.human_items import DCO_FILES

        body = role_section()
        for name in DCO_FILES:
            assert name in body, name

    def test_it_says_github_s_rendering_was_not_yet_seen_on_a_real_repository(self) -> None:
        assert "not yet on a real repository" in role_section()

    def test_no_link_into_the_local_only_folders(self) -> None:
        for target in re.findall(r"\]\(([^)]+)\)", text(GUIDE)):
            assert "/adr/" not in target and "/rfcs/" not in target, target


class TestReference:
    def test_add_documents_the_role_option_and_only_the_options_it_has(self) -> None:
        block = section(text("reference/cli.md"), "carter identity add", "###")
        assert documented(block) == help_options("identity", "add") and "--role" in documented(
            block
        )

    def test_the_emit_table_has_the_role_b_keys(self) -> None:
        block = " ".join(
            section(text("reference/cli.md"), "carter ops config --emit", "###").split()
        )
        for needle in (
            "`author`, `committer`",
            "`coauthor_linked`",
            "**your** line",
            "E-HUMAN-IDENTITY",
        ):
            assert needle in block, needle

    def test_commit_says_it_ignores_the_role(self) -> None:
        block = " ".join(section(text("reference/cli.md"), "carter commit", "##").split())
        assert "The role is ignored here" in block and "role not applied (own terminal)" in block

    def test_check_host_lists_the_role_b_items(self) -> None:
        block = " ".join(section(text("reference/cli.md"), "carter check --host", "###").split())
        for needle in ("role `author`", "E-HUMAN-IDENTITY", "DCO file", "older Carter"):
            assert needle in block, needle

    def test_every_code_in_the_troubleshooting_table_is_registered(self) -> None:
        for code in set(re.findall(r"`(E-[A-Z0-9]+(?:-[A-Z0-9]+)+)", text("troubleshooting.md"))):
            assert code in registry(), code


class TestNoBypassAdvice:
    def docs(self) -> list[tuple[str, str]]:
        root = REPO_ROOT / "docs"
        return [
            (str(p.relative_to(root)), p.read_text(encoding="utf-8"))
            for p in root.rglob("*.md")
            if not {"adr", "rfcs"} & set(p.parts)
        ]

    def test_author_flags_are_only_named_to_forbid_them(self) -> None:
        for name, body in self.docs():
            for para in body.split("\n\n"):
                if re.search(r"--reset-author|--author\b|GIT_AUTHOR", para):
                    assert re.search(
                        r"never|refus|stopped|forbid|rejects?|not accept|cannot|may not"
                        r"|ignores|keep|asks for|used\b",
                        para,
                        re.I,
                    ), (name, para[:100])

    def test_the_env_var_is_for_the_user_before_opencode_starts_and_the_agent_cannot_set_it(
        self,
    ) -> None:
        body = " ".join(text(GUIDE).split())
        assert "**before** OpenCode starts" in body
        assert "The agent cannot change the role" in body
