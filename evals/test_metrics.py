"""Unit tests for eval metrics normalization (key-free, offline).

Verifies that EvalMetrics.from_response extracts a uniform metrics shape from each
provider's response (openai uses `prompt_tokens`/`completion_tokens`;
anthropic uses `input_tokens`/`output_tokens`), and that cost is computed when the
model is priced and is None otherwise.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
import yaml

from evals.metrics import DEFAULT_MODEL, PRICE_PER_1M, EvalMetrics, _cost, from_response

# OpenAI-compatible shape.
_OPENAI_RAW = {
    "model": "gpt-4o",
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    "choices": [{"message": {"content": "hi"}}],
}

# Anthropic Messages API shape.
_ANTHROPIC_RAW = {
    "model": "claude-sonnet-4-6",
    "usage": {"input_tokens": 100, "output_tokens": 50},
    "content": [{"type": "text", "text": "hi"}],
}


def test_openai_shape_normalizes():
    m = from_response("openai", _OPENAI_RAW, latency_s=1.5)
    assert (m.prompt_tokens, m.completion_tokens, m.total_tokens) == (100, 50, 150)
    assert m.latency_s == 1.5


def test_anthropic_shape_normalizes_and_sums_total():
    m = from_response("anthropic", _ANTHROPIC_RAW, latency_s=2.0)
    assert (m.prompt_tokens, m.completion_tokens, m.total_tokens) == (100, 50, 150)


def test_cost_computed_for_priced_model():
    m = from_response("anthropic", _ANTHROPIC_RAW, latency_s=1.0)
    # claude-sonnet-4-6 = $3 / $15 per 1M tokens.
    assert m.cost_usd == (100 / 1_000_000 * 3.0) + (50 / 1_000_000 * 15.0)


def test_cost_none_for_unpriced_model_warns_once():

    raw = {**_OPENAI_RAW, "model": "some-unknown-model"}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        m = from_response("openai", raw, latency_s=1.0)
        from_response("openai", raw, latency_s=1.0)
    assert m.cost_usd is None
    msgs = [str(w.message) for w in caught if "some-unknown-model" in str(w.message)]
    assert len(msgs) == 1


def test_total_falls_back_to_sum_when_absent():
    raw = {"model": "gpt-4o", "usage": {"prompt_tokens": 10, "completion_tokens": 7}}
    m = from_response("openai", raw, latency_s=0.1)
    assert m.total_tokens == 17


def test_is_dataclass_with_expected_fields():
    m = EvalMetrics(prompt_tokens=1, completion_tokens=2, total_tokens=3, latency_s=0.5)
    assert m.cost_usd is None  # defaults to None when not priced


# --- Claude 5.5 pricing (Anthropic published rates) ---------------------------

_LIVE_WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/evals-live.yml"


def _canary_model() -> str:
    wf = yaml.safe_load(_LIVE_WORKFLOW.read_text(encoding="utf-8"))
    models = {job.get("env", {}).get("EVAL_MODEL") for job in wf.get("jobs", {}).values()} | {
        wf.get("env", {}).get("EVAL_MODEL")
    }
    models.discard(None)
    assert len(models) == 1, f"expected one EVAL_MODEL in evals-live.yml, got {models}"
    return models.pop()


def test_default_model_is_priced():
    assert DEFAULT_MODEL in PRICE_PER_1M


def test_live_canary_model_is_priced():
    assert _canary_model() in PRICE_PER_1M


@pytest.mark.parametrize(
    ("model", "expected"),
    [("claude-opus-5-5", 4.0 + 20.0), ("claude-sonnet-5-5", 2.0 + 10.0)],
)
def test_flat_55_cost(model, expected):
    assert _cost(model, 1_000_000, 1_000_000) == pytest.approx(expected)


def test_haiku_55_short_prompt_tier():
    assert _cost("claude-haiku-5-5", 100_000, 1_000_000) == pytest.approx(0.01 + 0.50)


def test_haiku_55_long_prompt_tier_bills_whole_request():
    assert _cost("claude-haiku-5-5", 100_001, 1_000_000) == pytest.approx(
        100_001 / 1e6 * 0.50 + 2.50
    )


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
def test_priced_models_do_not_warn(model):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _cost(model, 10, 10) is not None
