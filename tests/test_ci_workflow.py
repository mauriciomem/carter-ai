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
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
CI = ROOT / ".github" / "workflows" / "ci.yml"
E2E = ROOT / ".github" / "workflows" / "e2e.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}(\s+#.*)?$")
PATH_WORDS = re.compile(r"(?<![\w$/{.-])((?:tests|evals|carter|scripts)/[\w./*-]+)")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def steps(job: dict):
    yield from job.get("steps", [])


@pytest.fixture(scope="module")
def ci() -> dict:
    return load(CI)


@pytest.fixture(scope="module")
def e2e() -> dict:
    return load(E2E)


class TestJobs:
    @pytest.mark.parametrize(
        "name",
        [
            "lint",
            "test",
            "plugin",
            "gate-budget",
            "git-old",
            "macos-sh",
            "install-smoke",
            "identity-ssh",
            "lifecycle",
            "ci-template",
            "dist-check",
        ],
    )
    def test_the_job_exists(self, ci: dict, name: str) -> None:
        assert name in ci["jobs"]

    def test_dist_check_runs_the_release_checks_on_every_change_without_uploading(
        self, ci: dict
    ) -> None:
        job = ci["jobs"]["dist-check"]
        assert job["permissions"] == {"contents": "read"} and "if" not in job
        text = yaml.dump(job)
        assert "uv build" in text and "bash scripts/check-dist.sh" in text
        assert "upload-artifact" not in text and "id-token" not in text and "secrets." not in text
        checkout = next(s for s in steps(job) if "actions/checkout" in s.get("uses", ""))
        assert checkout["with"]["fetch-depth"] == 0  # hatch-vcs needs the history
        assert job["env"]["UV_NO_CACHE"] == "1"
        assert "dist-check" not in yaml.dump(
            load(RELEASE)["jobs"]["release"]
        )  # one script, two jobs
        assert "scripts/check-dist.sh" in yaml.dump(load(RELEASE)["jobs"]["build"])

    def test_lifecycle_runs_its_directory_on_both_systems_without_skips(self, ci: dict) -> None:
        job = ci["jobs"]["lifecycle"]
        assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "macos-latest"}
        assert job["strategy"]["fail-fast"] is False and not job.get("continue-on-error")
        runs = " ".join(s.get("run", "") for s in steps(job))
        assert "pytest tests/lifecycle" in runs and " -m " not in runs and "--deselect" not in runs
        sources = (ROOT / "tests" / "lifecycle").glob("*.py")
        assert not [p.name for p in sources if re.search(r"\bskip(if)?\b", p.read_text())]

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
        assert "tests/test_startup.py" in text  # the `carter --help` budget rides on this job
        assert not job.get("continue-on-error")

    def test_e2e_is_its_own_manual_workflow_and_latest_may_fail(self, ci: dict, e2e: dict) -> None:
        assert "e2e-contract" not in ci["jobs"]  # a skipped matrix job shows its raw title
        assert (e2e.get("on") or e2e.get(True)) == {"workflow_dispatch": None}
        assert "workflow_dispatch" not in (ci.get("on") or ci.get(True))
        job = e2e["jobs"]["contract"]
        assert "if" not in job
        text = yaml.dump(job)
        assert "tests/e2e/run.sh" in text and "unshare -rn" in text
        entries = {m["label"]: m for m in job["strategy"]["matrix"]["include"]}
        assert (
            entries["tested"]["experimental"] is False and entries["tested"]["version"] == "2.1.4"
        )
        assert entries["latest"]["experimental"] is True

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

    def test_every_job_that_starts_agents_has_the_if_always_cleanup_check(
        self, ci: dict, e2e: dict
    ) -> None:
        for name, job in (
            ("identity-ssh", ci["jobs"]["identity-ssh"]),
            ("contract", e2e["jobs"]["contract"]),
        ):
            last = job["steps"][-1]
            assert last.get("if") == "always()" and "ssh-agent" in last["run"], name

    def test_the_signing_checks_are_in_the_existing_jobs(self, ci: dict, e2e: dict) -> None:
        text = lambda name: yaml.dump(ci["jobs"][name])  # noqa: E731
        assert "test_plugin_entry_roundtrip.py" in text("plugin")
        assert "test_repohooks_commit_hooks.py" in text(
            "git-old"
        ) and "test_hook_matrix.py" in text("git-old")
        assert "test_shim.py" in text("macos-sh") and "socket path length" in text("macos-sh")
        assert "tests/e2e/run.sh" in yaml.dump(e2e["jobs"]["contract"])

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


