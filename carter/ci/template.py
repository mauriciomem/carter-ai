# ruff: noqa: E501  (the YAML pieces below are one-line workflow expressions)
"""Render the review-only workflow.

The template file is ``templates/ci/carter-review.yml.tmpl`` (bundled like the other
templates). Placeholders are plain ``__NAME__`` tokens: Jinja would fight ``${{ }}``. The
first line of the result is a hash header over the rest, so the installer can tell an
unedited file (refreshed) from an edited one (never overwritten).

``comment=True`` adds the documented opt-in: a second job ``comment`` whose only scope is
``pull-requests: write``. It has no checkout, no Carter and no model: it downloads the summary
artifact and posts it with ``gh``. The ``review`` job stays ``contents: read``.
"""

from __future__ import annotations

import hashlib
import re

import carter
from carter.ci import OPENCODE_VERSION
from carter.resources import templates_dir

HEADER_PREFIX = "# carter-template-sha256: "
_HEADER = re.compile(r"\A# carter-template-sha256: ([0-9a-f]{64})\n")

_RULE = "\n#   - the opt-in comment job has `pull-requests: write` as its only scope (no checkout, no model)"
_OUT = " and, with the opt-in, one comment"
_ENV = "\n          CARTER_CI_COMMENT_FILE: ${{ runner.temp }}/carter-review-comment.md"
_UPLOAD = """
      - name: Keep the review text for the comment job
        if: steps.gate.outputs.run == 'true'
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: carter-review-comment
          path: ${{ runner.temp }}/carter-review-comment.md
          retention-days: 1
"""
_JOB = """
  comment:
    name: comment (opt-in, widens the scope)
    needs: review
    if: github.event.pull_request.head.repo.full_name == github.repository && needs.review.outputs.reviewed == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      pull-requests: write
    steps:
      - name: Download the review text
        uses: actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131 # v7.0.0
        with:
          name: carter-review-comment

      - name: Post it as one pull request comment
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: gh pr comment "$PR_NUMBER" --body-file carter-review-comment.md
"""


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def render(*, comment: bool = False, carter_version: str | None = None) -> str:
    """The workflow text with its hash header. Deterministic for the same arguments."""
    text = (templates_dir() / "ci" / "carter-review.yml.tmpl").read_text("utf-8")
    parts = {
        "__COMMENT_RULE__": _RULE if comment else "",
        "__COMMENT_OUT__": _OUT if comment else "",
        "__COMMENT_FILE_ENV__": _ENV if comment else "",
        "__COMMENT_UPLOAD__": _UPLOAD if comment else "",
        "__COMMENT_JOB__": _JOB if comment else "",
        "__OPENCODE_VERSION__": OPENCODE_VERSION,
        "__CARTER_VERSION__": carter_version or _public_version(),
    }
    for token, value in parts.items():
        text = text.replace(token, value)
    body = text.rstrip("\n") + "\n"
    return f"{HEADER_PREFIX}{body_hash(body)}\n{body}"


def _public_version() -> str:
    """``carter-ai==<this>`` must exist on PyPI: drop a local ``+...`` version suffix."""
    return str(carter.__version__).split("+", 1)[0]


def split(text: str) -> tuple[str | None, str]:
    """``(recorded hash or None, body)`` of a file Carter may have written."""
    match = _HEADER.match(text)
    return (match.group(1), text[match.end() :]) if match else (None, text)


def is_unedited(text: str) -> bool:
    """True when ``text`` carries Carter's header and its body still hashes to it."""
    recorded, body = split(text)
    return recorded is not None and recorded == body_hash(body)
