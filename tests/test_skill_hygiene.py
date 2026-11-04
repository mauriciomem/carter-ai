"""Skill sources carry only what OpenCode V2 reads."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS = sorted((Path(__file__).resolve().parents[1] / "skills").glob("*/SKILL.md"))


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_frontmatter_has_no_argument_hint(skill: Path) -> None:
    # OpenCode V2 reads name/description/metadata only (opencode.ai/v2/docs/skills).
    frontmatter = skill.read_text().split("\n---", 1)[0]
    assert "argument-hint" not in frontmatter


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_no_platform_memory_or_harness_date(skill: Path) -> None:
    text = skill.read_text()
    assert " /memories/" not in text and "`/memories/`" not in text
    assert "harness date variable" not in text


# ─── Record templates carry ``ai-usage`` (RFC-0007 §4.2), plans do not carry push_policy ──

REPO = Path(__file__).resolve().parents[1]
AI_USAGE_LINE = "ai-usage: ai-assisted"


def _first_markdown_example(skill_name: str) -> str:
    """The first ```markdown fence of a skill: its record (frontmatter) template."""
    text = (REPO / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
    marker = "```markdown"
    start = text.index(marker) + len(marker)
    return text[start : text.index("```", start)].lstrip("\n")


def _frontmatter_of(example: str) -> str:
    assert example.startswith("---\n"), "template must open with a frontmatter block"
    return example.split("\n---", 1)[0]


class TestPlanSkillTemplate:
    def test_example_does_not_emit_push_policy(self) -> None:
        assert "push_policy" not in _frontmatter_of(_first_markdown_example("carter-plan"))

    def test_example_emits_ai_usage(self) -> None:
        assert AI_USAGE_LINE in _frontmatter_of(_first_markdown_example("carter-plan"))

    def test_example_documents_the_optional_enum(self) -> None:
        line = next(
            ln
            for ln in _frontmatter_of(_first_markdown_example("carter-plan")).splitlines()
            if ln.startswith("ai-usage:")
        )
        assert "ai-assisted | ai-generated | human-only" in line
        assert "optional" in line

    def test_skill_text_never_tells_the_pm_to_write_push_policy(self) -> None:
        text = (REPO / "skills" / "carter-plan" / "SKILL.md").read_text(encoding="utf-8")
        assert "push_policy" not in text


@pytest.mark.parametrize("skill_name", ["carter-adr", "carter-rfc", "carter-research"])
def test_record_template_carries_ai_usage(skill_name: str) -> None:
    assert AI_USAGE_LINE in _frontmatter_of(_first_markdown_example(skill_name))


def test_repo_docs_carry_no_front_matter() -> None:
    """RFC-0007 §4.2: repo docs (non-record) get no front matter."""
    docs = [REPO / "README.md", *sorted((REPO / "docs").rglob("*.md"))]
    local_only = (REPO / "docs" / "adr", REPO / "docs" / "rfcs")
    offenders = [
        str(p.relative_to(REPO))
        for p in docs
        if not any(d in p.parents for d in local_only)
        and p.read_text(encoding="utf-8").lstrip("\ufeff").startswith("---")
    ]
    assert offenders == []


# ─── carter-ops: the agent commit recipe (plan 002 step 15) ───

OPS_SKILL = REPO / "skills" / "carter-ops" / "SKILL.md"


def _ops_text() -> str:
    return OPS_SKILL.read_text(encoding="utf-8")


def _code_fences(text: str) -> list[str]:
    return re.findall(r"```[a-z]*\n(.*?)```", text, flags=re.S)