class TestRelease:
    """The release workflow only tags: no commit, no push of a branch, notes on GitHub."""

    @pytest.fixture(scope="class")
    def release(self) -> dict:
        return load(RELEASE)

    def test_semantic_release_runs_tag_only(self, release: dict) -> None:
        psr = [
            s
            for s in steps(release["jobs"]["release"])
            if s.get("uses", "").startswith("python-semantic-release/python-semantic-release@")
        ]
        assert len(psr) == 1
        assert psr[0]["with"]["commit"] == "false"
        assert psr[0]["with"]["changelog"] == "false"
        assert "push" not in psr[0]["with"] and psr[0]["with"].get("tag", "true") != "false"

    def test_no_step_commits_or_pushes_by_hand(self, release: dict) -> None:
        runs = " ".join(s.get("run", "") for s in steps(release["jobs"]["release"]))
        assert not re.search(r"git\s+(push|commit|add)", runs)

    def test_only_the_release_job_can_write(self, release: dict) -> None:
        jobs = release["jobs"]
        assert jobs["release"]["permissions"] == {"contents": "write"}
        others = {name: job["permissions"] for name, job in jobs.items() if name != "release"}
        assert all("contents" not in p or p["contents"] == "read" for p in others.values())
        for path in WORKFLOWS:
            if path != RELEASE:
                assert "write" not in yaml.dump(load(path).get("permissions", {})), path.name

    def test_there_is_no_changelog_file_and_the_url_points_at_the_releases(self) -> None:
        assert not (ROOT / "CHANGELOG.md").exists()
        urls = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["urls"]
        assert urls["Changelog"] == "https://github.com/mauriciomem/carter-ai/releases"


