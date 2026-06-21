"""Plan validation — the ADR-0003 frontmatter contract, enforced in Python.

This is the deterministic gate behind ADR-0003 (O3): plans are only useful as a
recovery/quality-gate substrate if their metadata is machine-checkable. The
canonical schema lives in ``docs/reference/frontmatter.md`` (D6); this module is
its executable form. ``carter check`` runs ``validate_plans_dir`` over a
workspace's ``.carter/state/plans/``.

Design: pure functions returning lists of human-readable error strings (empty =
valid), mirroring the existing ``carter check`` error-collection style. No I/O
beyond reading the plan files passed in.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import yaml

# Plan id: NNN-kebab (three digits, then lowercase alphanumeric kebab segments),
# and it MUST equal the plan's directory name.
PLAN_ID_RE = re.compile(r"^\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*$")

# step-NN.md filename -> the NN integer.
STEP_FILE_RE = re.compile(r"^step-(\d+)\.md$")

# An ISO-ish date string (YYYY-MM-DD, optionally with a time component).
_DATE_STR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")

VALID_PLAN_STATUS = {"proposed", "active", "blocked", "completed", "abandoned"}
VALID_STEP_STATUS = {"pending", "in-progress", "done", "blocked"}
VALID_PUSH_POLICY = {"manual", "auto"}

# Terminal statuses belong in completed/; non-terminal (in-progress) statuses
# belong in active/. The maestro reads active/ for "plans in progress", so a
# terminal plan left in active/ would resurface as live work.
TERMINAL_STATUS = {"completed", "abandoned"}

# Keys a plan README frontmatter MUST carry. adr/tags/repos are optional.
REQUIRED_PLAN_KEYS = ("id", "status", "created", "updated", "push_policy", "must_haves")
MUST_HAVES_KEYS = ("truths", "artifacts", "key_links")

# Defaults mirror carter.config DEFAULT_CONFIG["plans"]; a workspace may override.
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "step_file_threshold": 3,
    "readme_max_lines": 150,
    "step_max_lines": 80,
    "git_regime": "private",
}


def _safe_read(path: Path, label: str) -> tuple[str | None, str | None]:
    """Read ``path`` as UTF-8, returning ``(text, None)`` or ``(None, error)``.

    Validation must never raise on a malformed file (binary, non-UTF-8, a path
    that is a directory, or unreadable) — it converts the failure into a
    validation error string so ``carter check`` reports it cleanly.
    """
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{label}: unreadable file ({type(exc).__name__})"


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    """Extract and parse the leading YAML frontmatter block.

    Returns the parsed mapping, or ``None`` if there is no well-formed block
    (no opening/closing ``---`` delimiters, invalid YAML, or a non-mapping body).
    Tolerates a leading UTF-8 BOM.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            block = "\n".join(lines[1:i])
            try:
                data = yaml.safe_load(block)
            except (yaml.YAMLError, ValueError):
                # ValueError: YAML constructs an impossible date (e.g. 2026-02-30)
                return None
            return data if isinstance(data, dict) else None
    return None


def _is_date_like(value: Any) -> bool:
    """True if ``value`` is a date Carter accepts: a parsed date/datetime (YAML
    parses unquoted ``2026-06-09`` to ``datetime.date``) or a string that is a real
    ISO calendar date (a quoted ``"2026-02-30"`` is regex-shaped but rejected)."""
    if isinstance(value, datetime.date | datetime.datetime):
        return True
    if not isinstance(value, str) or not _DATE_STR_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


def _count_step_rows(text: str) -> int | None:
    """Count steps declared in the README's ``## Steps`` section.

    Prefers a Markdown table (header + ``|---|`` separator + data rows); when no
    table is present, falls back to top-level numbered-list items so a prose step
    list does not silently bypass the split rule. Returns ``None`` if neither is
    found. **Heuristic** — robust for the canonical skill shape; a second table,
    pipe-containing prose, or an h3 subsection inside ``## Steps`` can skew it.
    """
    in_steps = False
    table_lines = 0
    found_table = False
    list_items = 0
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("## "):
            # Only the canonical "## Steps" section; avoid matching prose headers
            # like "## Step-by-step" (which would inflate the count).
            in_steps = s[3:].strip().lower().startswith("steps")
            continue
        if not in_steps:
            continue
        if s.startswith("|") and s.endswith("|"):
            found_table = True
            table_lines += 1
        elif re.match(r"^\d+\.\s", s):
            list_items += 1
    if found_table:
        return max(0, table_lines - 2)  # drop header + separator
    if list_items:
        return list_items
    return None


