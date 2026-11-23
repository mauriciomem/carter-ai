"""``carter ci install review``: write the review-only workflow.

Click-free, so it is testable. It writes ``.github/workflows/carter-review.yml`` under the
repository that contains the working directory, and nothing else. The caller has already
refused agent shells and (for a real write) a missing TTY: an agent-written workflow is
executable config.

Never overwrites an edited file: the file starts with a hash header over the rest, and only a
file whose body still matches its header (or ``--force``) is replaced. Symlinks anywhere on the
path are refused (a planted link must not redirect the write).
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from carter.ci import ENVIRONMENT, SECRET, WORKFLOW_REL
from carter.ci import template as tpl

Echo = Callable[[str], None]


class InstallError(Exception):
    """The workflow was not written; the message says why and what to do."""


def repo_root(start: Path) -> Path:
    """The directory holding ``.git`` (a file or a directory) at or above ``start``."""
    here = start.resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise InstallError("not inside a git repository: run this from your repository")


def _refuse_links(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise InstallError(f"{current.relative_to(root)} is a symlink: not written through")


def _advice(echo: Echo, comment: bool) -> None:
    version = tpl.render().split("carter-ai==", 1)[1].split('"', 1)[0]
    if re.search(r"dev|rc|a\d|b\d|\+", version):
        echo("")
        echo(f"  Note: the workflow pins carter-ai=={version} (a pre-release)")
        echo("  It may not be on PyPI: pin a release before you push.")
    echo("")
    echo("What to do next (Carter changes nothing on GitHub):")
    echo("  1. Review the file, commit it and push it yourself.")
    echo(f"  2. On GitHub create the environment `{ENVIRONMENT}`")
    echo(f"     and add the secret `{SECRET}` to it (a throwaway key).")
    echo("     Optional variables: CARTER_CI_MODEL (provider/model),")
    echo("     CARTER_CI_KEY_ENV (default ANTHROPIC_API_KEY).")
    echo("  3. In CODEOWNERS add `/.github/workflows/ @your-team`")
    echo("     and require review (it is executable config).")
    echo("  Fork pull requests are skipped (`contents: read` only).")
    if comment:
        echo("")
        echo("  --comment WIDENS the scope: a second job gets")
        echo("  `pull-requests: write` (only that) to post the review.")


def install_review(cwd: Path, *, comment: bool, dry_run: bool, force: bool, echo: Echo) -> int:
    """Render and write the workflow; returns 0 or raises ``InstallError``."""
    text = tpl.render(comment=comment)
    if dry_run:
        echo(text.rstrip("\n"))
        echo(f"\n(dry run: nothing written; would write {WORKFLOW_REL})")
        return 0
    root = repo_root(cwd)
    target = root / WORKFLOW_REL
    _refuse_links(root, target)
    existing = target.read_text(encoding="utf-8") if target.is_file() else None
    if existing == text:
        echo(f"{WORKFLOW_REL} is up to date; nothing changed.")  # shown as one ✓ line
        _advice(echo, comment)
        return 0
    if existing is not None and not force and not tpl.is_unedited(existing):
        raise InstallError(
            f"{Path(WORKFLOW_REL).name} was edited: compare with --dry-run or use --force"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    _refuse_links(root, target)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".carter-review.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    verb = "updated" if existing is not None else "wrote"
    echo(f"{verb} {WORKFLOW_REL}" + (" (with the comment opt-in)" if comment else ""))
    _advice(echo, comment)
    return 0