class TestCarterOpsRecipe:
    def test_no_identity_placeholders_are_left_in_any_skill_or_template(self) -> None:
        offenders = [
            str(p.relative_to(REPO))
            for root in ("skills", "templates")
            for p in (REPO / root).rglob("*")
            if p.is_file() and re.search(r"\{\{(BOT_|SIGNING_KEY)", p.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_recipe_never_signs(self) -> None:
        for fence in _code_fences(_ops_text()):
            assert not re.search(r"git commit\b[^\n]*(?:\s-S|--gpg-sign|\s-s\b|--signoff)", fence)
            assert "-S" not in fence.replace("-Sx", "")

    def test_recipe_never_uses_the_forbidden_literals(self) -> None:
        from carter.identity.rules import render_forbidden_commands

        offenders = [
            (lit, fence.strip().splitlines()[0])
            for fence in _code_fences(_ops_text())
            for lit in render_forbidden_commands()
            if lit in fence
        ]
        assert offenders == []

    def test_recipe_stages_explicit_paths_only(self) -> None:
        fences = "\n".join(_code_fences(_ops_text()))
        assert "git add <file1> <file2>" in fences
        assert not re.search(r"git add (-A|--all|\.)(\s|$)", fences)
        assert not re.search(r"git commit\b[^\n]*\s-[a-z]*a[a-z]*\b", fences)

    def test_recipe_verifies_the_commit_shape(self) -> None:
        text = _ops_text()
        assert "git log -1 --format='%an|%cn|%G?'" in text
        assert "git config user.name" in text
        assert "`N`" in text  # unsigned is the expected status in this release

    def test_trailer_comes_from_the_runtime_emit_not_from_the_file(self) -> None:
        text = _ops_text()
        assert "carter ops config --emit" in text
        for key in ("coauthor_trailer", "tier", "commits", "refusal_reason", "footer"):
            assert f"`{key}`" in text, key
        assert '--trailer "<coauthor_trailer>"' in text
        assert not re.search(r"Co-authored-by: [A-Za-z0-9-]+ <[^<>\s]+@", text)  # no literal

    def test_refused_means_stop_and_report(self) -> None:
        text = _ops_text()
        assert re.search(r"`commits` is `refused`[^.]*stop", text, re.I)
        assert "report" in text.lower() and "`refusal_reason`" in text

    def test_interim_shape_is_stated(self) -> None:
        text = " ".join(_ops_text().split())
        assert "user's own git config" in text
        assert "unsigned" in text
        for flag in ("--author", "--no-verify", "-s", "-S"):
            assert f"`{flag}`" in text

    def test_footer_is_the_emitted_one(self) -> None:
        text = _ops_text()
        assert "{{" not in text
        assert "generated by" not in text.lower().replace("generated from", "")

    def test_rendered_blocks_are_present(self) -> None:
        from carter.identity.blocks import check_text

        assert check_text(_ops_text()) == []

    def test_error_recovery_has_no_signing_retry(self) -> None:
        assert "proceed without signing" not in _ops_text()


# ─── carter-ops: Push and PR is a handoff (plan 003 step 22) ───


def _section(tag: str) -> str:
    text = _ops_text()
    start, end = text.index(f"<{tag}>"), text.index(f"</{tag}>")
    return text[start:end]


class TestCarterOpsPushAndPr:
    def test_the_section_exists_and_names_the_handoff_path(self) -> None:
        section = _section("push-and-pr")
        assert "## Push and PR" in section
        assert ".carter/state/handoff/<encoded-branch>.md" in section
        assert "`%` written as `%25` and `/` as `%2F`" in section

    def test_the_example_front_matter_round_trips_through_the_parser(self) -> None:
        from carter.aplus.handoff import KEYS, parse_handoff

        (example,) = [f for f in _code_fences(_section("push-and-pr")) if f.startswith("---")]
        filled = example.replace("<40 lowercase hex characters: git rev-parse HEAD>", "a" * 40)
        filled = filled.replace("<owner/name>", "owner/name")
        model, _ = parse_handoff(filled)
        assert model.base == "main" and model.draft is False and model.repo == "owner/name"
        keys = [ln.split(":", 1)[0] for ln in example.split("---")[1].strip().splitlines()]
        assert tuple(keys) == KEYS  # exactly what the parser accepts, in its order

    def test_the_own_terminal_sentence_is_the_shared_constant(self) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        assert OWN_TERMINAL in _section("push-and-pr")
        assert _section("push-and-pr").count("in your own terminal") == 1

    def test_no_command_is_shown_with_a_leading_bang_or_a_force_flag(self) -> None:
        for fence in _code_fences(_ops_text()):
            for line in fence.splitlines():
                assert not line.lstrip().startswith("!"), line
                assert "--force" not in line and "--force-with-lease" not in line, line
        section = " ".join(_section("push-and-pr").split())
        assert "never prefix the commands with `!`" in section
        assert "never pass `--force`" in section

    def test_no_code_fence_pushes_or_writes_to_github(self) -> None:
        fences = "\n".join(_code_fences(_ops_text()))
        writes = (
            "git push", "gh pr create", "gh pr merge", "gh issue create", "gh issue comment",
            "gh pr comment", "gh release", "gh api",
        )  # fmt: skip
        for write in writes:
            assert write not in fences, write

    def test_issue_comment_and_release_have_no_agent_path(self) -> None:
        section = " ".join(_section("push-and-pr").split())
        assert "no agent path in this version" in section and "post themselves" in section

    def test_the_old_devops_push_wording_is_gone(self) -> None:
        text = _ops_text()
        assert "push by carter-devops only" not in text
        assert "Push (carter-devops only)" not in text
        assert "GitHub Operations (via gh CLI" not in text
        assert "sole `remote-write` holder" not in text

    def test_jira_and_slack_writes_stay_with_devops(self) -> None:
        routing = " ".join(_section("routing").split())
        assert "Jira and Slack writes" in routing and "only by carter-devops" in routing
        assert "carter-narrator" in routing

    def test_the_guards_interim_paragraph_is_honest(self) -> None:
        text = " ".join(_ops_text().split())
        assert "literal command matches" in text
        assert "plugin and shell isolation" in text and "not installed yet" in text

    def test_the_error_table_carries_the_codes_an_agent_can_meet(self) -> None:
        text = _ops_text()
        for code in ("E-POLICY", "E-GH-READONLY", "E-HANDOFF", "E-SECRET-SCAN", "E-HUMAN-TERMINAL"):
            assert f"`{code}`" in text, code
        assert "`E-PUSH-GUARD`" in text  # the pre-push hook is slice 2a (plan 004 step 34)

    def test_the_forbidden_block_now_lists_the_push_and_human_only_verbs(self) -> None:
        text = _ops_text()
        assert "- **Push verbs:** `git push`, `git send-pack`." in text
        assert "`carter push`" in text and "`carter guard *`" in text


# ─── Attribution wording agrees everywhere (plan 002 step 17) ───

WORDING_FILES = [
    "skills/carter-pipeline/SKILL.md",
    "skills/carter-docs/SKILL.md",
    "templates/instructions/AGENTS.md.j2",
    "templates/agents/carter-engineer.md.j2",
    "templates/agents/carter-devops.md.j2",
    "templates/agents/carter-maestro.md.j2",
]
STALE_WORDING = (
    "signed `-S`",
    "sign with your own key",
    "bot identity from `~/.carter/config.toml`",
    "bot identity from",
    "carter-bot",
)


@pytest.mark.parametrize("name", WORDING_FILES)
def test_attribution_wording_points_to_carter_ops_and_the_emit(name: str) -> None:
    text = " ".join((REPO / name).read_text(encoding="utf-8").split())
    assert "carter-ops" in text, name
    assert "coauthor_trailer" in text, name
    assert "`--author`" in text, name
    for stale in STALE_WORDING:
        assert stale not in text, (name, stale)


def test_the_user_is_never_said_to_sign() -> None:
    for name in WORDING_FILES:
        text = (REPO / name).read_text(encoding="utf-8")
        assert not re.search(r"user is (?:the )?(?:commit )?author \(signed", text), name


class TestCarterOpsGhReads:
    """Spike 4: `gh repo view` and `gh search repos` take the repo positionally (no -R)."""

    def test_the_positional_verbs_and_the_dash_r_placement_are_stated(self) -> None:
        text = " ".join(_ops_text().split())
        assert "`gh repo view <owner>/<repo>`" in text and "`gh search repos <query>`" in text
        assert "have no `-R`" in text
        assert "put `-R <owner>/<repo>` **after** the subcommand" in text
        assert "`gh status` and `gh api` are denied" in text

    def test_no_fence_shows_dash_r_on_the_positional_verbs(self) -> None:
        for fence in _code_fences(_ops_text()):
            assert "gh repo view -R" not in fence and "gh search repos -R" not in fence


class TestOwnTerminalWordingHasOneHome:
    """Plan 003 step 23: the sentence that says *where* pushing happens lives in
    ``handoff.OWN_TERMINAL`` only; templates use the ``own_terminal`` global, skills and the
    AGENTS.md rule carry it verbatim, and no file words it differently."""

    SOURCES = (
        "templates",
        "skills",
        "carter/install/components.py",
        "carter/scaffold.py",
    )

    @staticmethod
    def _files():
        for name in TestOwnTerminalWordingHasOneHome.SOURCES:
            path = REPO / name
            yield from (sorted(path.rglob("*")) if path.is_dir() else [path])

    def test_the_constant_is_the_sentence(self) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        assert OWN_TERMINAL == (
            "Run `carter push` and then `carter pr` in your own terminal, not through an agent."
        )
        assert "!" not in OWN_TERMINAL  # spike 2: `!` has no TTY, so it is never suggested

    def test_no_file_words_the_instruction_differently(self) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        drift = []
        for path in self._files():
            if not path.is_file() or path.suffix not in {".md", ".j2", ".py", ".yaml"}:
                continue
            text = " ".join(path.read_text(encoding="utf-8").split())
            for match in re.finditer(r"[^.\n]*\bin your own terminal\b[^.\n]*", text):
                sentence = match.group(0)
                if "carter push" in sentence and OWN_TERMINAL.removesuffix(".") not in sentence:
                    drift.append((str(path.relative_to(REPO)), sentence.strip()))
        assert drift == []

    def test_templates_use_the_global_not_a_copy(self) -> None:
        for path in (REPO / "templates").rglob("*.j2"):
            text = path.read_text(encoding="utf-8")
            assert "not through an agent" not in text, path.name

    def test_the_skill_and_the_rule_carry_it_verbatim(self) -> None:
        from carter.aplus.handoff import OWN_TERMINAL
        from carter.install.components import _ATTRIBUTION_RULE

        skill = " ".join((REPO / "skills/carter-ops/SKILL.md").read_text().split())
        pipeline = " ".join((REPO / "skills/carter-pipeline/SKILL.md").read_text().split())
        assert (
            OWN_TERMINAL in skill and OWN_TERMINAL in pipeline and OWN_TERMINAL in _ATTRIBUTION_RULE
        )

    def test_nothing_agent_facing_suggests_a_bang_shell(self) -> None:
        for path in self._files():
            if path.is_file() and path.suffix in {".md", ".j2"}:
                text = path.read_text(encoding="utf-8")
                assert "!carter push" not in text and "! carter push" not in text, path.name
                assert "!carter pr" not in text and "!git push" not in text, path.name


# ─── Plan 004 step 34: what the agent meets once the gate and isolation are live ───


class TestCarterOpsGate:
    def gate(self) -> str:
        text = _ops_text()
        start = text.index("## When the gate or the isolation answers")
        return " ".join(text[start : text.index("</guardrails>")].split())

    def test_a_rejection_is_handed_off_not_rephrased(self) -> None:
        gate = self.gate()
        assert "A rejection names a rule" in gate and "Do not rephrase the command" in gate
        assert "hand off" in gate and "Never write a script to get around a rejection" in gate

    def test_pushes_and_prs_stay_human_only_with_the_shared_sentence(self) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        assert "Pushes and PRs stay human-only" in self.gate()
        assert "`carter push` and `carter pr` in their own terminal" in self.gate()
        assert OWN_TERMINAL in " ".join(_ops_text().split())

    def test_the_practical_rules_are_stated(self) -> None:
        gate = self.gate()
        assert "Put `-R <owner>/<repo>` after the `gh` subcommand" in gate
        assert "Stage explicit paths" in gate and "`git add -A`" in gate
        assert "no SSH in your shell" in gate and "HTTPS with a read-only token" in gate
        assert "unsigned at this tier" in gate
        for code in ("E-ISOLATION-MISSING", "E-GATE-FAIL"):
            assert f"`{code}`" in gate
        assert "ask the user to run `carter check --host`" in gate
        assert "`carter check --probe`" in gate and "only when the user asks" in gate

    def test_nothing_teaches_a_bypass(self) -> None:
        text = _ops_text()
        for teaching in ("instead try", "another way to push:", "bypass by", "you can still"):
            assert teaching not in text.replace("do not look for another way to push", ""), teaching
        # the prohibitions name no concrete evasion command
        gate = self.gate()
        for evasion in ("sh -c", "bash -c", "eval ", "python3 -c", "xargs"):
            assert evasion not in gate, evasion

    def test_the_interim_paragraph_has_both_wordings(self) -> None:
        text = " ".join(_ops_text().split())
        assert "Once the user has confirmed group `g2` at revision 2, the Carter plugin is" in text
        assert "literal command matches" in text and "not installed yet" in text

    def test_the_error_table_carries_the_2a_codes(self) -> None:
        text = _ops_text()
        for code in (
            "E-ISOLATION-MISSING", "E-GATE", "E-GATE-FAIL", "E-PUSH-GUARD", "E-GIT-OLD",
            "E-OPENCODE-VERSION", "E-SIGN-UNAVAILABLE",
        ):  # fmt: skip
            assert f"| `{code}` |" in text, code

    @pytest.mark.parametrize("name", ["engineer", "devops", "maestro"])
    def test_each_agent_template_has_the_rejection_line_and_no_retry_advice(
        self, name: str
    ) -> None:
        text = " ".join((REPO / f"templates/agents/carter-{name}.md.j2").read_text().split())
        assert "refused by the Carter command gate" in text
        assert "is not retried in another spelling or through a script" in text
        assert "retry with" not in text.lower().replace("do not retry with", "")
