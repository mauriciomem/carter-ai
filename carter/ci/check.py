"""Structural checker for Carter's review-only workflow.

Pure Python (PyYAML, already a dependency), no network. ``actionlint`` is run on top of this
when it is installed; this checker is the floor and also enforces rules actionlint does not
have (no ``write``, SHA pins, the secret only in step-level ``env``, ``pull_request`` only).

Rules (``Finding.rule``):

- ``CI000`` the file is not a workflow mapping;
- ``CI001`` a trigger other than ``pull_request`` (``pull_request_target`` and ``workflow_run``
  run with secrets on code an outsider controls);
- ``CI002`` workflow ``permissions`` are not exactly ``contents: read``;
- ``CI003`` a job without its own ``permissions``;
- ``CI004`` a ``write`` permission anywhere except ``pull-requests: write`` as the only scope of
  the documented opt-in job ``comment`` (which must not check out code);
- ``CI005`` an action not pinned to a 40-hex commit SHA with a ``# vX`` comment, a local or
  docker action, or a reusable workflow;
- ``CI006`` a job without ``timeout-minutes`` (1-60);
- ``CI007`` no ``concurrency`` with ``cancel-in-progress: true``;
- ``CI008`` ``actions/checkout`` without ``persist-credentials: false``;
- ``CI009`` a ``secrets`` reference outside a step's ``env`` (or any secret other than
  ``LLM_API_KEY``, ``secrets: inherit``, ``toJSON(secrets)``);
- ``CI010`` a ``${{ }}`` expression inside a ``run:`` script (script injection: pass it through
  ``env`` and quote the variable);
- ``CI011`` a job that reads the secret without ``environment``;
- ``CI012`` a job that reads the secret (or holds a write scope) without the fork-skipping
  ``if:``;
- ``CI013`` a self-hosted or non-literal ``runs-on``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from carter.ci import COMMENT_JOB, SECRET

FORK_GUARD = "github.event.pull_request.head.repo.full_name == github.repository"
_SHA_USE = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$")
_SECRET_REF = re.compile(r"\bsecrets\b")
_SECRET_NAME = re.compile(r"\bsecrets\.([A-Za-z0-9_-]+)")
_EXPR = re.compile(r"\$\{\{")
_READ_ONLY = ("read", "none")


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    message: str

    def render(self) -> str:
        return f"{self.rule} {self.where}: {self.message}"


def _strings(node: Any, path: str = "") -> list[tuple[str, str]]:
    """Every string value of ``node`` with a dotted path (keys included, so ``secrets:`` shows)."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}" if path else str(key)
            out.append((f"{sub}#key", str(key)))
            out.extend(_strings(value, sub))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.extend(_strings(value, f"{path}[{i}]"))
    elif isinstance(node, str):
        out.append((path, node))
    return out


def _triggers(doc: dict[Any, Any]) -> list[str]:
    on = doc["on"] if "on" in doc else doc.get(True)  # YAML 1.1 reads a bare `on:` as True
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(x) for x in on]
    if isinstance(on, dict):
        return [str(k) for k in on]
    return []


def _perm_findings(where: str, perms: Any, *, optin: bool) -> list[Finding]:
    if isinstance(perms, str):  # `read-all` / `write-all`
        if perms == "write-all":
            return [Finding("CI004", where, "`write-all` grants every scope")]
        return []
    if not isinstance(perms, dict):
        return []
    out = []
    for scope, level in perms.items():
        if level == "write" and not (optin and scope == "pull-requests"):
            out.append(Finding("CI004", where, f"`{scope}: write` is not allowed here"))
        elif level not in ("read", "none", "write"):
            out.append(Finding("CI004", where, f"`{scope}` has an unknown level"))
    return out


def _is_checkout(step: dict[str, Any]) -> bool:
    return str(step.get("uses", "")).split("@", 1)[0] == "actions/checkout"


class _StrictLoader(yaml.SafeLoader):
    """``safe_load`` that refuses a duplicate key: PyYAML keeps the last one, so a second
    ``permissions:`` could hide the first from a reader while the checker saw only one."""


