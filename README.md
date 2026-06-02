# Spotter — LangGraph Multi-Agent Fitness System

A LangGraph hub agent that routes user requests across three intents — coach a movement, generate a workout, log a workout — to specialized sub-agents backed by Anthropic Claude and a 50-exercise dataset. Built for the [Future Research AI Engineer take-home](https://github.com/future-research/candidate-assessment/blob/main/1-multi-agent/ASSESSMENT.md).

## Quick start

```bash
git clone https://github.com/melmallow/Spotter.git && cd Spotter
cp .env.example .env             # then put your ANTHROPIC_API_KEY in .env
uv sync --extra dev
uv run python -m spotter   # serves http://127.0.0.1:8000
```

Then open the URL and try the chips below the chat input — one prompt per route.

## Run the tests

```bash
uv run pytest -v
```

Nine deterministic tests across two critical-path test files, no real API calls. See `tests/README.md` for why these two paths matter most.

## Run the evals

```bash
uv run python -m spotter.evals --suite routing   # ~$0.10 of haiku spend
uv run python -m spotter.evals --suite all       # ~$0.50 full sweep
```

See `evals/README.md` for what each suite measures and where to record the baseline numbers. The eval suite hits real Claude — `tests/` does not.

## Architecture

```mermaid
flowchart TD
    User([User message via /chat]) --> Hub[Hub StateGraph]
    Hub --> Router[Router subgraph<br/>haiku + with_structured_output<br/>→ RouteDecision]
    Router -->|confidence ≥ 0.6| Decision{route?}
    Router -->|confidence &lt; 0.6| Clarify[Clarification node]
    Decision -->|COACH| Coach[Coach subgraph<br/>sonnet, no tools]
    Decision -->|WORKOUT_GENERATE| Generator[Generator subgraph<br/>sonnet + 2 tools]
    Decision -->|WORKOUT_LOG| Logger[Logger subgraph<br/>haiku + structured output<br/>+ RapidFuzz match]
    Generator --> SearchTool[search_exercises<br/>filters: muscle / equipment<br/>/ movement / avoid_joints]
    Generator --> BuildTool[build_workout<br/>warmup / main / cooldown<br/>+ bilateral side-flip]
    Coach --> Hub
    Generator --> Hub
    Logger --> Hub
    Clarify --> Hub
    Hub --> Response([Final response])
```

**The hub** is a typed `StateGraph` whose nodes are compiled subgraphs (not inlined functions), wired with explicit edges and a single conditional edge from the router. Each sub-agent owns its own graph and is composed into the hub via `add_node(name, compiled_subgraph)`.

**The router** uses Claude haiku with `with_structured_output(RouteDecision)` to classify intent and self-report confidence in `[0, 1]`. When confidence < 0.6 or the route is `UNKNOWN`, the graph routes to a clarification node that names the two most likely routes. Routing errors fall back to clarification, never to silent misroute.

**The workout generator** is a tool-calling agent over two Pydantic-bound tools. `search_exercises` filters by muscle group, equipment, movement pattern, and an optional `avoid_joints` exclusion (the injury filter). `build_workout` resolves selected exercise IDs into warmup / main / cooldown blocks with sets, reps, and rest; for any selected exercise marked `is_bilateral=True`, the tool auto-appends a second `(other side)` set of the same record. (The dataset's `bilateral_pair_id` values do not resolve to real records, so we use the same record with a flipped side label rather than synthesizing a virtual pair.)

**The workout logger** runs Claude haiku with `with_structured_output(LogEntry)` to extract sets / reps / weight / unit, then fuzzy-matches the user's exercise name to the dataset with RapidFuzz `WRatio`. Matches above the threshold return a resolved log; below, the top-3 candidates surface so the user can disambiguate instead of the system guessing.

**The coach** is a single sonnet call with a scope-guard prompt that names what it covers (exercises, anatomy, programming concepts) and redirects off-topic asks back to fitness.

**Observability** rides on `structlog` with `contextvars`. The FastAPI middleware binds a fresh `trace_id` per request; every routing decision, tool invocation, and sub-agent response emits a JSON line to both stdout and `logs/trace.jsonl`. Grep by `event` to walk a single request: `hub_request → routed → tool_call → ... → hub_response`.

## Example transcripts

> **User:** What muscles does a Romanian deadlift work?
>
> **Coach** (sonnet, no tools) → "RDLs primarily load the posterior chain — hamstrings, glutes, and the erectors as bracers. The movement is a hip hinge; the knees stay relatively static while the hips drive back. Lats engage isometrically to keep the bar tight to the body."

> **User:** Build me a 30-minute upper body workout with dumbbells
>
> **Generator** (sonnet, tool-calling) → calls `search_exercises(muscle_groups=['chest','triceps','deltoids','lats'], equipment=['Dumbbell'])`, picks 4 exercises, calls `build_workout(...)`, returns:
> ```
> WARMUP
> - 2x10 Push-Up to Knee-Drive (rest 30s)
> MAIN
> - 4x8 Dumbbell Neutral-Grip Bench Press (rest 90s)
> - 3x10 Dumbbell Incline Chest Fly (rest 60s)
> - 3x12 Single-Arm Dumbbell Row (left arm, rest 45s)
> - 3x12 Single-Arm Dumbbell Row (right arm, rest 45s)
> COOLDOWN
> - 2x30s Kneeling Stability Ball Lat Stretch (rest 0s)
> ```

> **User:** I just did 3x10 bench press at 185 lbs
>
> **Logger** (haiku + WRatio) → "Logged: 3x10 Barbell Decline Bench Press at 185 lbs." (The dataset doesn't carry a generic "Bench Press" — WRatio scored Decline highest; reviewer can see all three candidates in the trace log.)

> **User:** Bench press
>
> **Router → Clarification** → "I'm not sure what you meant — would you like me to build you a workout or log a workout you just finished? A bit more detail will help me route correctly."

## Design decisions

| Decision | Why |
|---|---|
| Anthropic Claude tier split (haiku / sonnet) | Haiku is fast and cheap for structured-output classification (router, log extraction); sonnet quality dominates for generation (coach, workout tool-calling). |
| `with_structured_output(RouteDecision)` carries confidence as a Pydantic field | langchain-anthropic doesn't return confidence natively; making the LLM self-report it inside the schema costs zero infrastructure. |
| Clarification path, not silent fallback | The PRD called for the decision to be explicit. Surfacing uncertainty preserves the user's trust. |
| Sub-agents as separate `StateGraph` subgraphs | The PRD called for this. It also makes each agent unit-testable in isolation. |
| FastAPI single-page + Tailwind via CDN | "Simple web view is fine" per PRD; CDN avoids a build step so the reviewer can open the page immediately. |
| RapidFuzz `WRatio` for exercise-name match | `token_set_ratio` scored too low against full canonical names ("bench press" vs "Barbell Flat Bench Press"); WRatio combines strategies and handles partial substring matches. |
| Bilateral side-flip inside `build_workout` | Dataset's `bilateral_pair_id` values do not resolve to real records. Flipping a side label on the same record satisfies AE5 without inventing IDs. |
| `structlog` with `contextvars` for `trace_id` | One global config, cleanly propagates across async sub-graph calls — `RunnableConfig` callbacks would be more code for the same effect. |
| `uv` + `pyproject.toml` + `src/` layout | Fast install for the reviewer, modern Python defaults. |

## Known limits

- No streaming responses — `/chat` returns one JSON payload.
- No multi-turn conversation memory — each `/chat` request is independent. The clarification flow uses example-prompt chips and request re-submission, not threaded context.
- No Langfuse or OpenTelemetry — observability is `structlog` only.
- No authentication, persistence, or rate limiting.
- Coach responses about exercises NOT in the 50-record dataset use Claude's general knowledge; the scope-guard prompt nudges the model toward fitness, but factuality is best-effort.

## How I would evaluate this system in production

The starting point is `evals/`. It runs today against real Claude and reports concrete numbers — routing accuracy, ambiguous-input clarification recall, empty-search recovery rate (UUID-presence + acknowledgement check), and an LLM-as-judge score for COACH responses on factuality, scope adherence, and tone. That's the working artifact. Production hardening would layer the following on top.

**Routing accuracy.** The labeled set in `evals/data/routing.jsonl` is the starting test bed. In production, I'd grow it continuously from sampled live traffic (anonymized) and human-labeled corrections. Target: ≥ 95% accuracy on the rolling set, with a confidence-calibration plot (predicted confidence vs. observed correctness) reviewed weekly. The eval currently reports `mean_confidence_on_correct` vs `mean_confidence_on_wrong` as a single-number calibration sanity check; the plot is v2.

**Tool-call validity.** The empty-search suite checks for fabricated UUIDs. In production I'd extend this to a per-route counter on `logs/trace.jsonl`: `count(tool_call where success=false) / count(tool_call)`. Alert if the rate climbs above 1%. This is the cheapest tripwire for prompt regressions in the tool-calling flow.

**Empty-search rate as a coverage signal.** Today the eval intentionally probes 5 unavailable-equipment cases. In production, the empty-search rate from real traffic is a coverage signal: when it climbs in a particular muscle / equipment combination, the dataset has a gap users care about. This drives dataset expansion priorities.

**Latency.** Per-request `latency_ms` already lives in `logs/trace.jsonl`. Production needs an aggregator that emits p50 and p95 per route, plus a dashboard. Targets I'd set initially: COACH p95 < 3s, WORKOUT_LOG p95 < 2s (cheap), WORKOUT_GENERATE p95 < 8s (tool loop dominates).

**Hallucination spot-checks for COACH.** The `coach` suite already runs an LLM-as-judge against reference facts and scores three axes. Production would sample live COACH responses on a cadence (e.g., 1% of requests) and run the same judge with anonymized context. A drift in `mean_factuality` triggers a prompt review.

**Failure-mode catalog grepable from `logs/trace.jsonl`.** Every error class lands in the structured log with `event=hub_error|validation_error|tool_call success=false`. Searching for those events surfaces the failure population. A weekly report `jq 'select(.event=="hub_error")' logs/trace.jsonl | sort | uniq -c` (or equivalent in a real log pipeline) is the starting tripwire.

What the system would lose under traffic that v1 doesn't address: real per-user persistence (currently in-memory only), rate-limiting per IP, stateful conversation context across requests, and a proper observability backend (Langfuse, OpenTelemetry, or equivalent). These are explicit v2 work — they're called out in the brainstorm's Scope Boundaries.

## Repo layout

```
fitness/
├── exercises.json                   # 50-exercise dataset (provided)
├── pyproject.toml
├── src/spotter/
│   ├── __main__.py                  # launches the FastAPI demo
│   ├── config.py                    # env vars + thresholds
│   ├── data.py                      # dataset loader + indexes
│   ├── schemas.py                   # HubState + structured-output models
│   ├── llm.py                       # Anthropic factory (haiku|sonnet)
│   ├── logging_setup.py             # structlog + contextvars
│   ├── hub.py                       # hub StateGraph + run_hub
│   ├── agents/
│   │   ├── router.py
│   │   ├── clarification.py
│   │   ├── coach.py
│   │   ├── logger.py
│   │   └── generator.py
│   ├── tools/
│   │   ├── search_exercises.py
│   │   └── build_workout.py
│   ├── web/
│   │   ├── app.py                   # FastAPI + /chat
│   │   ├── __main__.py              # uvicorn entrypoint
│   │   └── templates/index.html     # Tailwind + Inter
│   └── evals/
│       ├── __main__.py              # CLI: --suite routing|ambiguous|...|all
│       ├── runner.py
│       ├── metrics.py
│       └── judge.py
├── tests/
│   ├── README.md                    # explains why these two paths matter
│   ├── conftest.py                  # FakeStructuredChatModel wrapper
│   ├── test_router_clarification.py # critical path #1
│   └── test_generator_empty_search.py # critical path #2
├── evals/
│   ├── README.md
│   ├── data/                        # labeled prompt sets
│   └── results/                     # gitignored — runner output
├── logs/                            # gitignored — trace.jsonl
└── docs/
    ├── brainstorms/                 # requirements doc
    └── plans/                       # implementation plan
```

The `docs/brainstorms/` and `docs/plans/` markdown files are the requirements + implementation plan I wrote before writing the code; they're checked in to make the engineering process visible to reviewers.

## License

MIT — see `LICENSE`.
