# ruff: noqa: E501
"""The structural checker: each bad workflow fails for the right reason.

The good workflow is the rendered template (both variants). Bad ones are single mutations of it,
so each fails for exactly the rule it breaks, plus a few classic real-world fixtures on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from carter.ci import check, template
from ci.helpers import FIXTURES, find_actionlint, run_actionlint


def rules(text: str) -> set[str]:
    return {f.rule for f in check.check(text)}


def mutate(text: str, old: str, new: str) -> str:
    assert old in text, f"the mutation anchor is not in the template: {old!r}"
    return text.replace(old, new, 1)


class TestGood:
    def test_the_rendered_template_keeps_every_rule(self, rendered: str) -> None:
        assert check.check(rendered) == []

    def test_there_is_no_write_permission_in_the_plain_template(self) -> None:
        plain = template.render(comment=False)
        assert not re.search(r"\bwrite\b", re.sub(r"(?m)^\s*#.*$", "", plain))

    def test_the_comment_variant_has_exactly_one_write_and_it_is_pull_requests(self) -> None:
        text = re.sub(r"(?m)^\s*#.*$", "", template.render(comment=True))
        assert re.findall(r"^\s*([\w-]+): write\s*$", text, re.M) == ["pull-requests"]

    def test_the_good_fixture_passes(self) -> None:
        assert check.check_file(FIXTURES / "good-minimal.yml") == []


# (name, anchor, replacement, expected rules); anchors are in both variants unless noted
PLAIN = [
    ("target", "on:\n  pull_request:\n", "on:\n  pull_request_target:\n", {"CI001"}),
    ("push-too", "on:\n  pull_request:\n", "on:\n  pull_request:\n  push:\n", {"CI001"}),
    (
        "workflow-run",
        "on:\n  pull_request:\n",
        "on:\n  workflow_run:\n    workflows: [x]\n",
        {"CI001"},
    ),
    (
        "schedule",
        "on:\n  pull_request:\n",
        "on:\n  pull_request:\n  schedule:\n    - cron: '1 1 * * *'\n",
        {"CI001"},
    ),
    (
        "list-form-target",
        "on:\n  pull_request:\n",
        "on: [pull_request, pull_request_target]\n",
        {"CI001"},
    ),
    (
        "workflow-write",
        "permissions:\n  contents: read\n\nconcurrency",
        "permissions:\n  contents: write\n\nconcurrency",
        {"CI002", "CI004"},
    ),
    (
        "workflow-wider",
        "permissions:\n  contents: read\n\nconcurrency",
        "permissions:\n  contents: read\n  issues: read\n\nconcurrency",
        {"CI002"},
    ),
    (
        "workflow-write-all",
        "permissions:\n  contents: read\n\nconcurrency",
        "permissions: write-all\n\nconcurrency",
        {"CI002", "CI004"},
    ),
    (
        "workflow-none-given",
        "permissions:\n  contents: read\n\nconcurrency",
        "concurrency",
        {"CI002"},
    ),
    (
        "job-write",
        "    permissions:\n      contents: read\n    outputs",
        "    permissions:\n      contents: write\n    outputs",
        {"CI004"},
    ),
    (
        "job-pr-write",
        "    permissions:\n      contents: read\n    outputs",
        "    permissions:\n      pull-requests: write\n    outputs",
        {"CI004"},
    ),
    (
        "job-write-all",
        "    permissions:\n      contents: read\n    outputs",
        "    permissions: write-all\n    outputs",
        {"CI004"},
    ),
    (
        "job-no-permissions",
        "    permissions:\n      contents: read\n    outputs",
        "    outputs",
        {"CI003"},
    ),
    (
        "unpinned-tag",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
        "actions/checkout@v7",
        {"CI005"},
    ),
    (
        "unpinned-branch",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
        "actions/checkout@main",
        {"CI005"},
    ),
    (
        "short-sha",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
        "actions/checkout@3d3c42e # v7.0.1",
        {"CI005"},
    ),
    (
        "no-version-comment",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        {"CI005"},
    ),
    (
        "local-action",
        "      - name: Set up uv\n",
        "      - uses: ./.github/actions/mine\n      - name: Set up uv\n",
        {"CI005"},
    ),
    (
        "docker-action",
        "      - name: Set up uv\n",
        "      - uses: docker://alpine:3\n      - name: Set up uv\n",
        {"CI005"},
    ),
    (
        "reusable-workflow",
        "    runs-on: ubuntu-latest\n    timeout-minutes: 15\n",
        "    uses: o/r/.github/workflows/x.yml@3d3c42e5aac5ba805825da76410c181273ba90b1\n    timeout-minutes: 15\n",
        {"CI005", "CI013"},
    ),
    ("no-timeout", "    timeout-minutes: 15\n", "", {"CI006"}),
    ("long-timeout", "timeout-minutes: 15", "timeout-minutes: 600", {"CI006"}),
    ("string-timeout", "timeout-minutes: 15", "timeout-minutes: '15'", {"CI006"}),
    (
        "no-concurrency",
        "concurrency:\n  group: carter-review-${{ github.event.pull_request.number }}\n  cancel-in-progress: true\n\n",
        "",
        {"CI007"},
    ),
    ("no-cancel", "cancel-in-progress: true", "cancel-in-progress: false", {"CI007"}),
    ("persist-true", "persist-credentials: false", "persist-credentials: true", {"CI008"}),
    ("persist-missing", "          persist-credentials: false\n", "", {"CI008"}),
    (
        "workflow-env-secret",
        "permissions:\n  contents: read\n\nconcurrency",
        "permissions:\n  contents: read\n\nenv:\n  K: ${{ secrets.LLM_API_KEY }}\n\nconcurrency",
        {"CI009"},
    ),
    (
        "job-env-secret",
        "    timeout-minutes: 15\n",
        "    timeout-minutes: 15\n    env:\n      K: ${{ secrets.LLM_API_KEY }}\n",
        {"CI009"},
    ),
    (
        "other-secret",
        "          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}\n          CARTER_IDENTITY_MODE",
        "          LLM_API_KEY: ${{ secrets.OTHER_KEY }}\n          CARTER_IDENTITY_MODE",
        {"CI009"},
    ),
    (
        "secret-in-with",
        '          node-version: "lts/*"\n',
        '          node-version: "lts/*"\n          token: ${{ secrets.LLM_API_KEY }}\n',
        {"CI009"},
    ),
    (
        "secret-in-run",
        '            echo "run=true" >> "$GITHUB_OUTPUT"\n',
        '            echo "run=true" >> "$GITHUB_OUTPUT"\n            echo \'${{ secrets.LLM_API_KEY }}\'\n',
        {"CI009", "CI010"},
    ),
    (
        "secrets-inherit",
        "    timeout-minutes: 15\n",
        "    timeout-minutes: 15\n    secrets: inherit\n",
        {"CI009"},
    ),
    (
        "whole-secrets-context",
        "          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}\n          CARTER_IDENTITY_MODE",
        "          LLM_API_KEY: ${{ toJSON(secrets) }}\n          CARTER_IDENTITY_MODE",
        {"CI009"},
    ),
    (
        "injection-title",
        "        run: carter ci review\n",
        '        run: echo "${{ github.event.pull_request.title }}"\n',
        {"CI010"},
    ),
    (
        "injection-head-ref",
        "        run: carter ci review\n",
        "        run: git checkout ${{ github.head_ref }}\n",
        {"CI010"},
    ),
    (
        "injection-even-for-a-number",
        "        run: carter ci review\n",
        "        run: echo ${{ github.event.pull_request.number }}\n",
        {"CI010"},
    ),
    ("no-environment", "    environment: carter-review\n", "", {"CI011"}),
    (
        "no-fork-guard",
        "    if: github.event.pull_request.head.repo.full_name == github.repository\n",
        "",
        {"CI012"},
    ),
    (
        "wrong-fork-guard",
        "github.event.pull_request.head.repo.full_name == github.repository",
        "github.actor != 'dependabot[bot]'",
        {"CI012"},
    ),
    ("self-hosted", "runs-on: ubuntu-latest", "runs-on: self-hosted", {"CI013"}),
    ("self-hosted-list", "runs-on: ubuntu-latest", "runs-on: [self-hosted, linux]", {"CI013"}),
    ("matrix-runner", "runs-on: ubuntu-latest", "runs-on: ${{ matrix.os }}", {"CI013"}),
]
COMMENT = [
    (
        "comment-extra-scope",
        "      pull-requests: write\n",
        "      pull-requests: write\n      contents: write\n",
        {"CI004"},
    ),
    ("comment-other-scope", "      pull-requests: write\n", "      issues: write\n", {"CI004"}),
    (
        "comment-with-checkout",
        "      - name: Download the review text\n",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n        with:\n          persist-credentials: false\n      - name: Download the review text\n",
        {"CI004"},
    ),
    (
        "comment-no-fork-guard",
        "    if: github.event.pull_request.head.repo.full_name == github.repository && needs.review.outputs.reviewed == 'true'\n",
        "    if: needs.review.outputs.reviewed == 'true'\n",
        {"CI012"},
    ),
    ("comment-no-timeout", "    timeout-minutes: 5\n", "", {"CI006"}),
    (
        "comment-reads-the-secret",
        "          GH_TOKEN: ${{ github.token }}\n",
        "          GH_TOKEN: ${{ github.token }}\n          K: ${{ secrets.LLM_API_KEY }}\n",
        {"CI011"},
    ),
    ("another-job-with-write", "  comment:\n    name:", "  notify:\n    name:", {"CI004"}),
]


@pytest.mark.parametrize(("name", "old", "new", "expected"), PLAIN, ids=[c[0] for c in PLAIN])
@pytest.mark.parametrize("variant", [False, True], ids=["plain", "comment"])
def test_each_mutation_fails_for_exactly_its_rule(
    name: str, old: str, new: str, expected: set[str], variant: bool
) -> None:
    del name
    text = mutate(template.render(comment=variant), old, new)
    assert rules(text) == expected


@pytest.mark.parametrize(("name", "old", "new", "expected"), COMMENT, ids=[c[0] for c in COMMENT])
def test_the_comment_job_is_held_to_its_narrow_exception(
    name: str, old: str, new: str, expected: set[str]
) -> None:
    del name
    text = mutate(template.render(comment=True), old, new)
    assert rules(text) == expected


class TestRealWorldFixtures:
    @pytest.mark.parametrize("path", sorted(FIXTURES.glob("bad-*.yml")), ids=lambda p: p.stem)
    def test_each_bad_fixture_fails_at_least_for_the_rules_it_names(self, path: Path) -> None:
        header = path.read_text().splitlines()[0]
        wanted = set(re.findall(r"CI\d{3}", header))
        assert wanted, f"{path.name} has no `# expect:` header"
        assert wanted <= rules(path.read_text())


class TestNotAWorkflow:
    @pytest.mark.parametrize("text", ["", "- a\n- b\n", "just: text\n", "jobs: []\n", ": : :\n\t["])
    def test_garbage_is_ci000(self, text: str) -> None:
        assert rules(text) == {"CI000"}

    def test_findings_render_with_rule_and_place(self) -> None:
        text = mutate(template.render(), "timeout-minutes: 15", "timeout-minutes: 99")
        (finding,) = check.check(text)
        assert finding.render().startswith("CI006 jobs.review:")


class TestDuplicateKeys:
    def test_a_second_permissions_key_is_not_silently_the_last_one(self) -> None:
        text = mutate(
            template.render(), "permissions:\n  contents: read\n\nconcurrency",
            "permissions:\n  contents: write\npermissions:\n  contents: read\n\nconcurrency",
        )  # fmt: skip
        assert rules(text) == {"CI000"}

    def test_a_duplicate_job_key_is_refused_too(self) -> None:
        assert rules(template.render() + "\n  review:\n    runs-on: ubuntu-latest\n") == {"CI000"}


class TestOneJobCannotHideBehindAnother:
    def test_a_second_unsafe_job_is_found_even_when_the_first_is_clean(self) -> None:
        extra = (
            "\n  other:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n"
            "    permissions:\n      contents: read\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
        )
        assert rules(template.render() + extra) == {"CI005", "CI008"}


@pytest.mark.skipif(find_actionlint() is None, reason="actionlint is not installed here")
class TestActionlintAgrees:
    def test_both_variants_are_clean(self, rendered: str, tmp_path: Path) -> None:
        path = tmp_path / "carter-review.yml"
        path.write_text(rendered)
        done = run_actionlint(find_actionlint() or "", path)
        assert done.returncode == 0, done.stdout + done.stderr

    def test_actionlint_still_flags_what_the_checker_does_not_cover(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yml"
        path.write_text(
            mutate(template.render(), "steps.gate.outputs.run", "steps.nope.outputs.run")
        )
        assert run_actionlint(find_actionlint() or "", path).returncode != 0
