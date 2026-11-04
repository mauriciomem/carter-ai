"""``carter ci``: install and run the review-only workflow (plan 008 freeze C1, C12).

``install review`` is human-only (agent shells refused, a TTY needed to write). ``review`` is
what the workflow runs. ``check`` validates any workflow against the App C.10 rules.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from carter.cliguard import guarded
from carter.terminal import require_human_terminal


@click.group("ci")
def ci() -> None:
    """Review-only CI (context E): no commits, `contents: read`."""


@ci.command("install")
@click.argument("what", type=click.Choice(["review"]))
@click.option("--comment", is_flag=True, help="Opt in to a PR comment (adds pull-requests: write).")
@click.option("--dry-run", is_flag=True, help="Print the workflow; write nothing.")
@click.option("--force", is_flag=True, help="Replace a file that was edited by hand.")
def install_cmd(what: str, comment: bool, dry_run: bool, force: bool) -> None:
    """Write .github/workflows/carter-review.yml (your own terminal only).

    An agent-written workflow is executable config, so this refuses in an agent shell and,
    unless --dry-run, without a terminal. It never overwrites a file you edited."""

    from carter.ci import install

    def run() -> int:
        require_human_terminal("carter ci install", need_tty=not dry_run)
        try:
            return install.install_review(
                Path.cwd(), comment=comment, dry_run=dry_run, force=force, echo=click.echo
            )
        except install.InstallError as exc:
            raise click.ClickException(str(exc)) from exc

    guarded(run)


@ci.command("review")
@click.option("--comment", is_flag=True, help="Also print the review body (for a comment step).")
def review_cmd(comment: bool) -> None:
    """Review the pull request read-only and write the summary (run by the workflow)."""
    from carter.ci import review

    outcome = review.run_review(os.environ, Path.cwd(), out=click.echo)
    if comment and outcome.text:
        click.echo(outcome.text)
    raise SystemExit(outcome.code)


@ci.command("check")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def check_cmd(path: Path) -> None:
    """Check a workflow file against the review-only rules (App C.10)."""
    from carter.ci import check as checker

    findings = checker.check_file(path)
    for finding in findings:
        click.echo(finding.render())
    if findings:
        raise SystemExit(1)
    click.echo("ok: the workflow keeps every review-only rule")
