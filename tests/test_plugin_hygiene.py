"""Static hygiene of the TypeScript plugin sources (plan 004 step 9; RFC-0007 D7, D60).

The plugin holds the marker, the tagging, a read of the static ``isolation.json`` and the call
of the Python gate, and nothing else. Every list, flag and rule it applies comes from
``isolation.json``, which Python renders from ``g2_rules.json``. These tests keep it that way:

- erasable TypeScript only (no ``enum``, ``namespace``, parameter properties, decorators), so
  Node's type stripping and Bun load the same file as written;
- ``core.ts`` imports only ``node:*``; ``index.ts`` is the only file that may import the
  OpenCode plugin API, and it stays tiny;
- no word from the Python-only lists (git verbs, credential paths, isolation variable names)
  appears in TS code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from carter.identity.rules import load_rules

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "carter" / "plugin"
SOURCES = sorted(PLUGIN.glob("*.ts"))
INDEX_MAX_LINES = 80

# Names the TS must know because they ARE the protocol (tags and the git count mechanism).
PROTOCOL_NAMES = {
    "CARTER_AGENT_SHELL",
    "CARTER_HUMAN_SHELL",
    "GH_TOKEN",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_",
    "GIT_CONFIG_VALUE_",
}
# Words of the gate/forbidden lists that must never be hard-coded in TS.
FORBIDDEN_WORDS = (
    "git push",
    "send-pack",
    "commit-tree",
    "filter-branch",
    "update-ref",
    "systemd-run",
    "crontab",
    "sudo",
    "docker",
    "podman",
    "gh api",
    "security find-",
    "--no-verify",
    "gpgsign",
    "pushInsteadOf",
    "IdentityAgent",
)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|(?<=[\s;,)])//[^\n]*$", "", text)


def strip_strings(text: str) -> str:
    return re.sub(r"(['\"])(?:\\.|(?!\1).)*\1|`(?:\\.|[^`])*`", '""', text)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_core_ts_exists() -> None:
    assert (PLUGIN / "core.ts").is_file()


def test_there_is_no_npm_or_build_machinery() -> None:
    for name in ("package.json", "package-lock.json", "node_modules", "tsconfig.json", "bun.lock"):
        assert not (REPO / name).exists(), name
        assert not (PLUGIN / name).exists(), name


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
class TestErasableSyntax:
    def test_no_enum_namespace_or_module_blocks(self, source: Path) -> None:
        code = strip_strings(strip_comments(read(source)))
        assert not re.search(r"\b(?:const\s+)?enum\s+\w+", code)
        assert not re.search(r"\bnamespace\s+\w+", code)
        assert not re.search(r"\bdeclare\s+module\b|\bmodule\s+\w+\s*\{", code)

    def test_no_parameter_properties_decorators_or_legacy_exports(self, source: Path) -> None:
        code = strip_strings(strip_comments(read(source)))
        assert not re.search(
            r"\bconstructor\s*\([^)]*\b(?:public|private|protected|readonly)\s+\w", code
        )
        assert not re.search(r"(?m)^\s*@\w+", code)
        assert not re.search(r"\bimport\s+\w+\s*=\s*require\b|\bexport\s*=", code)

    def test_ts_extensions_in_relative_imports(self, source: Path) -> None:
        for spec in re.findall(r"""from\s+["'](\.[^"']+)["']""", read(source)):
            assert spec.endswith(".ts"), f"{source.name}: {spec}"  # node needs the extension


def imports_of(source: Path) -> list[str]:
    return re.findall(
        r"""(?m)^\s*(?:import|export)\b[^'"\n]*?from\s+["']([^"']+)["']""", read(source)
    )


def test_core_imports_only_node_modules() -> None:
    assert all(name.startswith("node:") for name in imports_of(PLUGIN / "core.ts"))
    assert "@opencode" not in read(PLUGIN / "core.ts")


def test_core_is_installed_byte_identical_so_it_holds_no_placeholder() -> None:
    assert "__CARTER_" not in read(PLUGIN / "core.ts")


@pytest.mark.skipif(not (PLUGIN / "index.ts").exists(), reason="index.ts arrives in step 16")
class TestIndex:
    def test_index_holds_exactly_the_two_render_placeholders(self) -> None:
        text = read(PLUGIN / "index.ts")
        assert sorted(re.findall(r"__CARTER_[A-Z0-9_]+__", text)) == [
            "__CARTER_ISOLATION_SHA256__",
            "__CARTER_VERSION__",
        ]

    def test_index_registers_no_tool_and_no_permission_hook_in_2a(self) -> None:
        text = strip_comments(read(PLUGIN / "index.ts"))
        assert "tool.transform" not in text and "permission" not in text and "evaluate" not in text

    def test_index_imports_only_the_plugin_api_node_and_core(self) -> None:
        for name in imports_of(PLUGIN / "index.ts"):
            assert name == "@opencode/plugin" or name == "./core.ts" or name.startswith("node:"), (
                name
            )

    def test_index_stays_tiny(self) -> None:
        assert len(read(PLUGIN / "index.ts").splitlines()) <= INDEX_MAX_LINES


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
class TestNoPythonOnlyKnowledge:
    def test_no_gate_or_git_vocabulary(self, source: Path) -> None:
        code = strip_comments(read(source))
        for word in FORBIDDEN_WORDS:
            assert word not in code, (
                f"{source.name} hard-codes {word!r}: it belongs in isolation.json"
            )

    def test_no_credential_path_segments(self, source: Path) -> None:
        code = strip_comments(read(source))
        for segment in load_rules().credential_paths:
            assert segment not in code, f"{source.name} names the credential path {segment!r}"

    def test_no_isolation_variable_names_beyond_the_protocol(self, source: Path) -> None:
        names = set(re.findall(r"""["'`]([A-Z][A-Z0-9_]{3,})["'`]""", strip_comments(read(source))))
        data = load_rules()
        prefixes = ("GIT_", "GH_", "SSH_", "DBUS_", "HOME", "OPENCODE", "AGENT")
        env_like = {n for n in names if n.startswith(prefixes)}
        named_signals = names & (set(data.agent_signals) | set(data.human_signals))
        leaked = (env_like | named_signals) - PROTOCOL_NAMES
        assert leaked == set(), f"{source.name}: {sorted(leaked)} must come from isolation.json"
