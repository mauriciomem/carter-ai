"""User docs for slice 2b (plan 005): documented options equal ``--help``, the error codes named in
the docs are the registered ones. Grows with each documented command (steps 11, 15-17, 22, 28)."""

from __future__ import annotations

import re

import pytest

from carter.identity.errors import registry
from test_docs_slice1g import documented, help_options, section, text


class TestIdentityReference:
    @pytest.mark.parametrize("sub", ["unlock", "lock"])
    def test_documented_options_equal_help(self, sub: str) -> None:
        block = section(text("reference/cli.md"), f"carter identity {sub}", "###")
        assert documented(block) == help_options("identity", sub)

    def test_the_group_is_listed_in_the_command_table(self) -> None:
        assert "[`identity`](#carter-identity)" in text("reference/cli.md")

    def test_every_error_code_the_section_names_is_registered(self) -> None:
        block = section(text("reference/cli.md"), "carter identity")
        for code in set(re.findall(r"E-[A-Z0-9]+(?:-[A-Z0-9]+)+", block)):
            assert code in registry(), code

    def test_the_unlock_refusals_are_documented(self) -> None:
        block = " ".join(section(text("reference/cli.md"), "carter identity unlock", "###").split())
        for needle in ("OPENCODE_TERMINAL", "E-UNLOCK-OPENCODE", "E-UNLOCK-TTY", "E-UNLOCK-NOPASS"):
            assert needle in block