def _no_duplicates(
    loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _value in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.YAMLError(f"duplicate key {key!r}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def check(text: str) -> list[Finding]:
    """All findings for the workflow ``text`` (empty means it keeps every workflow rule)."""
    try:
        doc = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError:
        return [Finding("CI000", "file", "not valid YAML (or a duplicate key)")]
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        return [Finding("CI000", "file", "not a workflow (no `jobs` mapping)")]
    out: list[Finding] = []

    triggers = _triggers(doc)
    for name in triggers:
        if name != "pull_request":
            out.append(Finding("CI001", "on", f"trigger `{name}` is not allowed"))
    if "pull_request" not in triggers:
        out.append(Finding("CI001", "on", "the workflow must run on `pull_request`"))

    top = doc.get("permissions")
    if top != {"contents": "read"}:
        out.append(Finding("CI002", "permissions", "workflow permissions must be `contents: read`"))
    out.extend(_perm_findings("permissions", top, optin=False))

    jobs: dict[str, Any] = doc["jobs"]
    concurrency = [doc.get("concurrency")] + [j.get("concurrency") for j in jobs.values()]
    if not any(isinstance(c, dict) and c.get("cancel-in-progress") is True for c in concurrency):
        out.append(Finding("CI007", "concurrency", "needs `concurrency` with cancel-in-progress"))

    for job_id, job in jobs.items():
        out.extend(_check_job(str(job_id), job if isinstance(job, dict) else {}))
    out.extend(_check_secrets(doc))
    out.extend(_check_uses_comments(text))
    return out


def _check_job(job_id: str, job: dict[str, Any]) -> list[Finding]:
    where = f"jobs.{job_id}"
    out: list[Finding] = []
    steps = [s for s in job.get("steps", []) if isinstance(s, dict)]
    perms = job.get("permissions")
    if perms is None:
        out.append(Finding("CI003", where, "the job needs its own `permissions`"))
    optin = job_id == COMMENT_JOB and perms == {"pull-requests": "write"}
    out.extend(_perm_findings(f"{where}.permissions", perms, optin=optin))
    if job_id == COMMENT_JOB and any(_is_checkout(s) for s in steps):
        out.append(Finding("CI004", where, "the job with a write scope must not check out code"))
    if "uses" in job:
        out.append(Finding("CI005", where, "a reusable workflow is not allowed"))
    timeout = job.get("timeout-minutes")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 60:
        out.append(Finding("CI006", where, "needs `timeout-minutes` between 1 and 60"))
    runs_on = job.get("runs-on")
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    if any(not isinstance(x, str) or "self-hosted" in x or "${{" in x for x in labels):
        out.append(Finding("CI013", where, "`runs-on` must be a literal GitHub-hosted label"))
    reads_secret = any(
        _SECRET_REF.search(v) for p, v in _strings(job.get("steps", [])) if not p.endswith("#key")
    )
    if reads_secret and not job.get("environment"):
        out.append(Finding("CI011", where, "a job that reads the secret needs `environment`"))
    guarded = FORK_GUARD in str(job.get("if", ""))
    if (reads_secret or optin) and not guarded:
        out.append(Finding("CI012", where, "needs the fork-skipping `if:` on the head repository"))
    for i, step in enumerate(steps):
        out.extend(_check_step(f"{where}.steps[{i}]", step))
    return out


def _check_step(where: str, step: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    uses = step.get("uses")
    if isinstance(uses, str) and not _SHA_USE.match(uses):
        out.append(Finding("CI005", where, "an action must be pinned to a 40-hex commit SHA"))
    if _is_checkout(step):
        persist = (step.get("with") or {}).get("persist-credentials")
        if persist not in (False, "false"):
            out.append(Finding("CI008", where, "checkout needs `persist-credentials: false`"))
    run = step.get("run")
    if isinstance(run, str) and _EXPR.search(run):
        out.append(Finding("CI010", where, "no `${{ }}` inside `run:`; pass it through `env`"))
    return out


def _check_secrets(doc: dict[str, Any]) -> list[Finding]:
    """A secret may appear only as a value of a step's ``env``, and only ``LLM_API_KEY``."""
    out: list[Finding] = []
    for path, value in _strings(doc):
        is_key = path.endswith("#key")
        if is_key and value in ("secrets", "secrets.inherit"):
            out.append(Finding("CI009", path[:-4], "`secrets:` is not allowed"))
            continue
        if is_key or not _SECRET_REF.search(value):
            continue
        step_env = re.fullmatch(r"jobs\.[^.]+\.steps\[\d+\]\.env\.[A-Za-z_][A-Za-z0-9_]*", path)
        names = set(_SECRET_NAME.findall(value))
        if not step_env:
            out.append(Finding("CI009", path, "a secret may be read only in a step's `env`"))
        elif names != {SECRET} or re.search(r"\bsecrets\s*\[|toJSON\(\s*secrets", value):
            out.append(Finding("CI009", path, f"the only secret allowed is `{SECRET}`"))
    return out


def _check_uses_comments(text: str) -> list[Finding]:
    """A pinned action keeps its version in a comment (``# v7.0.1``), so the pin is readable."""
    out: list[Finding] = []
    for no, line in enumerate(text.splitlines(), start=1):
        match = _USES_LINE.match(line)
        if match and _SHA_USE.match(match.group(1)) and not re.match(r"\s+#\s*v\d", match.group(2)):
            out.append(Finding("CI005", f"line {no}", "a pinned action needs a `# vX.Y.Z` comment"))
    return out


def check_file(path: Path) -> list[Finding]:
    return check(path.read_text(encoding="utf-8"))
