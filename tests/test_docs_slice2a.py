"""User docs for slice 2a (plan 004 step 35): the plugin, the gate, the probe and the limits.

Same method as ``test_docs_slice1g.py``: documented options equal ``--help``, the consent
explanation equals the facts the installer prints, the error codes in the troubleshooting table
are the registered ones, and the honest residuals are stated. No doc links into the local-only
ADR and RFC folders, recommends ``export GITHUB_TOKEN``, ``--no-verify`` or a typed ``!git push``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from carter.identity.errors import registry
from carter.identity.policyset import consent_groups
from test_docs_slice1g import documented, help_options, section, text

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
USER_DOCS = [
    p for p in sorted(DOCS.rglob("*.md")) if not {"adr", "rfcs"} & set(p.relative_to(DOCS).parts)
]
TROUBLESHOOTING_CODES = (
    "E-ISOLATION-MISSING", "E-GATE", "E-GATE-FAIL", "E-PUSH-GUARD", "E-GIT-OLD",
    "E-OPENCODE-VERSION", "E-SELFTEST",
)  # fmt: skip


def norm(s: str) -> str:
    return " ".join(s.split())


class TestCliReference:
    def test_guard_install_documents_only_g2_for_the_plugin(self) -> None:
        block = section(text("reference/cli.md"), "carter guard install", "###")
        assert documented(block) == help_options("guard", "install")
        assert "--yes --only g2" in block and "`plugin` is not accepted here" in block

    def test_guard_remove_documents_only_plugin(self) -> None:
        block = section(text("reference/cli.md"), "carter guard remove", "###")
        assert documented(block) == help_options("guard", "remove")
        assert (
            "--only GROUPS|plugin" in block
            and "rm -r ~/.config/opencode/plugins/carter" in text("reference/cli.md")
        )

    def test_check_probe_and_gate_check_options_equal_help(self) -> None:
        cli = text("reference/cli.md")
        check = section(cli, "carter check", "##").split("### carter check --host")[0]
        assert "--probe" in help_options("check") and "--probe" in check
        probe = section(cli, "carter check --probe", "###")
        for name in (
            "ssh_agent_absent",
            "ssh_denied",
            "gh_pat_only",
            "push_refused",
            "agent_tagged",
        ):
            assert name in probe, name
        gate = section(cli, "carter gate check", "###")
        assert documented(gate) == help_options("gate", "check")
        assert "Exit 0 means allowed, 1 means refused" in gate


class TestNothingRecommendsTheForbidden:
    @pytest.mark.parametrize("doc", USER_DOCS, ids=lambda p: str(p.relative_to(DOCS)))
    def test_no_export_token_no_no_verify_no_bang_push_as_a_substitute(self, doc: Path) -> None:
        body = doc.read_text(encoding="utf-8")
        assert not re.search(r"^\s*export\s+(GH|GITHUB)_TOKEN", body, flags=re.M), doc.name
        for line in body.splitlines():
            if "--no-verify" in line:
                assert any(w in line.lower() for w in ("skip", "never", "not ", "forbidden")), line
        assert "!carter push" not in body and "! carter push" not in body
        assert "equivalent of `carter push`" not in body

    @pytest.mark.parametrize("doc", USER_DOCS, ids=lambda p: str(p.relative_to(DOCS)))
    def test_no_link_into_the_local_only_adr_and_rfc_folders(self, doc: Path) -> None:
        for target in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            assert "adr/" not in target and "rfcs/" not in target, (doc.name, target)

    def test_the_plugin_is_not_called_not_installed_slice_2a(self) -> None:
        for doc in USER_DOCS:
            assert "not installed (slice 2a)" not in doc.read_text(encoding="utf-8"), doc.name


class TestConsentExplanation:
    def facts(self) -> list[str]:
        g2 = next(g for g in consent_groups() if g.id == "g2")
        return [norm(line) for line in g2.explain]

    def test_the_install_guide_states_what_the_installer_prints(self) -> None:
        guide = norm(section(text("guides/install.md"), "Guards"))
        assert "never upgraded silently" in guide
        assert "plugin and isolation need your confirmation" in guide
        assert "`carter guard install --yes --only g2`" in guide
        for fact in (
            "no SSH agent",
            "the `!` shell",  # what stays untouched: your terminal and the `!` shell
            "carter guard remove --only plugin",
            "Restart the OpenCode server",
        ):
            assert fact.lower() in guide.lower(), fact
        # the installer's own text agrees on the same facts
        installer = " ".join(self.facts())
        for fact in ("no SSH agent", "does NOT change", "carter guard remove --only plugin"):
            assert fact in installer, fact

    def test_restart_from_a_clean_terminal_and_the_dotfiles_line(self) -> None:
        guide = norm(section(text("guides/install.md"), "Guards"))
        assert "Restart the OpenCode server from a clean terminal" in guide
        assert "git config --global --add include.path" in guide and "dotfiles" in guide

    def test_the_before_after_table_names_the_ssh_consequence(self) -> None:
        guide = norm(section(text("guides/install.md"), "Guards"))
        assert "| SSH agent |" in guide
        assert "works for public repositories and for repositories that token covers only" in guide
        assert "**unsigned**" in guide

    def test_the_group_list_equals_the_data_file(self) -> None:
        guards = section(text("guides/install.md"), "Guards")
        listed = set(re.findall(r"^\| `([a-z0-9_-]+)` \|", guards, flags=re.M))
        assert listed == {g.id for g in consent_groups() if g.live}


class TestTroubleshootingCodes:
    def table(self) -> str:
        return text("troubleshooting.md")

    def test_every_code_in_the_table_is_registered(self) -> None:
        codes = set(re.findall(r"`(E-[A-Z0-9-]+)`", self.table()))
        assert codes <= set(registry()), codes - set(registry())

    def test_every_2a_user_code_has_a_row(self) -> None:
        body = self.table()
        for code in TROUBLESHOOTING_CODES:
            assert f"`{code}`" in body, code

    def test_the_new_symptoms_are_there(self) -> None:
        body = self.table()
        for symptom in (
            "My agent cannot fetch over SSH",
            "My agent cannot run `python -c`",
            "Every git command fails",
            "after an OpenCode update",
            "inactive",
        ):
            assert symptom in body, symptom

    def test_the_malformed_gitconfig_recovery_is_exact(self) -> None:
        body = norm(self.table())
        assert "rm ~/.carter/gitconfig" in body and "git works again at once" in body


class TestFilesAndPaths:
    def test_the_2a_files_are_listed(self) -> None:
        doc = text("reference/files-and-paths.md")
        for path in (
            "~/.config/opencode/plugins/carter/index.ts",
            "~/.carter/isolation.json",
            "~/.carter/run/",
            "run/gh-empty/",
            "run/plugin-status/<pid>.json",
            "~/.carter/hooks/carter-guard",
            "~/.carter/gitconfig",
            "<repo>/.git/hooks/pre-push",
        ):
            assert path in doc, path
        assert "Not written in this release" not in doc


class TestTheResidualsAreHonest:
    def doc(self) -> str:
        return norm(section(text("guides/safety-and-permissions.md"), "What the guards cannot do"))

    def test_the_named_residuals(self) -> None:
        doc = self.doc()
        for needle in (
            "Same-user evasion",
            "`git push --no-verify` skips the `pre-push` hook",
            "(the accepted D67 residual)",
            "`.git/hooks/` and `.git/config`",
            "The read-only token is visible to the model",
            "unsigned until signing ships",
            '`max_tier = "t1"`',
            "Fail closed",
        ):
            assert needle in doc, needle

    def test_write_operations_has_the_t2_note_and_the_live_host_impact(self) -> None:
        wo = norm(
            section(text("guides/write-operations.md"), "What this release does and does not do")
        )
        assert "blocked** until agent signing ships" in wo and '`max_tier = "t1"`' in wo
        assert "speed bump" in wo and "unsigned" in wo
        guide = norm(text("guides/install.md"))
        assert "None. `git fetch`/`pull`/`clone` go over HTTPS" in guide

    def test_the_mcp_guide_still_says_the_token_is_read_from_a_file(self) -> None:
        mcp = norm(text("guides/mcp-servers.md"))
        assert "{file:~/.carter/secrets/gh-read.token}" in mcp
