"""LLM-as-judge for evaluating response quality on rubrics.

Used by live evals when assertions alone aren't sufficient (e.g., "is this
explanation accessible to a non-expert?").

Usage:
    from evals.judge import judge_response

    result = judge_response(
        response="The CAP theorem states...",
        rubric=["accessible_to_non_expert", "uses_examples_or_analogies"],
        context="User asked: Explain the CAP theorem",
    )
    assert result.passed
    assert result.score >= 0.7
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from evals.metrics import DEFAULT_JUDGE_MODEL, from_response, record


@dataclass
class JudgeResult:
    """Result from the LLM judge."""

    passed: bool
    score: float  # 0.0 to 1.0
    reasoning: str
    rubric_scores: dict[str, float]


JUDGE_SYSTEM_PROMPT = """\
You are an evaluation judge. Given a response and a set of quality rubrics,
score how well the response meets each rubric criterion.

For each rubric item, score 0.0 (completely fails) to 1.0 (perfectly meets).
Then give an overall score (average of rubric scores) and a pass/fail (pass if >= 0.7).

Respond ONLY with valid JSON in this exact format:
{
  "passed": true/false,
  "score": 0.0-1.0,
  "reasoning": "one sentence explanation",
  "rubric_scores": {"rubric_name": 0.0-1.0, ...}
}
"""

_COPILOT_API_URL = "https://api.githubcopilot.com/chat/completions"
_COPILOT_AUTH_FILE = Path.home() / ".local/share/opencode/auth.json"


def _get_copilot_token() -> str | None:
    """Get a GitHub Copilot OAuth token from available sources."""
    if _COPILOT_AUTH_FILE.exists():
        try:
            data = json.loads(_COPILOT_AUTH_FILE.read_text())
            token = data.get("github-copilot", {}).get("access")
            if token:
                return token
        except (json.JSONDecodeError, KeyError):
            pass
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_judge_auth() -> tuple[str, str]:
    """Return (provider, key) for the judge model."""
    if token := _get_copilot_token():
        return "copilot", token
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", key
    if key := os.environ.get("OPENAI_API_KEY"):
        return "openai", key
    import pytest

    pytest.skip("No auth available for judge")


def judge_response(
    response: str,
    rubric: list[str],
    context: str = "",
) -> JudgeResult:
    """Evaluate a response against quality rubrics using an LLM judge.

    Args:
        response: The model's response to evaluate
        rubric: List of quality criteria (e.g., ["accessible_to_non_expert"])
        context: The original user request or scenario context

    Returns:
        JudgeResult with scores and pass/fail

    Raises:
        pytest.skip if no auth is available
    """

    provider, api_key = _get_judge_auth()

    user_msg = (
        f"## Context\n{context}\n\n"
        f"## Response to Evaluate\n{response}\n\n"
        f"## Rubric Criteria\n" + "\n".join(f"- {r}" for r in rubric)
    )

    model = os.environ.get("EVAL_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)

    t0 = time.perf_counter()
    if provider == "copilot":
        resp = httpx.post(
            _COPILOT_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Editor-Version": "vscode/1.118.0",
                "Copilot-Integration-Id": "carter-evals",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
    elif provider == "anthropic":
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "temperature": 0,
                "system": JUDGE_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["content"][0]["text"]
    else:
        if "EVAL_JUDGE_MODEL" not in os.environ:
            model = "gpt-4o-mini"
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]

    record(from_response(provider, data, time.perf_counter() - t0))

    # Parse JSON response from judge
    # Handle markdown code blocks if present
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]

    data = json.loads(raw.strip())

    return JudgeResult(
        passed=data["passed"],
        score=data["score"],
        reasoning=data["reasoning"],
        rubric_scores=data.get("rubric_scores", {}),
    )