class TestPublish:
    """release.yml is one workflow: tag, build once, check, TestPyPI, then PyPI."""

    JOBS = ["release", "build", "publish-testpypi", "publish-pypi"]

    @pytest.fixture(scope="class")
    def release(self) -> dict:
        return load(RELEASE)

    @staticmethod
    def _environment(job: dict) -> str:
        env = job["environment"]
        return env if isinstance(env, str) else env["name"]

    def test_the_job_graph_is_a_chain_and_the_build_only_runs_for_a_release(
        self, release: dict
    ) -> None:
        jobs = release["jobs"]
        assert list(jobs) == self.JOBS
        assert "needs" not in jobs["release"]
        assert jobs["build"]["needs"] == "release"
        assert jobs["publish-testpypi"]["needs"] == "build"
        assert jobs["publish-pypi"]["needs"] == "publish-testpypi"  # TestPyPI first, then PyPI
        assert jobs["build"]["if"] == "needs.release.outputs.released == 'true'"
        assert "if" not in jobs["publish-testpypi"] and "if" not in jobs["publish-pypi"]

    def test_the_release_job_exposes_what_the_build_needs(self, release: dict) -> None:
        job = release["jobs"]["release"]
        psr = next(s for s in steps(job) if "python-semantic-release" in s.get("uses", ""))
        assert psr["id"] == "psr"
        assert job["outputs"] == {
            name: "${{ steps.psr.outputs." + name + " }}" for name in ("released", "tag", "version")
        }
        assert "uses" in psr and psr["with"]["github_token"] == "${{ secrets.GITHUB_TOKEN }}"

    def test_permissions_are_empty_at_the_top_and_minimal_per_job(self, release: dict) -> None:
        assert release["permissions"] == {}
        jobs = release["jobs"]
        assert {n: j["permissions"] for n, j in jobs.items()} == {
            "release": {"contents": "write"},
            "build": {"contents": "read"},
            "publish-testpypi": {"id-token": "write"},
            "publish-pypi": {"id-token": "write"},
        }
        assert release["concurrency"]["cancel-in-progress"] is False

    def test_the_publish_jobs_use_the_trusted_publisher_environments(self, release: dict) -> None:
        jobs = release["jobs"]
        assert self._environment(jobs["publish-testpypi"]) == "testpypi"
        assert self._environment(jobs["publish-pypi"]) == "pypi"
        assert "environment" not in jobs["release"] and "environment" not in jobs["build"]
        assert RELEASE.name == "release.yml"  # the file name the publisher entries expect

    def test_the_publish_jobs_run_no_repository_code_and_hold_no_secret(
        self, release: dict
    ) -> None:
        for name in ("publish-testpypi", "publish-pypi"):
            job = release["jobs"][name]
            uses = [s["uses"].split("@")[0] for s in steps(job)]
            assert uses == ["actions/download-artifact", "pypa/gh-action-pypi-publish"], name
            assert not [s for s in steps(job) if "run" in s], name  # no checkout, no scripts
            publish = job["steps"][-1].get("with", {})
            assert not {"password", "user", "attestations"} & set(publish), name
        assert "secrets." not in RELEASE.read_text().replace("secrets.GITHUB_TOKEN", "")

    def test_each_index_gets_its_own_url_and_only_testpypi_skips_existing_files(
        self, release: dict
    ) -> None:
        test = release["jobs"]["publish-testpypi"]["steps"][-1]["with"]
        prod = release["jobs"]["publish-pypi"]["steps"][-1].get("with", {})
        assert test["repository-url"] == "https://test.pypi.org/legacy/"
        assert test["skip-existing"] is True
        assert "repository-url" not in prod and "skip-existing" not in prod  # PyPI is the default

    def test_the_publish_action_is_pinned_by_sha(self, release: dict) -> None:
        text = RELEASE.read_text()
        pins = re.findall(
            r"uses: pypa/gh-action-pypi-publish@([0-9a-f]{40}) # v\d+\.\d+\.\d+", text
        )
        assert len(pins) == 2 and pins[0] == pins[1]

    def test_the_build_runs_the_checks_before_it_uploads(self, release: dict) -> None:
        job = release["jobs"]["build"]
        runs = [s.get("run", "") for s in steps(job)]
        index = {
            key: next(i for i, r in enumerate(runs) if key in r)
            for key in ("uv build", "scripts/check-dist.sh")
        }
        upload = next(i for i, s in enumerate(steps(job)) if "upload-artifact" in s.get("uses", ""))
        assert index["uv build"] < index["scripts/check-dist.sh"] < upload
        check = next(s for s in steps(job) if "check-dist.sh" in s.get("run", ""))
        assert check["env"]["VERSION"] == "${{ needs.release.outputs.version }}"
        assert check["run"] == 'bash scripts/check-dist.sh "$VERSION"'

    def test_the_dist_check_script_does_what_the_release_promises(self) -> None:
        script = ROOT / "scripts" / "check-dist.sh"
        text = script.read_text()
        assert text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text
        assert re.search(r"twine==\d+(\.\d+)* twine check --strict", text)
        assert re.search(r"check-wheel-contents==\d+(\.\d+)* check-wheel-contents", text)
        assert "dist/*.whl" in text and "dist/*.tar.gz" in text  # both files are installed
        assert 'cd "$work"' in text  # away from the checkout
        assert '"$venv/bin/carter" --version' in text and '"$expected"' in text  # the tag
        assert "carter.resources" in text and "_data" in text  # data from the package
        assert "$HOME" not in text and "carter install" not in text  # nothing touches the home
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0

    def test_the_build_checks_out_the_tag_with_full_history_and_uploads_one_artifact(
        self, release: dict
    ) -> None:
        jobs = release["jobs"]
        build = jobs["build"]
        checkout = next(s for s in steps(build) if "actions/checkout" in s.get("uses", ""))
        assert checkout["with"]["ref"] == "${{ needs.release.outputs.tag }}"
        assert checkout["with"]["fetch-depth"] == 0  # hatch-vcs derives the version from the tag
        up = next(s for s in steps(build) if "upload-artifact" in s.get("uses", ""))
        assert up["with"]["name"] == "dist" and up["with"]["if-no-files-found"] == "error"
        for name in ("publish-testpypi", "publish-pypi"):
            down = jobs[name]["steps"][0]
            assert "download-artifact" in down["uses"] and down["with"]["name"] == "dist"
        assert sum("upload-artifact" in s.get("uses", "") for s in steps(build)) == 1

    def test_every_checkout_drops_its_credentials(self, release: dict) -> None:
        found = [
            s
            for job in release["jobs"].values()
            for s in steps(job)
            if "actions/checkout" in s.get("uses", "")
        ]
        assert len(found) == 2
        assert all(s["with"]["persist-credentials"] is False for s in found)

    def test_nothing_is_cached_in_a_release_job(self, release: dict) -> None:
        text = RELEASE.read_text()
        assert "actions/cache" not in text and "cache:" not in text.replace("enable-cache", "")
        uv = [
            s
            for job in release["jobs"].values()
            for s in steps(job)
            if "setup-uv" in s.get("uses", "")
        ]
        assert uv and all(s["with"]["enable-cache"] is False for s in uv)
        assert release["jobs"]["build"]["env"]["UV_NO_CACHE"] == "1"

    def test_no_run_script_interpolates_an_expression(self, release: dict) -> None:
        for name, job in release["jobs"].items():
            for step in steps(job):
                assert "${{" not in step.get("run", ""), (name, step.get("name"))

    def test_every_action_has_a_version_comment(self) -> None:
        lines = [ln for ln in RELEASE.read_text().splitlines() if "uses:" in ln]
        assert lines and all(re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", ln) for ln in lines)

    def test_the_build_backend_is_pinned_exactly(self) -> None:
        requires = tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"]["requires"]
        assert requires and all(re.fullmatch(r"[\w.-]+==\d+(\.\d+)*", r) for r in requires)


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
        else:  # release.yml too: its one job asks for `contents: write` itself
            assert top is None or set(top.values()) <= {"read", "none"}

    def test_secrets_are_only_given_to_the_step_that_needs_them(self, path: Path) -> None:
        doc = load(path)
        assert "secrets." not in yaml.dump(doc.get("env", {})), "workflow-level env"
        for name, job in doc["jobs"].items():
            assert "secrets." not in yaml.dump(job.get("env", {})), f"job-level env of {name}"
            assert "secrets." not in yaml.dump(job.get("container", {})), name

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


STALE_TERMS = re.compile(r"\bA\+|\bslice\b|\bRFC\b|\bplan 0|\brevision [0-9]\b|\b[12][abc]\b", re.I)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_job_and_step_names_are_short_current_and_expand_on_their_own(path: Path) -> None:
    """A matrix job skipped by ``if:`` shows its raw ``${{ matrix.x }}`` title, so only
    always-running jobs may put a matrix value in a name."""
    doc = load(path)
    assert doc["name"] and len(doc["name"]) <= 20
    for job_id, job in doc["jobs"].items():
        name = job["name"]
        shown = re.sub(r"\$\{\{.*?\}\}", "x" * 8, name)  # a matrix value is short
        assert len(shown) <= 60 and not STALE_TERMS.search(name), (job_id, name)
        if "${{" in name:
            assert "if" not in job and "matrix" in job.get("strategy", {}), (job_id, name)
        for step in steps(job):
            label = step.get("name", "")
            assert len(label) <= 60 and not STALE_TERMS.search(label), (job_id, label)
            assert "${{" not in label, (job_id, label)


def test_every_carter_module_a_run_command_imports_exists() -> None:
    """A smoke step that imports a module nobody ships fails only on the runner."""
    import importlib.util

    names = set()
    for path in WORKFLOWS:
        for job in load(path)["jobs"].values():
            for step in steps(job):
                for line in step.get("run", "").splitlines():
                    if re.match(r"\s*(import|from)\s", line):
                        names |= set(re.findall(r"\bcarter(?:\.\w+)+", line))
    assert names  # the install-smoke step imports the broker core
    assert [n for n in sorted(names) if importlib.util.find_spec(n) is None] == []


def test_actionlint_when_installed() -> None:
    tool = shutil.which("actionlint")
    if tool is None:
        pytest.skip("actionlint is not installed")
    done = subprocess.run([tool, str(CI)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout
