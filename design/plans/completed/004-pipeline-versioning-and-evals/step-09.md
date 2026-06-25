---
step: 9
status: done
depends_on: []
files_modified: [evals/metrics.py, evals/judge.py, evals/test_live.py, evals/test_metrics.py, evals/README.md]
---

## Step 9: Eval metrics — tokens/latency/cost + model-drift fix (TDD)

### Tasks (red → green)
1. **RED** — add `evals/test_metrics.py`: given a fake provider response containing
   a `usage` block, assert the harness extracts a normalized
   `EvalMetrics(prompt_tokens, completion_tokens, total_tokens, latency_s, cost_usd)`
   for each of the 3 providers (copilot/openai/anthropic shapes).
2. **GREEN** — add `evals/metrics.py` with an `EvalMetrics` dataclass + a
   `from_response(provider, raw, latency_s)` normalizer:
   - copilot/openai → `usage.prompt_tokens / completion_tokens / total_tokens`.
   - anthropic → `usage.input_tokens / output_tokens` (total = sum).
   - `cost_usd` via an optional `{model: (in_price, out_price)}` table; `None` if
     the model is unpriced.
3. Wire `_call_model` (test_live.py) and `judge_response` (judge.py) to time the
   request (`time.perf_counter`) and return/attach metrics. Set `temperature = 0` on
   ALL eval + judge calls for determinism.
4. **Fix the model-drift bug**: evals/README.md says `claude-sonnet-4-20250514` but
   judge.py:121 / test_live.py:88 default to `claude-sonnet-4.6`. Single-source the
   default model name (one constant in metrics.py or conftest), reference it
   everywhere, and update the README/env-var table to match.
5. Print a per-run metrics summary: pass-rate, mean judge score, total tokens, mean
   latency, est. $.

### Done criteria
- `evals/test_metrics.py` green; metrics normalize across all 3 providers.
- Live calls record tokens + latency (+ cost when priced); `temperature=0` set.
- Model name is single-sourced; README and code agree (drift fixed).

### Notes
The APIs already RETURN `usage` — today it is discarded (no `usage`/`*_tokens`
reference exists in evals/). This is pure capture: NO new API calls, NO key needed
for the unit test (fake responses). Leave the offline evals untouched (key-free).