def _validate_step_file(step_file: Path, plan_name: str, thresholds: dict[str, Any]) -> list[str]:
    """Validate a single ``step-NN.md`` file's frontmatter and size."""
    rel = f"{plan_name}/{step_file.name}"
    text, read_err = _safe_read(step_file, rel)
    if read_err:
        return [read_err]
    assert text is not None  # read_err is None ⇒ text is set
    fm = parse_frontmatter(text)
    if fm is None:
        return [f"{rel}: missing or malformed YAML frontmatter"]

    errors: list[str] = []
    step = fm.get("step")
    if "step" not in fm:
        errors.append(f"{rel}: missing required key 'step'")
    elif not isinstance(step, int) or isinstance(step, bool):
        errors.append(f"{rel}: step {step!r} must be an integer")
    else:
        m = STEP_FILE_RE.match(step_file.name)
        if m and step != int(m.group(1)):
            errors.append(f"{rel}: step {step} must match the filename number {int(m.group(1))}")

    status = fm.get("status")
    if "status" in fm and status not in VALID_STEP_STATUS:
        errors.append(f"{rel}: status {status!r} not in {sorted(VALID_STEP_STATUS)}")

    depends_on = fm.get("depends_on")
    if depends_on is not None and not isinstance(depends_on, list):
        errors.append(f"{rel}: depends_on must be a list")
    elif isinstance(depends_on, list) and any(
        not isinstance(d, int) or isinstance(d, bool) for d in depends_on
    ):
        errors.append(f"{rel}: depends_on must contain only step numbers (integers)")

    n_lines = len(text.split("\n"))
    budget = thresholds["step_max_lines"]
    if n_lines > budget:
        errors.append(f"{rel}: {n_lines} lines exceeds budget {budget}")

    return errors


def validate_plan_dir(plan_dir: Path, thresholds: dict[str, Any] | None = None) -> list[str]:
    """Validate one plan directory against the ADR-0003 contract.

    Returns a list of human-readable error strings (empty = valid).
    """
    return _validate_plan_dir(plan_dir, thresholds)[0]


