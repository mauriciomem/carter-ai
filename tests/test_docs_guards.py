"""The install guide, the safety page and the guard rules in the docs match the guards.

The consent groups listed equal ``g2_rules.json``; what the installer prints and what the guide
says agree; the limits are stated plainly; and no doc recommends a way around a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from carter.identity.policyset import consent_groups
from docs_support import DOCS, norm, section, text, user_docs

PUBLIC_DOCS = [p for p in sorted(DOCS.rglob("*.md")) if not {"adr", "rfcs"} & set(p.parts)]


def guards() -> str:
    return norm(section(text("guides/install.md"), "Guards"))


class TestInstallGuide:
    def test_the_groups_listed_are_the_groups_in_the_data_file(self) -> None:
        body = section(text("guides/install.md"), "Guards")
        listed = set(re.findall(r"^\| `([a-z0-9_-]+)` \|", body, flags=re.M))
        assert listed == {g.id for g in consent_groups()}

    def test_there_is_one_question_and_an_upgrade_is_asked_in_it(self) -> None:
        body = guards()
        assert "asks **one** question, `Install? [Y/n]`" in body
        assert "asked again in this same question, never separately" in body

    def test_it_explains_yes_no_terminal_dry_run_remove_and_restart(self) -> None:
        body = guards()
        for needle in (
            "carter install --yes",
            "skipped with a notice",
            "carter guard install --dry-run",
            "carter guard remove",
            "Restart the OpenCode server from a clean terminal",
            "carter uninstall --keep-guards",
            "A group you decline stays declined",
            "restores the backup",
        ):
            assert needle in body, needle

    def test_it_says_where_the_rules_apply(self) -> None:
        body = guards()
        assert "only Carter agents and Carter workspaces" in body
        assert "Carter writes no global OpenCode policies" in body

    def test_the_plugin_table_names_the_consequences(self) -> None:
        body = guards()
        assert "| SSH agent |" in body and "**unsigned**" in body
        assert "Your terminal and OpenCode's `!` shell | Untouched" in body
        assert "fail closed" in body.lower()

    def test_the_dotfiles_line_is_exact(self) -> None:
        body = guards()
        assert "git config --global --add include.path" in body and "dotfiles" in body

    def test_the_undo_commands_are_there(self) -> None:
        body = guards()
        for needle in (
            "carter guard remove --only plugin",
            "carter guard remove --only broker",
            "rm -r ~/.config/opencode/plugins/carter",
            "rm ~/.carter/gitconfig",
        ):
            assert needle in body, needle


class TestGuideAgreesWithTheInstaller:
    def explained(self, group: str) -> str:
        return norm(" ".join(next(g for g in consent_groups() if g.id == group).explain))

    def test_g2_facts(self) -> None:
        guide, installer = guards().lower(), self.explained("g2")
        for fact in ("no SSH agent", "does NOT change", "carter guard remove --only plugin"):
            assert fact in installer, fact
        assert "no ssh agent" in guide or "| ssh agent | none" in guide
        assert "carter guard remove --only plugin" in guide

    def test_the_hooks_row_names_the_events_the_installer_does(self) -> None:
        row = norm(
            next(ln for ln in text("guides/install.md").splitlines() if ln.startswith("| `hooks`"))
        )
        explained = self.explained("hooks")
        for event in ("pre-push", "prepare-commit-msg", "commit-msg", "post-commit"):
            assert event in row and event in explained, event


class TestWhatTheGuardsCannotDo:
    def doc(self) -> str:
        return norm(section(text("guides/safety-and-permissions.md"), "What the guards cannot do"))

    def test_the_named_limits(self) -> None:
        body = self.doc()
        for needle in (
            "Same-user evasion",
            "Outside Carter there are no guards",
            "`carter_push` can be forged by a same-user agent",
            "`git push --no-verify` skips the `pre-push` hook",
            "`.git/hooks/` and `.git/config`",
            "The read-only token is visible to the model",
            "Agent commits are unsigned unless LLM signing is on",
            '`max_tier = "t1"`',
            "Fail closed",
        ):
            assert needle in body, needle

    def test_the_gate_is_called_a_speed_bump_not_a_sandbox(self) -> None:
        assert "speed bump" in self.doc() and "not a sandbox" in self.doc()

    def test_the_safety_page_and_the_readme_say_who_pushes(self) -> None:
        safety = norm(text("guides/safety-and-permissions.md"))
        assert "**Nobody pushes or merges.**" in safety and "DevOps included" in safety
        readme = norm(user_docs()["README.md"])
        assert "No agent pushes: you do, with `carter push`" in readme


class TestNothingTeachesABypass:
    @pytest.mark.parametrize("doc", PUBLIC_DOCS, ids=lambda p: str(p.relative_to(DOCS)))
    def test_no_export_token_no_bare_no_verify_no_pasted_bang(self, doc: Path) -> None:
        body = doc.read_text(encoding="utf-8")
        assert not re.search(r"^\s*export\s+(GH|GITHUB)_TOKEN", body, flags=re.M), doc.name
        for line in body.splitlines():
            if "--no-verify" in line:
                assert any(w in line.lower() for w in ("skip", "never", "not ", "forbidden")), line
            if "!carter push" in line:
                assert any(w in line.lower() for w in ("opencode", "plugin", "tagged", "you")), line
            if re.search(r"paste", line, re.I) and "`!" in line:
                assert re.search(r"never|not|instead", line, re.I), line

    @pytest.mark.parametrize("doc", PUBLIC_DOCS, ids=lambda p: str(p.relative_to(DOCS)))
    def test_no_link_into_the_local_only_folders(self, doc: Path) -> None:
        for target in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            assert "adr/" not in target and "rfcs/" not in target, (doc.name, target)

    def test_no_doc_describes_devops_pushing(self) -> None:
        patterns = (
            r"only (?:the )?devops (?:agent )?(?:can|may|is allowed to) (?:push|run)",
            r"only devops can push",
            r"the only agent that pushes",
            r"handed to devops",
            r"hand(?:s|ed)? (?:the )?(?:push )?(?:over )?to devops",
            r"devops (?:then )?(?:pushes|runs `?git push)",
        )
        for name, body in user_docs().items():
            flat = norm(body).lower()
            assert [p for p in patterns if re.search(p, flat)] == [], name

    def test_no_doc_names_a_command_that_is_gone(self) -> None:
        for name, body in user_docs().items():
            assert "carter pr" not in body.replace("carter pr-", ""), name
            assert "handoff file" not in body.lower(), name
