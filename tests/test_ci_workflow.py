"""The CI workflow keeps its promises.

CI runs only after the human pushes, so locally the workflow is validated for syntax, pinning,
permissions and that every command that names a repo script or test path points at something
that exists. ``actionlint`` runs if it is installed.
"""

from __future__ import annotations

import glob
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
CI = ROOT / ".github" / "workflows" / "ci.yml"
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}(\s+#.*)?$")
PATH_WORDS = re.compile(r"(?<![\w$/{.-])((?:tests|evals|carter|scripts)/[\w./*-]+)")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def steps(job: dict):
    yield from job.get("steps", [])


@pytest.fixture(scope="module")
def ci() -> dict:
    return load(CI)


class TestJobs:
    @pytest.mark.parametrize(
        "name",
        [
            "lint",
            "test",
            "plugin",
            "gate-budget",
            "e2e-contract",
            "git-old",
            "macos-sh",
            "install-smoke",
            "identity-ssh",
            "ci-template",
        ],
    )
    def test_the_job_exists(self, ci: dict, name: str) -> None:
        assert name in ci["jobs"]

    def test_plugin_runs_node_22_and_24_on_both_systems(self, ci: dict) -> None:
        matrix = ci["jobs"]["plugin"]["strategy"]["matrix"]
        assert matrix["node"] == ["24", "22.18"] and set(matrix["os"]) == {
            "ubuntu-latest",
            "macos-latest",
        }
        runs = " ".join(s.get("run", "") for s in steps(ci["jobs"]["plugin"]))
        assert "node --test" in runs and "tests/test_plugin_parity.py" in runs

    def test_ci_template_checks_both_variants_with_the_checker_and_actionlint(
        self, ci: dict
    ) -> None:
        text = yaml.dump(ci["jobs"]["ci-template"])
        assert "carter ci check" in text and "actionlint" in text and "comment=comment" in text
        assert "tests/ci" in text and "actionlint-py==" in text

    def test_gate_budget_measures_the_installed_tool_and_is_required(self, ci: dict) -> None:
        job = ci["jobs"]["gate-budget"]
        text = yaml.dump(job)
        assert (
            "uv tool install ." in text and "CARTER_PERF" in text and "CARTER_GATE_PYTHON" in text
        )
        assert "tests/gate/test_budget.py" in text and "GITHUB_STEP_SUMMARY" in text
        assert not job.get("continue-on-error")

    def test_e2e_is_manual_and_latest_may_fail(self, ci: dict) -> None:
        job = ci["jobs"]["e2e-contract"]
        assert job["if"] == "github.event_name == 'workflow_dispatch'"
        text = yaml.dump(job)
        assert "tests/e2e/run.sh" in text and "unshare -rn" in text
        entries = {m["label"]: m for m in job["strategy"]["matrix"]["include"]}
        assert (
            entries["tested"]["experimental"] is False and entries["tested"]["version"] == "2.1.4"
        )
        assert entries["latest"]["experimental"] is True
        assert "workflow_dispatch" in (ci.get("on") or ci.get(True))

    def test_identity_ssh_runs_on_both_systems_and_always_checks_for_stray_agents(
        self, ci: dict
    ) -> None:
        job = ci["jobs"]["identity-ssh"]
        assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "macos-latest"}
        text = yaml.dump(job)
        assert (
            "tests/identity" in text
            and "test_carter_guard_commit_events.py" in text
            and "test_carter_guard_role_author.py" in text
            and "/usr/bin/ssh -V" in text
        )
        last = job["steps"][-1]
        assert last["if"] == "always()" and "pgrep" in last["run"]

    def test_every_job_that_starts_agents_has_the_if_always_cleanup_check(self, ci: dict) -> None:
        for name in ("identity-ssh", "e2e-contract"):
            last = ci["jobs"][name]["steps"][-1]
            assert last.get("if") == "always()" and "ssh-agent" in last["run"], name

    def test_the_signing_checks_are_in_the_existing_jobs(self, ci: dict) -> None:
        text = lambda name: yaml.dump(ci["jobs"][name])  # noqa: E731
        assert "test_plugin_entry_roundtrip.py" in text("plugin")
        assert "test_repohooks_commit_hooks.py" in text(
            "git-old"
        ) and "test_hook_matrix.py" in text("git-old")
        assert "test_shim.py" in text("macos-sh") and "socket path length" in text("macos-sh")
        assert "includes the signing scenarios" in " ".join(text("e2e-contract").split())

    def test_git_old_runs_the_marker_in_a_bookworm_container(self, ci: dict) -> None:
        job = ci["jobs"]["git-old"]
        assert job["container"] == "debian:bookworm"
        assert "pytest -m gitold" in " ".join(s.get("run", "") for s in steps(job))

    def test_macos_sh_uses_the_system_git_and_sh(self, ci: dict) -> None:
        job = ci["jobs"]["macos-sh"]
        assert job["runs-on"] == "macos-latest"
        assert "/usr/bin/git" in yaml.dump(job) and "test_carter_guard.py" in yaml.dump(job)

    def test_install_smoke_keeps_the_floor_and_runs_the_dry_run(self, ci: dict) -> None:
        job = ci["jobs"]["install-smoke"]
        assert any(m.get("opencode") == "2.1.0" for m in job["strategy"]["matrix"]["include"])
        assert "carter guard install --dry-run" in yaml.dump(job)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
class TestEveryWorkflow:
    def test_actions_are_pinned_by_sha(self, path: Path) -> None:
        for job in load(path)["jobs"].values():
            for step in steps(job):
                if "uses" in step and not step["uses"].startswith("./"):
                    ref = step["uses"]
                    text = next(
                        ln for ln in path.read_text().splitlines() if ref in ln and "uses:" in ln
                    )
                    assert SHA_PIN.match(text.split("uses:", 1)[1].strip()), text

    def test_read_only_permissions_and_no_pull_request_target(self, path: Path) -> None:
        doc = load(path)
        raw = path.read_text()
        assert "pull_request_target" not in raw
        top = doc.get("permissions")
        if path == CI:
            assert top == {"contents": "read"}
        elif path.name != "release.yml":  # the release workflow publishes: it asks for more
            assert top is None or set(top.values()) <= {"read", "none"}

    def test_every_repo_path_named_in_a_run_command_exists(self, path: Path) -> None:
        missing = []
        for name, job in load(path)["jobs"].items():
            for step in steps(job):
                for word in PATH_WORDS.findall(step.get("run", "")):
                    word = word.rstrip(".,;:)\"'")
                    if "${" in word or "$" in word:
                        continue
                    if not glob.glob(str(ROOT / word)):
                        missing.append((name, word))
        assert missing == []


def test_actionlint_when_installed() -> None:
    tool = shutil.which("actionlint")
    if tool is None:
        pytest.skip("actionlint is not installed")
    done = subprocess.run([tool, str(CI)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout
