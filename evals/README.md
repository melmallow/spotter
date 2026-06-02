# Evals

A real-Claude evaluation suite that turns the README's "How I would evaluate this in production" section from prose into a runnable artifact. The unit tests in `tests/` prove the graph wiring; this suite measures whether the LLM actually does the right thing.

## Run

```bash
# fast & cheap — routing accuracy only
uv run python -m fitness_agent.evals --suite routing

# the full sweep
uv run python -m fitness_agent.evals --suite all
```

Requires `ANTHROPIC_API_KEY` in `.env`. Results land in `evals/results/<suite>-<timestamp>.jsonl` (gitignored).

## Suites

### `routing` — 50 labeled prompts → expected route

Asserts the router classifies each input correctly and reports a useful confidence.

Reports:
- `accuracy` — fraction of examples whose actual route matched the labeled expected route
- `min_confidence_pass_rate` — fraction whose actual route was correct AND confidence met the per-example threshold
- `mean_confidence_on_correct` / `mean_confidence_on_wrong` — quick calibration sanity check

### `ambiguous` — 10 underspecified prompts → clarification expected

Asserts low-confidence inputs land on the clarification path rather than silently misrouting. The PRD calls out "Bench press" as the canonical example; this suite generalizes that.

Reports:
- `recall` — fraction that triggered the clarification path

### `unavailable_equipment` — 5 prompts requesting equipment not in the dataset → empty-search recovery expected

Asserts the generator does NOT fabricate exercises when `search_exercises` returns nothing. Each response is checked for (a) no UUIDs that aren't in the dataset, and (b) acknowledgement of the unavailability via at least one of: "don't", "no", "not", "unavailable", "instead", "alternative".

Reports:
- `rate` — fraction of responses that meet both conditions

### `coach` — 10 reference COACH prompts judged by Claude sonnet

For each question, the agent's response is scored on three axes (factuality, scope adherence, tone) by a sonnet-tier judge against a list of reference facts. Scores are integers 1-5.

Reports:
- `mean_factuality`, `mean_scope_adherence`, `mean_tone`

## Cost per run

Approximate Anthropic spend per full `--suite all` run:
- `routing` (50 examples × haiku) — ~$0.10
- `ambiguous` (10 examples × haiku) — ~$0.02
- `unavailable_equipment` (5 examples × sonnet for tool-calling) — ~$0.15
- `coach` (10 examples × sonnet for the agent + 10 sonnet judge calls) — ~$0.40
- **Total: ~$0.50–$0.70 per full sweep.**

## First-run baseline

This space records the first end-to-end baseline so subsequent runs can be compared.

| Suite | Metric | First-run baseline |
|---|---|---|
| routing | accuracy | _record after first run_ |
| routing | min_confidence_pass_rate | _record after first run_ |
| ambiguous | recall | _record after first run_ |
| unavailable_equipment | rate | _record after first run_ |
| coach | mean_factuality | _record after first run_ |
| coach | mean_scope_adherence | _record after first run_ |
| coach | mean_tone | _record after first run_ |

## What the eval suite deliberately does not measure

- **Latency calibration.** Per-request latency is logged in `logs/trace.jsonl` for any run, but the eval runner does not aggregate p50/p95 across runs — a production-grade evaluation would.
- **Confidence calibration plot.** The runner reports mean confidence on correct vs. wrong, which is a one-number proxy for calibration; a real production system would track a full reliability diagram.
- **Drift over time.** Each run is a snapshot. A production system would archive results and surface drift week-over-week — this is on the v2 list.
- **Live traffic shape.** The labeled prompts cover an opinionated cross-section, not the long-tail of real user input. Production evaluation would augment this set continuously from anonymized live traffic.
