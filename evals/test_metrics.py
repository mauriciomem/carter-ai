"""Unit tests for eval metrics normalization (key-free, offline).

Verifies that EvalMetrics.from_response extracts a uniform metrics shape from each
provider's response (copilot/openai use `prompt_tokens`/`completion_tokens`;
anthropic uses `input_tokens`/`output_tokens`), and that cost is computed when the
model is priced and is None otherwise.
"""

from __future__ import annotations

from evals.metrics import EvalMetrics, from_response

# OpenAI-compatible shape (GitHub Copilot + OpenAI both use this).
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


def test_copilot_shape_normalizes():
    m = from_response("copilot", _OPENAI_RAW, latency_s=0.9)
    assert (m.prompt_tokens, m.completion_tokens, m.total_tokens) == (100, 50, 150)


def test_anthropic_shape_normalizes_and_sums_total():
    m = from_response("anthropic", _ANTHROPIC_RAW, latency_s=2.0)
    assert (m.prompt_tokens, m.completion_tokens, m.total_tokens) == (100, 50, 150)


def test_cost_computed_for_priced_model():
    m = from_response("anthropic", _ANTHROPIC_RAW, latency_s=1.0)
    # claude-sonnet-4-6 = $3 / $15 per 1M tokens.
    assert m.cost_usd == (100 / 1_000_000 * 3.0) + (50 / 1_000_000 * 15.0)


def test_cost_none_for_unpriced_model_warns_once():
    import warnings

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
