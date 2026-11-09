"""The audit store and the ``ops audit.log`` move."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from carter.broker import audit
from carter.ops import carter_ops


@pytest.fixture
def carter_dir(tmp_path: Path) -> Path:
    path = tmp_path / ".carter"
    path.mkdir()
    return path


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


EVENT = {
    "root": "ses_root", "session": "ses_child", "agent": "carter-devops", "owner_repo": "o/r",
    "branch": "feat/x", "range": "aaaaaaa..bbbbbbb", "commits": 2, "verb": "push",
    "decision": "approved", "code": "", "dwell_ms": 812,
}  # fmt: skip


class TestStore:
    def test_the_directory_is_0700_the_files_0600_and_the_line_has_exactly_the_fields(
        self, carter_dir: Path
    ) -> None:
        audit.record(EVENT, carter_dir)
        directory = audit.audit_dir(carter_dir)
        assert mode(directory) == 0o700 and mode(directory / "b.jsonl") == 0o600
        (line,) = (directory / "b.jsonl").read_text().splitlines()
        assert list(json.loads(line)) == sorted(audit.FIELDS)
        assert json.loads(line)["dwell_ms"] == 812

    def test_unknown_keys_values_and_secrets_never_land(self, carter_dir: Path) -> None:
        audit.record(
            {**EVENT, "env": {"OPENCODE_SERVER_PASSWORD": "pw"}, "url": "https://u:tok@h/x"},
            carter_dir,
        )
        text = (audit.audit_dir(carter_dir) / "b.jsonl").read_text()
        assert "pw" not in text and "tok" not in text and "url" not in text

    def test_a_model_chosen_branch_cannot_forge_a_second_line(self, carter_dir: Path) -> None:
        audit.record({**EVENT, "branch": 'x"}\n{"decision": "approved'}, carter_dir)
        lines = (audit.audit_dir(carter_dir) / "b.jsonl").read_text().splitlines()
        assert len(lines) == 1 and json.loads(lines[0])["decision"] == "approved"
        assert "\n" not in json.loads(lines[0])["branch"]

    def test_values_are_bounded(self, carter_dir: Path) -> None:
        audit.record({**EVENT, "branch": "b" * 5000}, carter_dir)
        (line,) = audit.read_b(carter_dir)
        assert len(line["branch"]) == audit.MAX_VALUE

    def test_an_unknown_decision_is_refused(self, carter_dir: Path) -> None:
        with pytest.raises(audit.AuditError):
            audit.record({**EVENT, "decision": "maybe"}, carter_dir)

    def test_rotation_at_the_size_cap_keeps_three_files(
        self, carter_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(audit, "ROTATE_BYTES", 300)
        for i in range(30):
            audit.record({**EVENT, "commits": i}, carter_dir)
        names = sorted(p.name for p in audit.audit_dir(carter_dir).glob("b.jsonl*"))
        assert names == ["b.jsonl", "b.jsonl.1", "b.jsonl.2", "b.jsonl.3"]
        assert all(mode(p) == 0o600 for p in audit.audit_dir(carter_dir).glob("b.jsonl*"))

    def test_a_corrupt_line_is_skipped_and_never_blocks_a_new_one(self, carter_dir: Path) -> None:
        audit.record(EVENT, carter_dir)
        with (audit.audit_dir(carter_dir) / "b.jsonl").open("a") as fh:
            fh.write("{not json\n")
        audit.record({**EVENT, "decision": "rejected"}, carter_dir)
        assert [e["decision"] for e in audit.read_b(carter_dir)] == ["approved", "rejected"]

    def test_a_symlinked_log_is_not_followed(self, carter_dir: Path, tmp_path: Path) -> None:
        directory = audit.audit_dir(carter_dir)
        directory.parent.mkdir(parents=True)
        directory.mkdir()
        target = tmp_path / "elsewhere"
        target.write_text("")
        (directory / "b.jsonl").symlink_to(target)
        with pytest.raises(audit.AuditError):
            audit.record(EVENT, carter_dir)
        assert target.read_text() == ""


class TestOpsLog:
    def test_the_path_is_resolved_when_used_not_at_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(carter_ops, "AUDIT_LOG", None)
        carter_ops._audit({"operation": "x"})
        written = home / ".carter" / "state" / "audit" / "audit.log"
        assert json.loads(written.read_text()) == {"operation": "x"}
        assert mode(written.parent) == 0o700 and mode(written) == 0o600

    def test_a_test_may_still_point_the_ops_log_at_a_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(carter_ops, "AUDIT_LOG", tmp_path / "x.log")
        carter_ops._audit({"operation": "y"})
        assert (tmp_path / "x.log").read_text().strip() == '{"operation": "y"}'
