"""Eval metrics — normalize token usage / latency / cost across providers.

The live-eval providers (GitHub Copilot, OpenAI, Anthropic) already RETURN a
`usage` block on every response; historically the harness discarded it. This module
normalizes those differing shapes into a single ``EvalMetrics`` record and computes
an estimated USD cost from a small per-model price table.

Single source of truth for the default model name, so test_live.py /
test_adherence_live.py / README never drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Default models for live evals. Canonical Anthropic IDs (hyphens, no dot):
# `claude-sonnet-4.6` is a 404-causing typo and `claude-sonnet-4-20250514` is
# deprecated — both previously appeared in code/README and disagreed. Single-sourced
# here; override per-run with EVAL_MODEL (e.g. a Haiku-class model on the weekly cron).
DEFAULT_MODEL = "claude-sonnet-5-5"

# USD price per 1M tokens: model -> (input, output). Unlisted models => cost_usd None.
# TODO: add the Claude 5.5 family once its pricing is confirmed; until then a 5.5 run
# reports cost_usd None rather than a guessed figure.
PRICE_PER_1M: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),  # kept: the recorded adherence fixture is a 4.6 transcript
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
}


@dataclass
class EvalMetrics:
    """Normalized per-call usage metrics."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_s: float
    cost_usd: float | None = None


def _cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimated USD cost, or None when the model has no price entry."""
    price = PRICE_PER_1M.get(model)
    if price is None:
        return None
    in_price, out_price = price
    return (prompt_tokens / 1_000_000 * in_price) + (completion_tokens / 1_000_000 * out_price)


def from_response(provider: str, raw: dict[str, Any], latency_s: float) -> EvalMetrics:
    """Normalize a raw provider response into ``EvalMetrics``.

    - copilot / openai: ``usage.prompt_tokens`` / ``completion_tokens`` / ``total_tokens``.
    - anthropic: ``usage.input_tokens`` / ``output_tokens`` (total = their sum).

    ``cost_usd`` is computed from ``raw["model"]`` against ``PRICE_PER_1M`` (None if
    the model is unpriced). ``total_tokens`` falls back to prompt+completion when absent.
    """
    usage = raw.get("usage", {}) or {}
    if provider == "anthropic":
        prompt = int(usage.get("input_tokens", 0))
        completion = int(usage.get("output_tokens", 0))
        total = prompt + completion
    else:  # copilot / openai (OpenAI-compatible)
        prompt = int(usage.get("prompt_tokens", 0))
        completion = int(usage.get("completion_tokens", 0))
        total = int(usage.get("total_tokens", prompt + completion))

    model = raw.get("model", "")
    return EvalMetrics(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        latency_s=latency_s,
        cost_usd=_cost(model, prompt, completion),
    )


# ── Run-level accumulator + summary ────────────────────────────────────────────
# _call_model appends here so a run can print an aggregate summary
# without changing their string return contract.
_RECORDED: list[EvalMetrics] = []


def record(metric: EvalMetrics) -> EvalMetrics:
    """Record a metric for the run-level summary; returns it for convenience."""
    _RECORDED.append(metric)
    return metric


def summary() -> dict[str, Any]:
    """Aggregate the recorded metrics: call count, total tokens, mean latency, est. $."""
    calls = len(_RECORDED)
    total_tokens = sum(m.total_tokens for m in _RECORDED)
    mean_latency = (sum(m.latency_s for m in _RECORDED) / calls) if calls else 0.0
    costs = [m.cost_usd for m in _RECORDED if m.cost_usd is not None]
    est_cost = sum(costs) if costs else None
    return {
        "calls": calls,
        "total_tokens": total_tokens,
        "mean_latency_s": round(mean_latency, 3),
        "est_cost_usd": round(est_cost, 6) if est_cost is not None else None,
    }