def _validate_plan_dir(
    plan_dir: Path, thresholds: dict[str, Any] | None = None
) -> tuple[list[str], dict[str, Any] | None]:
    """Internal: returns ``(errors, parsed_frontmatter_or_None)`` so callers that
    also need the frontmatter (e.g. the bucket-status check) don't re-read it."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    name = plan_dir.name

    readme = plan_dir / "README.md"
    if not readme.exists():
        return [f"{name}: missing README.md"], None

    text, read_err = _safe_read(readme, f"{name}/README.md")
    if read_err:
        return [read_err], None
    assert text is not None  # read_err is None ⇒ text is set
    fm = parse_frontmatter(text)
    if fm is None:
        return [f"{name}/README.md: missing or malformed YAML frontmatter"], None

    errors: list[str] = []

    for key in REQUIRED_PLAN_KEYS:
        if key not in fm:
            errors.append(f"{name}/README.md: missing required key {key!r}")

    # id: NNN-kebab and equal to the directory name
    plan_id = fm.get("id")
    if "id" in fm:
        if not isinstance(plan_id, str) or not PLAN_ID_RE.match(plan_id):
            errors.append(
                f"{name}/README.md: id {plan_id!r} must be NNN-kebab (e.g. 001-feature-name)"
            )
        elif plan_id != name:
            errors.append(
                f"{name}/README.md: id {plan_id!r} must match the directory name {name!r}"
            )

    status = fm.get("status")
    if "status" in fm and status not in VALID_PLAN_STATUS:
        errors.append(f"{name}/README.md: status {status!r} not in {sorted(VALID_PLAN_STATUS)}")

    push_policy = fm.get("push_policy")
    if "push_policy" in fm and push_policy not in VALID_PUSH_POLICY:
        errors.append(
            f"{name}/README.md: push_policy {push_policy!r} not in {sorted(VALID_PUSH_POLICY)}"
        )

    # created / updated must be dates
    for date_key in ("created", "updated"):
        if date_key in fm and not _is_date_like(fm.get(date_key)):
            errors.append(
                f"{name}/README.md: {date_key} {fm.get(date_key)!r} must be a date (YYYY-MM-DD)"
            )

    # must_haves shape + count
    must_haves = fm.get("must_haves")
    mh_count = 0
    if "must_haves" in fm:
        if not isinstance(must_haves, dict):
            errors.append(
                f"{name}/README.md: must_haves must be a mapping with {'/'.join(MUST_HAVES_KEYS)}"
            )
        else:
            unknown = [k for k in must_haves if k not in MUST_HAVES_KEYS]
            if unknown:
                errors.append(
                    f"{name}/README.md: must_haves has unknown key(s) {sorted(unknown)}; "
                    f"expected {list(MUST_HAVES_KEYS)}"
                )
            for sub in MUST_HAVES_KEYS:
                val = must_haves.get(sub)
                if val is None:
                    continue
                if not isinstance(val, list):
                    errors.append(f"{name}/README.md: must_haves.{sub} must be a list")
                else:
                    mh_count += len(val)

    # O6: an active plan must declare at least one must_haves entry
    if status == "active" and mh_count == 0:
        errors.append(
            f"{name}/README.md: an 'active' plan must declare at least one "
            f"must_haves entry (truths/artifacts/key_links)"
        )

    # README size budget
    readme_lines = len(text.split("\n"))
    if readme_lines > th["readme_max_lines"]:
        errors.append(
            f"{name}/README.md: {readme_lines} lines exceeds budget {th['readme_max_lines']}"
        )

    # Step files: required when steps > threshold; validate any present
    step_files = sorted(plan_dir.glob("step-*.md"))
    step_count = _count_step_rows(text)
    if step_count is not None and step_count > th["step_file_threshold"] and not step_files:
        errors.append(
            f"{name}: {step_count} steps (> {th['step_file_threshold']}) require "
            f"per-step step-NN.md files"
        )
    for step_file in step_files:
        errors.extend(_validate_step_file(step_file, name, th))

    return errors, fm


def validate_plans_dir(plans_root: Path, thresholds: dict[str, Any] | None = None) -> list[str]:
    """Validate every plan under ``plans_root/{active,completed}/``.

    Missing directories are treated as clean (a fresh workspace has no plans).
    In addition to each plan's intrinsic validity: the frontmatter status must be
    coherent with its bucket (``completed/`` holds only terminal statuses), and a
    plan number (NNN) must be unique **globally**, not just within one bucket.
    """
    errors: list[str] = []
    seen: dict[str, list[str]] = {}  # NNN -> ["<bucket>/<name>", ...], global
    for state in ("active", "completed"):
        state_dir = plans_root / state
        if not state_dir.is_dir():
            continue
        for plan_dir in sorted(p for p in state_dir.iterdir() if p.is_dir()):
            errs, fm = _validate_plan_dir(plan_dir, thresholds)
            errors.extend(errs)
            status = fm.get("status") if fm else None
            errors.extend(_check_bucket_status(plan_dir.name, status, state))
            m = re.match(r"^(\d{3})-", plan_dir.name)
            if m:
                seen.setdefault(m.group(1), []).append(f"{state}/{plan_dir.name}")
    for nnn, names in sorted(seen.items()):
        if len(names) > 1:
            errors.append(f"duplicate plan number {nnn} ({', '.join(sorted(names))})")
    return errors


def _check_bucket_status(name: str, status: Any, bucket: str) -> list[str]:
    """Flag a plan whose frontmatter status contradicts its ``active``/``completed``
    bucket. Takes the already-parsed status (no I/O); conditions already reported
    by ``_validate_plan_dir`` (missing/invalid status) are skipped here."""
    if status not in VALID_PLAN_STATUS:
        return []  # missing/invalid status already reported by validate_plan_dir
    if bucket == "active" and status in TERMINAL_STATUS:
        return [
            f"{name}/README.md: status {status!r} is terminal but the plan is in "
            f"active/ (move it to completed/)"
        ]
    if bucket == "completed" and status not in TERMINAL_STATUS:
        return [
            f"{name}/README.md: status {status!r} is not terminal but the plan is in "
            f"completed/ (move it to active/)"
        ]
    return []


def validate_checkpoint(checkpoint_file: Path, plans_root: Path | None = None) -> list[str]:
    """Validate the session ``checkpoint.md`` recovery cursor (ADR-0003 D7.2).

    The checkpoint is optional: its absence is clean. If present, it must carry
    valid frontmatter with ``updated`` and, when set, an ``active_plan`` string
    and an integer ``next_step`` (both may be null). It is a thin cursor that
    points into a plan's frontmatter — not a place to duplicate plan content.

    When ``plans_root`` is given, ``active_plan`` must resolve to a real plan
    under ``plans_root/active/`` — a dangling pointer would misdirect recovery.
    """
    if not checkpoint_file.exists():
        return []

    rel = "sessions/checkpoint.md"
    text, read_err = _safe_read(checkpoint_file, rel)
    if read_err:
        return [read_err]
    assert text is not None  # read_err is None ⇒ text is set
    fm = parse_frontmatter(text)
    if fm is None:
        return [f"{rel}: missing or malformed YAML frontmatter"]

    errors: list[str] = []
    if "updated" not in fm:
        errors.append(f"{rel}: missing required key 'updated'")

    active_plan = fm.get("active_plan")
    if active_plan is not None and not isinstance(active_plan, str):
        errors.append(f"{rel}: active_plan must be a string or null")
    elif isinstance(active_plan, str) and plans_root is not None:
        active_dir = (plans_root / "active").resolve()
        candidate = (active_dir / active_plan).resolve()
        # Must resolve to a real plan directory *inside* active/ — reject both
        # missing pointers and ".."-traversal that escapes the bucket.
        is_contained = candidate == active_dir or active_dir in candidate.parents
        if not (candidate.is_dir() and is_contained):
            errors.append(
                f"{rel}: active_plan {active_plan!r} does not resolve to a plan under "
                f"active/ (dangling pointer)"
            )

    next_step = fm.get("next_step")
    # bool is a subclass of int, but `next_step: true` is not a step index.
    if next_step is not None and (not isinstance(next_step, int) or isinstance(next_step, bool)):
        errors.append(f"{rel}: next_step must be an integer or null")

    return errors
