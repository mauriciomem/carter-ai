"""Repository hygiene files: the gitleaks ignore list and the Dependabot configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IGNORE = ROOT / ".gitleaksignore"
FINGERPRINT = re.compile(r"^[0-9a-f]{40}:(?P<file>[\w./-]+):(?P<rule>[a-z-]+):(?P<line>\d+)$")


def entries() -> list[str]:
    return [
        ln.strip()
        for ln in IGNORE.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


class TestGitleaksIgnore:
    def test_it_lists_exactly_the_nine_checked_findings_without_repeats(self) -> None:
        found = entries()
        assert len(found) == 9 and len(set(found)) == 9

    def test_every_entry_is_a_commit_bound_fingerprint_of_test_data(self) -> None:
        for entry in entries():
            match = FINGERPRINT.match(entry)
            assert match, entry  # a bare path or a glob would allow a new secret in that file
            assert match["rule"] in {"generic-api-key", "private-key"}, entry
            assert match["file"].startswith(("tests/", "evals/")), (
                entry
            )  # test and eval data only, never product code

    def test_every_group_of_entries_says_what_it_is(self) -> None:
        lines = IGNORE.read_text().splitlines()
        for i, line in enumerate(lines):
            if FINGERPRINT.match(line.strip()) and not FINGERPRINT.match(lines[i - 1].strip()):
                assert lines[i - 1].startswith("#"), line  # a comment above the first of a group

    def test_it_matches_the_triaged_scan_when_the_scan_is_available(self) -> None:
        scan = ROOT / "notes" / "gitleaks.json"
        if not scan.is_file():  # notes/ is maintainer-local
            return
        assert set(entries()) == {f["Fingerprint"] for f in json.loads(scan.read_text())}


class TestDependabot:
    def test_actions_and_uv_are_updated_weekly_in_one_grouped_pull_request_each(self) -> None:
        doc = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
        assert doc["version"] == 2
        updates = {u["package-ecosystem"]: u for u in doc["updates"]}
        assert set(updates) == {"github-actions", "uv"}
        for update in updates.values():
            assert update["directory"] == "/"
            assert update["schedule"]["interval"] == "weekly"
            assert update["groups"] and update["open-pull-requests-limit"] <= 5
            assert update["cooldown"]["default-days"] >= 1
