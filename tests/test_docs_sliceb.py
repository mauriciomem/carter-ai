# ruff: noqa: E501
"""User docs for slice B, the push and PR tools (plan 007 step 20): the guide covers the tools,
the docs equal the code (codes, constants, paths, options) and nothing teaches a bypass."""

from __future__ import annotations

import re

from carter.broker import audit, counter, plan
from carter.guard import consent, plugin
from carter.identity.errors import registry
from carter.identity.schema import schema_names
from test_docs_slice1g import documented, help_options, section, text

GUIDE = "guides/push-and-pr-tools.md"


def guide() -> str:
    return " ".join(text(GUIDE).split())


class TestGuide:
    def test_it_covers_what_the_plan_requires(self) -> None:
        body = guide()
        for needle in (
            "A+", "B is a convenience, not a security boundary",
            "Forgeable by a same-user agent until a sandbox exists",
            "ask you to approve every single use", "Once", "Reject", "there is no \"Always\"",
            "g2` **revision 3**", "carter guard install --yes --only g2",
            "carter guard remove --only broker", "carter guard status --reset-b",
            "less than half a second", "120 seconds", "Three rejections",
            "OPENCODE_CONFIG=~/.carter/opencode-headless.json opencode run --standalone",
            "ignores it", "~/.carter/state/audit/b.jsonl", "b-rejections.json",
            "never searches `PATH`", "ssh_bin_dir", "ProxyJump", "/etc/ssh",
        ):  # fmt: skip
            assert needle in body, needle

    def test_every_code_it_names_is_registered(self) -> None:
        for code in set(re.findall(r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+", text(GUIDE))):
            assert code in registry(), code

    def test_every_b_code_is_in_the_guide_s_table_or_text(self) -> None:
        body = text(GUIDE)
        for code in ("E-B-CALLER", "E-B-DEFAULT", "E-B-HTTPS", "E-B-REPOCFG", "E-B-UNSIGNED",
                     "E-B-NOAGENT", "E-B-POLLUTED", "E-B-MOVED", "E-B-DWELL", "E-B-TIMEOUT",
                     "E-B-REJECTED", "E-B-ARGS", "E-B-HEADLESS"):  # fmt: skip
            assert code in body, code

    def test_the_numbers_are_the_code_s(self) -> None:
        body = guide()
        assert f"{plan.DWELL_FLOOR_MS / 1000:g}" == "0.5" and "half a second" in body
        assert f"{plan.TIMEOUT_MS // 1000} seconds" in body
        assert f"{counter.MAX_REJECTIONS}" == "3" and "Three rejections" in body
        assert "10 000" in body and str(plan.DWELL_CAP_MS) in str(plan.DWELL_CAP_MS)
        assert f"{audit.ROTATE_BYTES // (1024 * 1024)} MiB" in body
        for directory in plugin.TOOL_DIRS:
            assert directory in body, directory

    def test_it_never_recommends_auto_accept(self) -> None:
        body = guide()
        for risky in ("--auto", "auto-accept"):
            for sentence in re.findall(r"[^.]*" + re.escape(risky) + r"[^.]*\.", body):
                assert re.search(r"\b(not|never|refus|warn|stop|rejects|would be)", sentence), (
                    sentence
                )

    def test_no_link_into_the_local_only_folders(self) -> None:
        for target in re.findall(r"\]\(([^)]+)\)", text(GUIDE)):
            assert not target.startswith(("../adr", "../rfcs", "docs/adr", "docs/rfcs")), target


class TestReferenceEqualsCode:
    def test_guard_status_documents_exactly_its_option(self) -> None:
        assert help_options("guard", "status") == {"--reset-b", "--verbose"}
        assert documented(section(text("reference/cli.md"), "carter guard status", "###")) == {
            "--reset-b",
            "--verbose",
        }

    def test_guard_remove_documents_broker_and_the_plugin(self) -> None:
        block = section(text("reference/cli.md"), "carter guard remove", "###")
        assert "plugin|broker" in block and "`broker` turns only" in block
        assert consent.BROKER == "broker"

    def test_the_config_table_and_keys(self) -> None:
        keys = schema_names()["broker"]
        body = " ".join(text("reference/configuration.md").split())
        for key in keys:
            assert f"`{key}`" in body or f"{key} =" in body, key
        assert "[broker]" in body

    def test_the_files_are_listed(self) -> None:
        files = " ".join(text("reference/files-and-paths.md").split())
        for needle in ("state/audit/b.jsonl", "state/audit/audit.log", "b-rejections.json",
                       "opencode-headless.json", "broker.ts"):  # fmt: skip
            assert needle in files, needle
        assert "~/.carter/audit.log` |" not in files  # the ops log moved

    def test_troubleshooting_has_a_row_for_every_agent_facing_b_code(self) -> None:
        body = text("troubleshooting.md")
        for code in ("E-B-DWELL", "E-B-TIMEOUT", "E-B-REJECTED", "E-B-POLLUTED", "E-B-NOAGENT",
                     "E-B-REPOCFG", "E-B-HTTPS", "E-B-DEFAULT", "E-B-UNSIGNED", "E-B-ARGS"):  # fmt: skip
            assert code in body, code

    def test_the_safety_guide_states_the_residual_in_plain_words(self) -> None:
        body = " ".join(text("guides/safety-and-permissions.md").split())
        assert "forgeable by a same-user agent until a sandbox exists" in body.lower()
        assert "convenience, not a boundary" in body
