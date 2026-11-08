"""User docs describe what slice 1 actually shipped (plan 002 step 18).

They are checked against the code: documented CLI options equal ``--help``, the
documented ``--emit`` output has the real keys, the configuration example equals the
generated default, and the interim shape is stated plainly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from carter.cli import main
from carter.config import generate_default_config

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def text(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


def section(doc: str, heading: str) -> str:
    """The body of ``## heading`` up to the next ``## `` heading."""
    start = doc.index(f"\n## {heading}\n")
    rest = doc[start + 1 :]
    nxt = rest.find("\n## ", 5)
    return rest if nxt < 0 else rest[:nxt]


def help_options(*command: str) -> set[str]:
    out = CliRunner().invoke(main, [*command, "--help"]).output
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", out)) - {"--help"}


def documented_options(block: str) -> set[str]:
    return set(re.findall(r"`(?:-\w, )?(--[a-z][a-z0-9-]+)", block)) - {"--help"}


class TestCliReferenceMatchesHelp:
    def test_install_options(self) -> None:
        block = section(text("reference/cli.md"), "carter install")
        assert documented_options(block) == help_options("install")

    def test_update_synopsis_and_options(self) -> None:
        block = section(text("reference/cli.md"), "carter update")
        for opt in help_options("update"):
            assert opt in block, opt
        assert "identity" in block and "config.toml" in block and "asks nothing" in block

    def test_update_synopsis_line_matches_the_real_options(self) -> None:
        block = section(text("reference/cli.md"), "carter update")
        synopsis = re.search(r"```text\n(carter update[^\n]*)\n```", block)
        assert synopsis and "[-v]" in synopsis.group(1) and "[--dry-run]" in synopsis.group(1)

    def test_ops_config_emit_lists_the_real_keys(self) -> None:
        block = section(text("reference/cli.md"), "carter ops")
        for key in ("tier", "role", "role_source", "coauthor_trailer", "commits", "refusal_reason"):
            assert f"`{key}`" in block, key
        for removed in ("bot name and email", "bot_email", "bot_name"):
            assert removed not in block


class TestEmitExampleIsReal:
    def test_documented_json_has_exactly_the_emitted_keys(self) -> None:
        doc = text("guides/write-operations.md")
        blocks = re.findall(r"```json\n(.*?)```", doc, flags=re.S)
        emit = next(json.loads(b) for b in blocks if "coauthor_trailer" in b)
        assert set(emit) == {
            "tier",
            "role",
            "role_source",
            "coauthor_trailer",
            "commits",
            "refusal_reason",
            "footer",
            "has_github_token",
        }
        assert emit["tier"] == "t0" and emit["coauthor_trailer"] == "Assisted-by: Carter"


class TestConfigurationReference:
    def test_full_example_is_the_generated_default(self) -> None:
        doc = text("reference/configuration.md")
        example = yaml.safe_load(re.search(r"```yaml\n(.*?)```", doc, flags=re.S).group(1))
        assert example == generate_default_config(workspace_name="my-project")

    def test_identity_section_documents_policy_only(self) -> None:
        block = section(text("reference/configuration.md"), "Keys")
        identity = block[block.index("### identity") :].split("\n### ", 2)[0]
        for needle in ("`role`", "`require_tier`", "`co-author`", "`author`", "`t0`", "`t2`"):
            assert needle in identity, needle
        assert "carter update" in identity and "~/.carter/config.toml" in identity
        assert "git_account" not in identity and "bot_name" not in identity  # D70: unknown keys
        assert "deprecated" not in identity.lower()

    def test_user_config_schema_2_is_documented(self) -> None:
        doc = text("reference/configuration.md")
        assert "schema = 2" in doc
        assert '[workspaces."/abs/path"]' in doc or '[workspaces."' in doc
        for key in ("max_tier", "role", "require_tier"):
            assert f"`{key}`" in doc
        assert "config.toml.schema1.bak" not in doc and "unknown key" in doc  # D70: no migration


class TestInstallAndFiles:
    def test_files_and_paths_cover_the_new_files(self) -> None:
        doc = text("reference/files-and-paths.md")
        assert "config.toml.schema1.bak" not in doc and "upgrade-notes" not in doc  # D70
        assert "Never overwritten" not in next(
            ln for ln in doc.splitlines() if ln.startswith("| `~/.carter/config.toml`")
        )

    def test_install_guide_names_unknown_keys_and_the_human_key(self) -> None:
        doc = " ".join(text("guides/install.md").split())
        assert "not migrated" in doc and "→ delete it" in doc
        assert "schema1.bak" not in doc and "upgrade-notes" not in doc
        assert "never uses your signing key" in doc.lower() or "never reads your signing key" in doc


class TestInterimShapeIsStatedPlainly:
    def test_write_operations_says_commits_use_your_git_config_and_are_unsigned(self) -> None:
        doc = " ".join(section(text("guides/write-operations.md"), "Attribution").split())
        assert "your own git config" in doc or "your `git config`" in doc
        assert "unsigned" in doc
        assert "carter ops config --emit" in doc
        assert "`-S`" in doc and "`--author`" in doc

    def test_every_identity_command_the_docs_name_exists(self) -> None:
        """Was "no doc promises signing" in the interim releases; with slice 2b the docs describe
        it, so the rule is that they name only commands that exist (plan 005 step 28)."""
        real = {"add", "show", "verify", "unlock", "lock", "remove"}
        for path in DOCS.rglob("*.md"):
            if any(part in {"adr", "rfcs"} for part in path.parts):
                continue
            named = set(re.findall(r"carter identity (\w[\w-]*)", path.read_text(encoding="utf-8")))
            assert named <= real | {"env"}, (path, named - real)

    def test_attribution_text_mentions_the_three_tiers(self) -> None:
        doc = section(text("guides/write-operations.md"), "Attribution")
        for needle in ("Assisted-by: Carter", "Co-authored-by", "T0", "T1"):
            assert needle in doc, needle


class TestNoStaleIdentityText:
    PARAGRAPH_OK = re.compile(
        r"dropped|no longer|migrat|legacy|old |removed|deprecated|ignored", re.I
    )

    @pytest.mark.parametrize("needle", ["carter-bot@users.noreply", "signing_key"])
    def test_only_migration_context_mentions_removed_things(self, needle: str) -> None:
        offenders = []
        for path in DOCS.rglob("*.md"):
            if any(part in {"adr", "rfcs"} for part in path.parts):
                continue
            for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
                if needle in para and not self.PARAGRAPH_OK.search(para):
                    offenders.append((str(path.relative_to(REPO)), para.strip()[:80]))
        assert offenders == []

    def test_no_doc_says_the_user_signs_or_that_commits_are_signed(self) -> None:
        for path in [*DOCS.rglob("*.md"), REPO / "README.md"]:
            if any(part in {"adr", "rfcs"} for part in path.parts):
                continue
            body = path.read_text(encoding="utf-8")
            assert "git commit -S" not in body, path
            assert "signed with your key" not in body, path
