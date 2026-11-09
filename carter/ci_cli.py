"""``carter ci``: install and run the review-only workflow.

``install review`` is human-only (agent shells refused, a TTY needed to write). ``review`` is
what the workflow runs. ``check`` validates any workflow against the workflow rules.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from carter import ui
from carter.cliguard import guarded, verbose_option
from carter.terminal import require_human_terminal


@click.group("ci")
def ci() -> None:
    """Review-only CI workflow: no commits, read-only."""


def _say(line: str) -> None:
    """The installer's lines: the result and any pre-release note show, the steps are ``-v``."""
    text = line.strip()
    if text.startswith(("wrote ", "updated ")) or text.endswith("nothing changed."):
        ui.ok(text)
    elif text.startswith("Note:"):
        ui.warn(text.removeprefix("Note:").strip())
    elif text:
        ui.detail(text)


@ci.command("install")
@click.argument("what", type=click.Choice(["review"]))
@click.option("--comment", is_flag=True, help="Also post the review as a PR comment.")
@click.option("--dry-run", is_flag=True, help="Print the workflow; write nothing.")
@click.option("--force", is_flag=True, help="Replace a hand-edited file.")
@verbose_option
def install_cmd(what: str, comment: bool, dry_run: bool, force: bool) -> None:
    """Write the review workflow."""

    from carter.ci import install

    def run() -> int:
        require_human_terminal("carter ci install", need_tty=not dry_run)
        try:
            code = install.install_review(
                Path.cwd(), comment=comment, dry_run=dry_run, force=force,
                echo=click.echo if dry_run else _say,
            )  # fmt: skip
        except install.InstallError as exc:
            raise click.ClickException(str(exc)) from exc
        if not dry_run:
            ui.info("→ next: commit and push it yourself, then add the provider key secret (-v)")
        return code

    guarded(run)


@ci.command("review")
@click.option("--comment", is_flag=True, help="Also print the review body.")
def review_cmd(comment: bool) -> None:
    """Review the pull request read-only (run by the workflow)."""
    from carter.ci import review

    outcome = review.run_review(os.environ, Path.cwd(), out=click.echo)
    if comment and outcome.text:
        click.echo(outcome.text)
    raise SystemExit(outcome.code)


@ci.command("check")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def check_cmd(path: Path) -> None:
    """Check a workflow against the review-only rules."""
    from carter.ci import check as checker

    findings = checker.check_file(path)
    for finding in findings:
        ui.warn(finding.render())
    if findings:
        ui.fail(f"{len(findings)} rule(s) broken")
        raise SystemExit(1)
    ui.ok("the workflow keeps every review-only rule")
