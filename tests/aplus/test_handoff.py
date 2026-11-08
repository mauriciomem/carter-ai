"""The handoff file: the only input of ``carter pr`` (RFC-0007 C.6.6, freeze F11; plan 003
step 17)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from carter.aplus import handoff as h
from carter.aplus.handoff import Handoff
from carter.identity import IdentityError
from carter.identity.errors import E_HANDOFF, registry

SHA = "a" * 40


def sample(**kw) -> Handoff:
    fields = {
        "title": "feat: add x",
        "base": "main",
        "draft": False,
        "head_sha": SHA,
        "repo": "o/r",
        "body": "Body.\n",
    }
    return Handoff(**{**fields, **kw})


def text(**fm) -> str:
    keys = {
        "title": '"feat: add x"',  # a colon-space needs quotes in YAML; render_handoff quotes
        "base": "main",
        "draft": "false",
        "head_sha": SHA,
        "repo": "o/r",
    }
    keys.update(fm)
    lines = [f"{k}: {v}" for k, v in keys.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\n\nBody.\n"


class TestEncoding:
    @pytest.mark.parametrize(
        ("branch", "name"),
        [
            ("main", "main.md"),
            ("feat/x", "feat%2Fx.md"),
            ("feat/a/b", "feat%2Fa%2Fb.md"),
            ("100%/done", "100%25%2Fdone.md"),
            ("a%2Fb", "a%252Fb.md"),  # a literal %2F in a branch name stays distinct
        ],
    )
    def test_percent_encodes_percent_and_slash_only(self, branch: str, name: str) -> None:
        assert h.handoff_filename(branch) == name
        assert h.decode_branch(name.removesuffix(".md")) == branch

    @pytest.mark.parametrize(
        "branch", ["main", "feat/x", "a%2Fb", "x%y", "release/1.0/rc-1", "é/ü"]
    )
    def test_round_trips(self, branch: str) -> None:
        assert h.decode_branch(h.encode_branch(branch)) == branch

    def test_two_different_branches_never_share_a_file(self) -> None:
        assert h.encode_branch("a/b") != h.encode_branch("a%2Fb")

    @pytest.mark.parametrize(
        "bad",
        [
            "", "..", "a/../b", "../etc", "/abs/path", "a\0b", "a\nb", "a b", "-leading", ".hidden",
            "trail/", "a//b", "x.lock", "a@{b", "a~b", "a^b", "a:b", "a?b", "a*b", "a[b", "a\\b",
            "x" * 300,
        ],
    )  # fmt: skip
    def test_rejects_unsafe_branch_names(self, bad: str) -> None:
        with pytest.raises(IdentityError) as exc:
            h.encode_branch(bad)
        assert exc.value.code == E_HANDOFF

    def test_decode_rejects_bad_escapes_and_traversal(self) -> None:
        for bad in ("a%", "a%2", "a%zz", "a%2f", "..", "a%00b", ""):
            with pytest.raises(IdentityError):
                h.decode_branch(bad)

    def test_the_path_is_under_state_handoff(self, tmp_path: Path) -> None:
        p = h.handoff_path(tmp_path, "feat/x")
        assert p == tmp_path / ".carter" / "state" / "handoff" / "feat%2Fx.md"


class TestParse:
    def test_a_valid_file_gives_the_model_and_the_body(self) -> None:
        got, warnings = h.parse_handoff(text())
        assert got == sample() and warnings == []
        assert h.parse_handoff(text(draft="true"))[0].draft is True

    def test_only_the_model_comes_back_never_argv_or_flags(self) -> None:
        got, _ = h.parse_handoff(text())
        assert set(vars(got)) == {"title", "base", "draft", "head_sha", "repo", "body"}

    @pytest.mark.parametrize("missing", ["title", "base", "draft", "head_sha", "repo"])
    def test_each_key_is_required(self, missing: str) -> None:
        with pytest.raises(IdentityError) as exc:
            h.parse_handoff(text(**{missing: None}))
        assert exc.value.code == E_HANDOFF and missing in exc.value.detail

    @pytest.mark.parametrize(
        "kw",
        [
            {"draft": "1"}, {"draft": "'false'"}, {"head_sha": "abc123"},
            {"head_sha": "A" * 40}, {"head_sha": "g" * 40}, {"head_sha": "a" * 41},
            {"repo": "just-a-name"}, {"repo": "a/b/c"}, {"repo": "../x"}, {"repo": "o/ r"},
            {"title": "''"}, {"title": '"two\\nlines"'}, {"title": "'x" + "y" * 300 + "'"},
            {"title": '"bell\\x07"'}, {"base": "''"}, {"base": "'a b'"}, {"base": "--force"},
            {"title": "[a, b]"}, {"base": "{x: y}"}, {"title": "5"},
        ],
    )  # fmt: skip
    def test_values_are_validated(self, kw: dict) -> None:
        with pytest.raises(IdentityError) as exc:
            h.parse_handoff(text(**kw))
        assert exc.value.code == E_HANDOFF

    def test_unknown_keys_are_refused_so_no_flags_can_ride_in(self) -> None:
        for extra in ({"argv": "[--force]"}, {"flags": "x"}, {"assignee": "me"}, {"labels": "[a]"}):
            with pytest.raises(IdentityError) as exc:
                h.parse_handoff(text(**extra))
            assert exc.value.code == E_HANDOFF and "unknown" in exc.value.detail

    def test_the_detail_names_keys_never_values(self) -> None:
        with pytest.raises(IdentityError) as exc:
            h.parse_handoff(text(head_sha="SUPERSECRETVALUE", extra_key="SUPERSECRETVALUE2"))
        assert "SUPERSECRET" not in exc.value.detail and "SUPERSECRET" not in str(exc.value)

    @pytest.mark.parametrize(
        "bad", ["", "no front matter\n", "---\nunterminated: true\n", "---\n- a\n- b\n---\n"]
    )
    def test_no_front_matter_or_not_a_mapping(self, bad: str) -> None:
        with pytest.raises(IdentityError):
            h.parse_handoff(bad)

    def test_message_is_the_registry_text(self) -> None:
        with pytest.raises(IdentityError) as exc:
            h.parse_handoff("")
        assert str(exc.value) == registry()[E_HANDOFF].message

    def test_crlf_and_bom_are_tolerated(self) -> None:
        crlf = text().replace("\n", "\r\n")
        assert h.parse_handoff(crlf)[0] == sample(body="Body.\r\n".replace("\r\n", "\n"))
        assert h.parse_handoff("\ufeff" + text())[0].title == "feat: add x"

    def test_a_ten_thousand_line_body_parses(self) -> None:
        big = text() + "line\n" * 10_000
        got, _ = h.parse_handoff(big)
        assert got.body.count("\n") >= 10_000

    def test_a_front_matter_bomb_is_refused(self) -> None:
        bomb = "---\ntitle: x\n" + "k: " + "a" * 100_000 + "\n---\nbody\n"
        with pytest.raises(IdentityError):
            h.parse_handoff(bomb)

    def test_yaml_aliases_cannot_expand(self) -> None:
        lol = (
            "---\na: &a [x, x, x, x]\nb: &b [*a, *a, *a, *a]\n"
            "c: &c [*b, *b, *b, *b]\ntitle: *c\n---\n"
        )
        with pytest.raises(IdentityError) as exc:
            h.parse_handoff(lol)
        assert "alias" in exc.value.detail

    def test_yaml_tags_are_refused(self) -> None:
        with pytest.raises(IdentityError):
            h.parse_handoff(text(title="!!python/object/apply:os.system [x]"))

    def test_a_body_larger_than_the_cap_is_refused(self) -> None:
        with pytest.raises(IdentityError):
            h.parse_handoff(text() + "x" * (h.MAX_FILE_BYTES + 1))


class TestReadWrite:
    def test_write_creates_a_0600_file_in_a_0700_dir_and_reads_back(self, tmp_path: Path) -> None:
        path = h.write_handoff(tmp_path, "feat/x", sample())
        assert path == h.handoff_path(tmp_path, "feat/x")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert h.read_handoff(tmp_path, "feat/x") == sample()

    def test_writing_twice_replaces_the_file(self, tmp_path: Path) -> None:
        h.write_handoff(tmp_path, "b", sample(title="one"))
        h.write_handoff(tmp_path, "b", sample(title="two"))
        assert h.read_handoff(tmp_path, "b").title == "two"
        assert [p.name for p in h.handoff_path(tmp_path, "b").parent.iterdir()] == ["b.md"]

    def test_read_missing_is_e_handoff(self, tmp_path: Path) -> None:
        with pytest.raises(IdentityError) as exc:
            h.read_handoff(tmp_path, "nope")
        assert exc.value.code == E_HANDOFF

    def test_a_symlinked_handoff_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere.md"
        target.write_text(text())
        path = h.handoff_path(tmp_path, "b")
        path.parent.mkdir(parents=True)
        path.symlink_to(target)
        with pytest.raises(IdentityError):
            h.read_handoff(tmp_path, "b")

    def test_a_non_regular_file_is_refused(self, tmp_path: Path) -> None:
        path = h.handoff_path(tmp_path, "b")
        path.parent.mkdir(parents=True)
        path.mkdir()
        with pytest.raises(IdentityError):
            h.read_handoff(tmp_path, "b")

    def test_an_oversized_file_is_refused_before_it_is_read_whole(self, tmp_path: Path) -> None:
        path = h.handoff_path(tmp_path, "b")
        path.parent.mkdir(parents=True)
        path.write_text(text() + "x" * (h.MAX_FILE_BYTES + 10))
        with pytest.raises(IdentityError):
            h.read_handoff(tmp_path, "b")

    def test_invalid_utf8_is_refused(self, tmp_path: Path) -> None:
        path = h.handoff_path(tmp_path, "b")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"---\ntitle: \xff\xfe\n---\n")
        with pytest.raises(IdentityError):
            h.read_handoff(tmp_path, "b")

    def test_a_branch_with_dotdot_cannot_escape_the_handoff_dir(self, tmp_path: Path) -> None:
        with pytest.raises(IdentityError):
            h.handoff_path(tmp_path, "../../etc/passwd")


class TestDelete:
    def test_deletes_only_after_success_and_only_that_file(self, tmp_path: Path) -> None:
        mine = h.write_handoff(tmp_path, "a", sample())
        other = h.write_handoff(tmp_path, "b", sample())
        assert h.delete_after_success(tmp_path, "a", success=False) is False
        assert mine.exists()
        assert h.delete_after_success(tmp_path, "a", success=True) is True
        assert not mine.exists() and other.exists()

    def test_missing_file_is_a_quiet_false(self, tmp_path: Path) -> None:
        assert h.delete_after_success(tmp_path, "gone", success=True) is False

    def test_never_follows_a_symlink_out_of_the_handoff_dir(self, tmp_path: Path) -> None:
        victim = tmp_path / "victim.txt"
        victim.write_text("keep")
        path = h.handoff_path(tmp_path, "a")
        path.parent.mkdir(parents=True)
        path.symlink_to(victim)
        h.delete_after_success(tmp_path, "a", success=True)
        assert victim.read_text() == "keep"

    def test_success_must_be_the_boolean_true(self, tmp_path: Path) -> None:
        mine = h.write_handoff(tmp_path, "a", sample())
        assert h.delete_after_success(tmp_path, "a", success=1) is False  # type: ignore[arg-type]
        assert mine.exists()


class TestWording:
    def test_the_own_terminal_sentence_is_one_constant_that_names_the_bang_shell(self) -> None:
        assert "carter push" in h.OWN_TERMINAL and "carter pr" in h.OWN_TERMINAL
        assert "`!carter push`" in h.OWN_TERMINAL and "not through an agent" in h.OWN_TERMINAL

    def test_the_agent_facing_handoff_template_round_trips_through_the_parser(self) -> None:
        template = h.handoff_template("feat/x", "o/r", SHA)
        got, _ = h.parse_handoff(template)
        assert got.repo == "o/r" and got.head_sha == SHA

    def test_modules_import_no_click(self) -> None:
        import ast

        tree = ast.parse(Path(h.__file__).read_text(encoding="utf-8"))
        names = {
            (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import | ast.ImportFrom)
            for a in (n.names if isinstance(n, ast.Import) else [n])
        }
        assert not {x for x in names if x.split(".")[0] == "click"}
        assert os.fspath(Path(h.__file__)).endswith("handoff.py")
