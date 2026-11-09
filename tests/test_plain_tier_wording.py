"""Nobody has to decode `T0`, `T1` or `T2`.

What a user or an agent reads says what the setup does, in the same three phrases everywhere:

- no LLM identity (config value `t0`),
- LLM identity, unsigned (config value `t1`),
- LLM signing on (config value `t2`): agent commits are signed.

The config values (`max_tier = "t1"`, `require_tier`, the `tier` field of `carter ops config
--emit`) are unchanged, because existing files use them; the configuration reference explains each
in one plain line. Code identifiers and comments may keep the short names.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.identity.errors import registry
from carter.identity.schema import TIER_WORDS, tier_words

REPO = Path(__file__).resolve().parent.parent
CODE = re.compile(r"\bT[012]\b")


def tracked(*patterns: str) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        found |= {p for p in REPO.glob(pattern) if p.is_file()}
    return sorted(found)


def docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


class TestTheWords:
    def test_the_three_phrases(self) -> None:
        assert TIER_WORDS == {
            "t0": "no LLM identity",
            "t1": "LLM identity, unsigned",
            "t2": "LLM signing on",
        }
        assert tier_words("t2") == "LLM signing on"
        assert tier_words("") == "no LLM identity"

    def test_the_configuration_reference_explains_each_value_in_one_plain_line(self) -> None:
        doc = (REPO / "docs/reference/configuration.md").read_text(encoding="utf-8")
        for value, words in TIER_WORDS.items():
            assert re.search(rf"^\| `{value}` \| .*{re.escape(words)}", doc, re.M), value


class TestNothingShowsACode:
    def test_error_texts(self) -> None:
        raw = (REPO / "carter/identity/errors.json").read_text(encoding="utf-8")
        assert CODE.findall(json.dumps(json.loads(raw))) == []
        assert all(
            not CODE.search(e.message + e.remediation + e.where) for e in registry().values()
        )

    def test_every_help_text(self) -> None:
        def walk(cmd: click.Command, path: tuple[str, ...]) -> list[tuple[str, ...]]:
            found = [path]
            if isinstance(cmd, click.Group):
                for name, sub in cmd.commands.items():
                    found += walk(sub, (*path, name))
            return found

        for path in walk(main, ()):
            out = CliRunner().invoke(main, [*path, "--help"]).output
            assert CODE.findall(out) == [], path

    @pytest.mark.parametrize(
        "path",
        tracked("docs/*.md", "docs/guides/*.md", "docs/reference/*.md", "docs/contributing/*.md")
        + [REPO / "README.md"],
        ids=lambda p: str(p.relative_to(REPO)),
    )
    def test_user_docs(self, path: Path) -> None:
        assert CODE.findall(path.read_text(encoding="utf-8")) == []

    @pytest.mark.parametrize(
        "path",
        tracked("skills/**/*.md", "templates/**/*.j2", "mcp/**/*.json"),
        ids=lambda p: str(p.relative_to(REPO)),
    )
    def test_what_agents_read(self, path: Path) -> None:
        assert CODE.findall(path.read_text(encoding="utf-8")) == []

    def test_the_global_agents_rule(self) -> None:
        from carter.install import components

        assert CODE.findall(components._OPENCODE_AGENTS_MD) == []

    @pytest.mark.parametrize(
        "path", tracked("carter/**/*.py"), ids=lambda p: str(p.relative_to(REPO))
    )
    def test_strings_printed_by_the_python_code(self, path: Path) -> None:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = docstring_nodes(tree)
        bad = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and CODE.search(node.value)
        ]
        assert bad == []

    @pytest.mark.parametrize(
        "path",
        tracked("carter/plugin/*.ts", "carter/guard/templates/*"),
        ids=lambda p: str(p.relative_to(REPO)),
    )
    def test_strings_printed_by_the_plugin_and_the_guard_script(self, path: Path) -> None:
        bad = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if CODE.search(line) and not line.lstrip().startswith(("//", "#", "*", "/*"))
        ]
        assert bad == []


def test_the_pattern_finds_the_codes_and_only_the_codes() -> None:
    assert CODE.search("at T2 the LLM signs") and CODE.search("tiers T0 and T1")
    assert not CODE.search('max_tier = "t1"') and not CODE.search("HT2 and T2x")
