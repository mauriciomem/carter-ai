"""Carter in CI: the review-only workflow (context E) and its driver (RFC-0007 §4.1, App C.10).

Plan 008 / slice CI-E. Three parts: ``template`` renders the hardened workflow, ``check``
validates any workflow against the C.10 rules, ``review`` is what the workflow runs
(``carter ci review``). The mode logic that refuses commits is ``carter.identity.mode``.
"""

from __future__ import annotations

WORKFLOW_REL = ".github/workflows/carter-review.yml"
ENVIRONMENT = "carter-review"
SECRET = "LLM_API_KEY"
OPENCODE_VERSION = "2.1.4"  # the OpenCode the review profile was tested against
COMMENT_JOB = "comment"
