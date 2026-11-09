"""The reference docs equal the code.

Documented options equal ``--help``, the documented ``carter ops config --emit`` output has
the keys the command really prints, the configuration examples load through the schema, and
every file, command and error code the docs name exists.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from carter.cli import main
from carter.config import generate_default_config
from carter.identity import load_identity
from carter.identity.errors import registry
from carter.identity.schema import Github, schema_names
from carter.ops import carter_ops
from docs_support import DOCS, codes_in, documented, help_options, section, text, user_docs

# (heading in cli.md, heading level, the command whose --help lists the same options)
OPTION_TABLES = [
    ("carter install", "##", ("install",)),
    ("carter uninstall", "##", ("uninstall",)),
    ("carter guard install", "###", ("guard", "install")),
    ("carter guard remove", "###", ("guard", "remove")),
    ("carter guard status", "###", ("guard", "status")),
    ("carter identity add", "###", ("identity", "add")),
    ("carter identity show", "###", ("identity", "show")),
    ("carter identity verify", "###", ("identity", "verify")),
    ("carter identity remove", "###", ("identity", "remove")),
    ("carter identity unlock", "###", ("identity", "unlock")),
    ("carter identity lock", "###", ("identity", "lock")),
    ("carter push", "##", ("push",)),
    ("carter ci install", "###", ("ci", "install")),
    ("carter ci review", "###", ("ci", "review")),
    ("carter gate check", "###", ("gate", "check")),
]


class TestCliReference:
    @pytest.mark.parametrize(("heading", "level", "command"), OPTION_TABLES)
    def test_documented_options_equal_help(
        self, heading: str, level: str, command: tuple[str, ...]
    ) -> None:
        block = section(text("reference/cli.md"), heading, level)
        assert documented(block) == help_options(*command)

    def test_update_documents_every_option(self) -> None:
        block = section(text("reference/cli.md"), "carter update")
        for option in help_options("update"):
            assert option in block, option

    def test_every_command_has_a_heading(self) -> None:
        doc = text("reference/cli.md")
        for name, command in main.commands.items():
            if not command.hidden:
                assert f"\n## carter {name}\n" in doc, name

    def test_the_guard_commands_are_all_listed(self) -> None:
        listed = CliRunner().invoke(main, ["guard", "--help"]).output
        for name in ("install", "status", "remove"):
            assert name in listed and f"### carter guard {name}" in text("reference/cli.md")

    def test_check_has_host_and_probe(self) -> None:
        assert {"--host", "--probe"} <= help_options("check")
        doc = text("reference/cli.md")
        assert "### carter check --host" in doc and "### carter check --probe" in doc

    def test_every_error_code_in_the_reference_is_registered(self) -> None:
        assert codes_in(text("reference/cli.md")) <= set(registry())

    def test_carter_commit_refuses_the_flags_the_reference_lists(self) -> None:
        from carter.identity.commit import REFUSED_FLAGS

        block = " ".join(section(text("reference/cli.md"), "carter commit").split())
        for flag in REFUSED_FLAGS:
            assert flag.replace("<arg>", "<key>") in block, flag

    def test_carter_commit_asks_nothing_when_the_key_is_locked(self) -> None:
        block = " ".join(section(text("reference/cli.md"), "carter commit").split())
        assert "✗ key locked → carter identity unlock" in block
        assert "asked" not in block.split("key locked")[0].split("T2, key locked")[-1]

    def test_ops_help_does_not_talk_about_bots(self) -> None:
        assert "bot" not in (carter_ops.__doc__ or "")


class TestEmit:
    def real(self, capsys: pytest.CaptureFixture[str]) -> dict:
        assert carter_ops.main(["config", "--emit"]) == 0
        return json.loads(capsys.readouterr().out)

    def test_the_documented_json_has_exactly_the_printed_keys(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocks = re.findall(r"```json\n(.*?)```", text("guides/write-operations.md"), flags=re.S)
        shown = next(json.loads(b) for b in blocks if "coauthor_trailer" in b)
        printed = self.real(capsys)
        assert set(shown) == set(printed)
        assert shown == printed | {"has_github_token": shown["has_github_token"]}

    def test_the_reference_table_has_a_row_for_every_printed_key(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        block = section(text("reference/cli.md"), "carter ops config --emit", "###")
        rows = " ".join(re.findall(r"^\| ([^|]+) \|", block, flags=re.M))
        for key in self.real(capsys):
            assert f"`{key}`" in rows, key


class TestConfigurationReference:
    def test_the_full_example_is_the_generated_default(self) -> None:
        doc = text("reference/configuration.md")
        example = yaml.safe_load(re.search(r"```yaml\n(.*?)```", doc, flags=re.S).group(1))
        assert example == generate_default_config(workspace_name="my-project")

    def toml_block(self, marker: str) -> str:
        doc = section(text("reference/configuration.md"), "User config: `~/.carter/config.toml`")
        return next(b for b in re.findall(r"```toml\n(.*?)```", doc, flags=re.S) if marker in b)

    def test_the_workspace_example_loads_through_the_schema(self, tmp_path: Path) -> None:
        block = self.toml_block("allow_project_opencode_edit")
        (path,) = tomllib.loads(block)["workspaces"]
        assert path.startswith("/abs")
        cfg = tmp_path / "config.toml"
        cfg.write_text("schema = 2\n" + block.replace("/abs/path/to/project", str(tmp_path)))
        assert load_identity(cfg).workspaces[str(tmp_path)].allow_project_opencode_edit is True

    def test_the_github_example_is_the_schema_default(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(self.toml_block("[github]").replace("/abs/path", str(tmp_path)))
        assert load_identity(cfg).github == Github()

    def test_every_key_of_the_broker_and_workspace_tables_is_named(self) -> None:
        body = " ".join(text("reference/configuration.md").split())
        tables = {
            name: keys
            for name, keys in schema_names().items()
            if name.startswith(("broker", "workspaces"))
        }
        assert len(tables) == 2
        for table, keys in tables.items():
            for key in keys:
                assert f"`{key}`" in body or f"{key} =" in body, (table, key)

    def test_the_identity_keys_are_documented_as_policy(self) -> None:
        doc = text("reference/configuration.md")
        identity = doc[doc.index("### identity") :].split("\n### ", 2)[0]
        for needle in ("`role`", "`require_tier`", "`co-author`", "`author`", "`t0`", "`t2`"):
            assert needle in identity, needle
        assert "carter update" in identity and "~/.carter/config.toml" in identity

    def test_the_opt_out_lands_in_the_agents_permissions(self) -> None:
        doc = " ".join(text("reference/configuration.md").split())
        assert "only when a human runs `carter guard install` or `carter update`" in doc
        assert "Carter agents' permissions" in doc


class TestFilesAndPaths:
    @pytest.mark.parametrize(
        "path",
        [
            "~/.carter/guard-state.json",
            "~/.carter/gitconfig",
            "~/.carter/isolation.json",
            "~/.carter/hooks/carter-guard",
            "~/.carter/backups/<timestamp>/opencode.json[c]",
            "~/.carter/secrets/gh-read.token",
            "~/.carter/state/audit/audit.log",
            "~/.carter/state/audit/b.jsonl",
            "~/.carter/run/",
            "run/gh-empty/",
            "run/plugin-status/<pid>.json",
            "b-rejections.json",
            "opencode-headless.json",
            "~/.config/opencode/plugins/carter/index.ts",
            "<repo>/.git/hooks/pre-push",
            "carter-review.yml",
        ],
    )
    def test_each_path_is_listed(self, path: str) -> None:
        assert path in text("reference/files-and-paths.md")

    def test_guard_state_is_kept_apart_from_the_manifest(self) -> None:
        row = next(
            ln
            for ln in text("reference/files-and-paths.md").splitlines()
            if ln.startswith("| `~/.carter/guard-state.json`")
        )
        assert "0600" in row and "manifest.json" in row


class TestTroubleshooting:
    def test_every_code_named_is_registered(self) -> None:
        assert codes_in(text("troubleshooting.md")) <= set(registry())

    @pytest.mark.parametrize(
        "code",
        [
            "E-CONFIG", "E-ROLE-B-TIER", "E-HUMAN-IDENTITY", "E-CI-REVIEW",
            "E-HUMAN-TERMINAL", "E-POLICIES-MISSING", "E-STATE-INVALID",
            "E-ISOLATION-MISSING", "E-GATE", "E-GATE-FAIL", "E-PUSH-GUARD", "E-GIT-OLD",
            "E-OPENCODE-VERSION", "E-SELFTEST", "E-APLUS-ARGS", "E-PAT-TYPE", "E-PAT-PERM",
            "E-B-UNSIGNED", "E-B-DWELL", "E-B-TIMEOUT", "E-B-REJECTED", "E-B-POLLUTED",
            "E-B-NOAGENT", "E-B-DEFAULT", "E-B-HTTPS", "E-B-REPOCFG", "E-B-MOVED", "E-B-ARGS",
            "E-SIGN-LOCKED", "E-SIGN-NOAGENT", "E-SIGN-UNAVAILABLE", "E-SHIM-REFUSED",
            "E-SIGN-HUMAN-FALLBACK", "E-UNLOCK-OPENCODE", "E-UNLOCK-TTY", "E-UNLOCK-PATH",
            "E-UNLOCK-BADPASS", "E-GUARD-NOIDENT", "E-GUARD-COMMITTER", "E-GUARD-SIGNCFG",
            "E-GUARD-TRAILER", "E-GUARD-T01SIGN", "E-GUARD-UNSIGNED", "E-TIER-CAPPED",
            "E-TIER-REQUIRED", "E-IDENTITY-CHECK", "E-GITHUB-UNREACHABLE", "E-SSH-OLD",
        ],
    )  # fmt: skip
    def test_each_user_facing_code_has_a_row(self, code: str) -> None:
        assert re.search(rf"`{code}\b", text("troubleshooting.md")), code

    def test_the_malformed_gitconfig_recovery_is_exact(self) -> None:
        body = " ".join(text("troubleshooting.md").split())
        assert "rm ~/.carter/gitconfig" in body and "git works again at once" in body

    def test_every_identity_command_the_docs_name_exists(self) -> None:
        real = {"add", "show", "verify", "unlock", "lock", "remove", "env"}
        for name, body in user_docs().items():
            named = set(re.findall(r"carter identity (\w[\w-]*)", body))
            assert named <= real, (name, named - real)

    def test_the_docs_index_links_every_guide(self) -> None:
        index = text("README.md")
        for guide in sorted((DOCS / "guides").glob("*.md")):
            assert f"guides/{guide.name}" in index, guide.name
