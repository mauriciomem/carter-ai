# ruff: noqa: E501
"""The review-only workflow template."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from carter.ci import ENVIRONMENT, OPENCODE_VERSION, SECRET, WORKFLOW_REL, template
from ci.helpers import find_actionlint, run_actionlint

PINS = {  # the repository's own pins reused, not invented
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-node": "949feb2413d6458794dcd2491c4babbbce0c15c1",
    "astral-sh/setup-uv": "07a047e608db84b3d8c06cd9a7c7dcc9c355c18e",
    "actions/upload-artifact": "cf430e030ddbb5b0abf93d22962f4752f3646cd9",
    "actions/download-artifact": "37930b1c2abaa49bbe596cd826c3c89aef350131",
}


def doc_of(text: str) -> dict:
    return yaml.safe_load(text)


class TestShape:
    def test_it_is_deterministic(self) -> None:
        assert template.render(comment=False) == template.render(comment=False)
        assert template.render(comment=True) == template.render(comment=True)

    def test_trigger_permissions_concurrency_and_timeout(self, rendered: str) -> None:
        doc = doc_of(rendered)
        assert doc[True] == {"pull_request": None}  # `on:` parses as True in YAML 1.1
        assert doc["permissions"] == {"contents": "read"}
        assert doc["concurrency"]["cancel-in-progress"] is True
        review = doc["jobs"]["review"]
        assert review["permissions"] == {"contents": "read"}
        assert review["timeout-minutes"] <= 15 and review["environment"] == ENVIRONMENT
        assert review["runs-on"] == "ubuntu-latest"

    def test_pull_request_target_appears_nowhere_in_the_yaml(self, rendered: str) -> None:
        code = re.sub(r"(?m)^\s*#.*$", "", rendered)  # the header comment may say "never ..."
        assert "pull_request_target" not in code and "workflow_run" not in code

    def test_actions_are_pinned_to_the_repositorys_own_shas(self, rendered: str) -> None:
        used = dict(re.findall(r"uses:\s*([\w./-]+)@([0-9a-f]{40})\s+# v\d", rendered))
        assert used and all(PINS[name] == sha for name, sha in used.items())
        assert len(re.findall(r"uses:", rendered)) == len(used)

    def test_checkout_does_not_persist_credentials_and_has_the_history_for_the_diff(
        self, rendered: str
    ) -> None:
        step = doc_of(rendered)["jobs"]["review"]["steps"][0]
        assert step["with"] == {"fetch-depth": 0, "persist-credentials": False}

    def test_the_secret_is_read_only_in_step_level_env(self, rendered: str) -> None:
        hits = [m.start() for m in re.finditer(r"secrets\.", rendered)]
        assert len(hits) == 2 and set(re.findall(r"secrets\.(\w+)", rendered)) == {SECRET}
        steps = doc_of(rendered)["jobs"]["review"]["steps"]
        reading = [s["name"] for s in steps if "secrets." in str(s.get("env", ""))]
        assert reading == ["Is the provider key available?", "Review the pull request (read-only)"]

    def test_fork_pull_requests_are_skipped_not_failed(self, rendered: str) -> None:
        review = doc_of(rendered)["jobs"]["review"]
        assert review["if"] == "github.event.pull_request.head.repo.full_name == github.repository"
        gate = review["steps"][1]
        assert gate["id"] == "gate" and "-z" in gate["run"] and "exit 1" not in gate["run"]
        later = list(review["steps"][2:])
        assert later and all(s["if"] == "steps.gate.outputs.run == 'true'" for s in later)

    def test_scripts_hold_no_expressions(self, rendered: str) -> None:
        for job in doc_of(rendered)["jobs"].values():
            for step in job["steps"]:
                assert "${{" not in step.get("run", "")

    def test_the_output_goes_to_the_step_summary_not_a_comment_by_default(self) -> None:
        plain = template.render(comment=False)
        assert "GITHUB_STEP_SUMMARY" in plain and "pull-requests" not in plain
        assert "gh pr comment" not in plain and "comment:" not in re.sub(r"(?m)^\s*#.*$", "", plain)

    def test_the_review_step_runs_in_review_mode_with_the_base_sha(self, rendered: str) -> None:
        step = doc_of(rendered)["jobs"]["review"]["steps"][-1 if "comment" not in rendered else -2]
        env = step["env"]
        assert env["CARTER_IDENTITY_MODE"] == "review"
        assert env["CARTER_CI_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
        assert step["run"] == "carter ci review"

    def test_versions_are_pinned(self) -> None:
        text = template.render(carter_version="1.2.3")
        assert f'"@opencode/cli@{OPENCODE_VERSION}"' in text and '"carter-ai==1.2.3"' in text
        assert "__CARTER_VERSION__" not in text and "__OPENCODE_VERSION__" not in text

    def test_a_local_version_suffix_is_dropped(self) -> None:
        import carter

        original = carter.__version__
        try:
            carter.__version__ = "0.17.0+g1234.dirty"
            assert '"carter-ai==0.17.0"' in template.render()
        finally:
            carter.__version__ = original

    def test_no_placeholder_is_left(self, rendered: str) -> None:
        assert not re.search(r"__[A-Z_]+__", rendered)


class TestCommentOptIn:
    def test_a_second_job_with_one_write_scope_and_no_checkout(self) -> None:
        jobs = doc_of(template.render(comment=True))["jobs"]
        assert list(jobs) == ["review", "comment"]
        comment = jobs["comment"]
        assert comment["permissions"] == {"pull-requests": "write"}
        assert comment["needs"] == "review" and comment["timeout-minutes"] <= 5
        assert not any("checkout" in str(s.get("uses", "")) for s in comment["steps"])
        scripts = " ".join(str(s.get("run", "")) for s in comment["steps"])
        assert "carter ci" not in scripts and "opencode" not in scripts and "npm" not in scripts
        assert jobs["review"]["permissions"] == {"contents": "read"}

    def test_the_comment_is_posted_from_a_file_with_the_token_in_env_only(self) -> None:
        step = doc_of(template.render(comment=True))["jobs"]["comment"]["steps"][-1]
        assert step["run"] == 'gh pr comment "$PR_NUMBER" --body-file carter-review-comment.md'
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"

    def test_the_two_variants_differ_only_by_the_opt_in(self) -> None:
        plain = template.render(comment=False).splitlines()
        wide = template.render(comment=True).splitlines()
        removed = [ln for ln in plain if ln not in wide and not ln.startswith("# carter-template")]
        assert all(
            ln.startswith("#") or "comment" in ln.lower() or ln.strip() == "" for ln in removed
        )


class TestHeader:
    def test_the_first_line_is_a_hash_of_the_rest(self, rendered: str) -> None:
        recorded, body = template.split(rendered)
        assert recorded == template.body_hash(body) and template.is_unedited(rendered)

    def test_any_edit_is_noticed(self, rendered: str) -> None:
        assert not template.is_unedited(
            rendered.replace("timeout-minutes: 15", "timeout-minutes: 14")
        )
        assert not template.is_unedited(rendered + "# x\n")

    def test_a_file_without_the_header_is_not_ours(self) -> None:
        assert template.split("name: x\n") == (None, "name: x\n") and not template.is_unedited(
            "name: x\n"
        )

    def test_the_install_path_is_the_conventional_one(self) -> None:
        assert WORKFLOW_REL == ".github/workflows/carter-review.yml"


@pytest.mark.skipif(find_actionlint() is None, reason="actionlint is not installed here")
def test_actionlint_accepts_both_variants(rendered: str, tmp_path: Path) -> None:
    path = tmp_path / "w.yml"
    path.write_text(rendered)
    done = run_actionlint(find_actionlint() or "", path)
    assert done.returncode == 0, done.stdout
