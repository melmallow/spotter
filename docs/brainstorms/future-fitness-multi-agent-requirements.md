---
date: 2026-06-02
topic: future-fitness-multi-agent
---

# Future Fitness Multi-Agent System — Requirements

## Summary

A LangGraph hub agent routes user requests across three intents (`COACH`, `WORKOUT_GENERATE`, `WORKOUT_LOG`) to specialized sub-agents, returning grounded fitness coaching responses backed by a 50-exercise dataset. The system targets the Future Research AI Engineer take-home and ships as a public GitHub repo with tests, a runnable single-page web demo styled to Future.co's brand, and a production-evaluation README section. Anthropic Claude provides LLM capabilities (haiku tier for routing and log extraction, sonnet tier for coaching and workout generation), with structured logging for observability, automatic bilateral-exercise pairing, and joints-loaded-based injury filtering layered on top of the PRD baseline.

---

## Problem Frame

The Future Research hiring team needs to evaluate whether a candidate can compose a small but correct multi-agent system end-to-end: typed graph state, separated sub-agents, schema-bound tools, LLM-driven structured output for routing, and graceful failure under ambiguous input or empty tool results. The reviewer reads the repo, runs the demo, and reads the README evaluation section — these are the surfaces where signal lands. A build that adds three carefully chosen production-thinking stretches (observability, bilateral pairing, injury filtering) demonstrates judgment about what matters in deployment without bloating scope past the assessment's 2–3 hour intent. Aesthetic fidelity to Future.co matters because the company explicitly grades on product taste alongside engineering: a generic-looking demo signals less care than one that visually fits the product context the assessment is named after.

---

## Actors

- A1. End user (in-app): Types natural-language fitness messages through the demo UI; receives coaching answers, generated workouts, or log confirmations.
- A2. Hub agent: A LangGraph `StateGraph` that classifies intent via LLM structured output, attaches a confidence score, and routes to one sub-agent or to a clarification path.
- A3. Workout Generator sub-agent: A separate `StateGraph` that calls `search_exercises` then `build_workout` to assemble a warmup/main/cooldown plan.
- A4. Workout Logger sub-agent: A separate `StateGraph` that extracts structured set/rep/weight data from prose and fuzzy-matches the exercise name against the dataset.
- A5. Coach sub-agent: A separate `StateGraph` running a plain Claude call answering knowledge-style questions (no tools) with guardrails to stay in the fitness domain.
- A6. Assessment reviewer (downstream): Reads the repo, runs the demo, evaluates against the PRD checklist and the production-evaluation README section.

---

## Key Flows

- F1. Confident routing → sub-agent → response
  - **Trigger:** End user submits a message in the demo UI.
  - **Actors:** A1, A2, one of A3/A4/A5.
  - **Steps:** Hub receives input → router LLM emits `{route, confidence}` via `with_structured_output` → confidence above threshold → graph edge fires to selected sub-agent → sub-agent returns its structured output → hub composes the user-facing reply.
  - **Outcome:** End user sees a route-appropriate response; structured-log event records route, confidence, latency, and tool calls.
  - **Covered by:** R1, R2, R3, R4, R8, R11, R13, R26.

- F2. Low-confidence routing → clarification
  - **Trigger:** Router emits confidence below threshold (or `UNKNOWN` route).
  - **Actors:** A1, A2.
  - **Steps:** Hub detects low confidence → graph routes to a clarification node → node returns a short prompt naming the two most likely routes → end user re-submits with disambiguation → hub re-routes.
  - **Outcome:** No silent misroute; end user sees the system's uncertainty and corrects it.
  - **Covered by:** R5, R16.

- F3. Workout generation with bilateral pairing + injury filter
  - **Trigger:** Router selects `WORKOUT_GENERATE`.
  - **Actors:** A1, A3.
  - **Steps:** Generator parses user constraints (duration, target muscles, equipment, optional joints-to-avoid) → calls `search_exercises` filtered by those constraints, automatically excluding exercises loading avoided joints → calls `build_workout` to assemble warmup/main/cooldown with sets/reps/rest → for any selected unilateral exercise, the paired side is auto-added → final workout returned as structured JSON.
  - **Outcome:** End user receives a workout that respects time, equipment, and injury constraints, with both sides covered for unilateral movements.
  - **Covered by:** R6, R7, R8, R9, R27, R28.

- F4. Workout logging via fuzzy match
  - **Trigger:** Router selects `WORKOUT_LOG`.
  - **Actors:** A1, A4.
  - **Steps:** Logger LLM extracts `{exercise_name_raw, sets, reps, weight, unit}` via structured output → fuzzy-matches `exercise_name_raw` against the dataset → returns matched exercise ID plus normalized log entry → hub confirms the log to the end user with the canonical exercise name.
  - **Outcome:** End user gets back a structured log entry referencing a real dataset exercise; ambiguous matches surface alternatives instead of silently picking one.
  - **Covered by:** R10, R11, R12, R15.

- F5. Resilient empty-search recovery
  - **Trigger:** `search_exercises` returns zero results (e.g., unsupported equipment requested).
  - **Actors:** A1, A3.
  - **Steps:** Tool returns an empty list with an explanatory `reason` field → generator sub-agent catches the empty result → returns a structured "no match" response naming what was unavailable and suggesting the nearest covered option → hub surfaces this to the end user without fabricating exercises.
  - **Outcome:** End user gets an honest "I don't have that equipment but here's the closest fit" reply; no hallucinated exercise IDs.
  - **Covered by:** R14, R15.

---

## Requirements

**Hub graph and routing**

- R1. Hub is implemented as a LangGraph `StateGraph` with a typed `TypedDict` (or Pydantic) state carrying at least: `user_input`, `route`, `confidence`, `sub_agent_output`, `final_response`, `messages`, and a `clarification_needed` flag.
- R2. Graph edges between nodes are explicit (`add_edge` / `add_conditional_edges`) — no implicit fall-through, no inlined sub-agent logic in the hub node.
- R3. Router node uses an LLM with `with_structured_output(RouteDecision)` where `RouteDecision` is a Pydantic schema containing `route: Literal["COACH","WORKOUT_GENERATE","WORKOUT_LOG","UNKNOWN"]`, `confidence: float` in `[0,1]`, and `reasoning: str`.
- R4. Routing is decided purely by the structured-output result — no regex or keyword shortcuts override it.
- R5. When `confidence < 0.6` or `route == "UNKNOWN"`, the graph routes to a clarification node that returns a short user-facing question naming the two most likely routes; the system never silently picks a low-confidence route.

**Sub-agents (composed graphs)**

- R6. Workout Generator is implemented as its own `StateGraph` and composed into the hub via subgraph composition (not as an inlined function call).
- R7. Workout Logger is implemented as its own `StateGraph` and composed into the hub via subgraph composition.
- R8. Coach is implemented as its own `StateGraph` (single LLM call, no tools), composed into the hub via subgraph composition.
- R9. Workout Generator is a tool-calling agent exposing `search_exercises` and `build_workout` tools; the generator decides tool order via the LLM, not a hard-coded sequence.

**Tools and schemas**

- R10. Workout Logger uses `with_structured_output(LogEntry)` to extract `exercise_name_raw`, `sets`, `reps`, `weight`, and `weight_unit` from the user message.
- R11. The Logger fuzzy-matches `exercise_name_raw` against the dataset using token-set similarity (e.g., RapidFuzz `token_set_ratio`); the top match must clear a score threshold to be returned as resolved.
- R12. Logger returns a structured `LogEntry` JSON containing the matched exercise ID, the canonical exercise name, and the parsed set/rep/weight fields; unresolved matches surface the top 3 candidates rather than guessing.
- R13. Coach sub-agent answers exercise-knowledge questions; an in-prompt scope guard nudges off-topic questions back to fitness.
- R17. Every tool (`search_exercises`, `build_workout`) has a Pydantic input schema with `Field(description=...)` on every field; `build_workout`'s schema validates that selected exercises exist in the dataset.

**Resilience**

- R14. When `search_exercises` returns no results, the tool returns an empty list with a structured `reason` field; the generator surfaces a non-hallucinated "no match" reply naming what was unavailable.
- R15. The hub catches `pydantic.ValidationError` (e.g., the LLM emits a malformed tool call or unknown exercise ID) and returns a user-facing apology + structured log of the malformed call — no uncaught exception.
- R16. Routing errors (LLM call fails, structured output cannot be parsed) fall back to the clarification node rather than crashing the graph.

**Testing**

- R20. The repo includes at least two `pytest` critical-path tests with a short `tests/README.md` (or top-of-file docstring) explaining *why these two paths matter most*. Recommended: (a) ambiguous routing → clarification path (highest-leverage routing correctness check), and (b) `search_exercises` returns empty → no-hallucination recovery (highest-leverage resilience check).
- R21. Tests stub the LLM via `langchain-core`'s fake chat model (or equivalent) so they are deterministic and free to run; no real API calls in CI.

**Demo + submission**

- R22. A FastAPI app serves a single HTML page that posts user input to a `POST /chat` endpoint and renders the response inline (no SPA framework). Page is styled with Tailwind via CDN to match Future.co's aesthetic: dark navy (#0b1a2a-ish) + teal accent (#00d4d4-ish) on white, rounded buttons, generous whitespace, modern geometric sans-serif (Inter or similar), mobile-first layout.
- R23. The demo persists nothing across page reloads in v1 — state lives in-memory in the FastAPI process.
- R24. `README.md` covers: setup (`uv sync`, env vars), running the demo, running tests, an architecture diagram (Mermaid is fine) of the hub + sub-agents, a transcript of one example per route, design decisions, known limits, and a dedicated **"How I would evaluate this system in production"** section covering metrics, failure modes, dashboards, and known-good signals.
- R25. The repo is pushed to a public GitHub repository with a permissive license (MIT) and a `.gitignore` excluding `.env` and Python build artifacts.

**Observability (stretch)**

- R26. Every routing decision, tool call, and sub-agent invocation emits a structured JSON log line via `structlog` containing: `trace_id`, `route`, `confidence`, `latency_ms`, `tool_name` (when applicable), `success`, and any caught error class. Logs are written to stdout and to `logs/trace.jsonl` for the demo.

**Bilateral pairing (stretch)**

- R27. `build_workout` inspects each selected exercise's `is_bilateral` / `bilateral_pair_id`; when `is_bilateral == false` and a `bilateral_pair_id` exists in the dataset, the paired exercise is auto-included as the next set so both sides are covered without the LLM having to remember the rule.

**Injury filtering (stretch)**

- R28. `search_exercises` accepts an optional `avoid_joints: list[str]` parameter (Pydantic-described); any exercise whose `joints_loaded` intersects the list is excluded from results. The generator extracts `avoid_joints` from the user message via the same structured-output pattern as the logger.

---

## Acceptance Examples

- AE1. **Covers R3, R4.** Given the input "Build me a 30 min upper body session with dumbbells", when the router runs, then the structured output returns `route="WORKOUT_GENERATE"` with `confidence >= 0.8`, and the graph edge fires to the Workout Generator subgraph.

- AE2. **Covers R5, R16.** Given the input "Bench press", when the router runs, then the structured output returns either `route="UNKNOWN"` or any route with `confidence < 0.6`, and the graph routes to the clarification node, which returns a message asking the user whether they want to *log*, *generate*, or *learn about* the bench press.

- AE3. **Covers R10, R11, R12.** Given the input "I just did 3x10 bench press at 185 lbs", when the Logger runs, then the structured output contains `sets=3`, `reps=10`, `weight=185`, `weight_unit="lbs"`, and the fuzzy match resolves `exercise_name_raw="bench press"` to the dataset's canonical `Barbell Flat Bench Press` (or equivalent) with a score above threshold.

- AE4. **Covers R14, R15.** Given the input "Build me a workout using a kettlebell" when the dataset contains no kettlebell exercises, when `search_exercises` runs, then the tool returns an empty list with `reason="no exercises matched equipment=kettlebell"`, and the Generator returns a user-facing reply naming kettlebells as unavailable and offering the closest covered alternative — no fabricated kettlebell exercise IDs appear in the response.

- AE5. **Covers R27.** Given a generated workout selecting `Bulgarian Split Squat (left)` (a unilateral exercise with `bilateral_pair_id` pointing to the right-side variant), when `build_workout` finalizes the plan, then the right-side variant is auto-appended as the next set with matching sets/reps/rest.

- AE6. **Covers R28.** Given the input "Build me a lower body workout but avoid my knees", when the Generator extracts `avoid_joints=["knee"]` and calls `search_exercises`, then exercises whose `joints_loaded` includes `"knee"` are excluded from the returned candidate list before `build_workout` selects from them.

---

## Success Criteria

- The assessment reviewer can clone the repo, follow the README, and have the demo running with `uv sync && uv run python -m app` (or equivalent) within ~5 minutes.
- All five flows (F1–F5) execute end-to-end with no uncaught exceptions, and the two critical-path tests pass via `uv run pytest`.
- The "How I would evaluate this system in production" README section names at least: (a) routing accuracy + a way to measure it offline against labeled prompts, (b) tool-call validity rate, (c) empty-search rate as a coverage signal, (d) p50/p95 latency per route, (e) hallucination spot-checks for the COACH path, and (f) the failure modes the reviewer can grep the structured logs for.
- The demo's visual identity reads as "this candidate looked at Future.co before shipping" — same color register, same calm/modern feel, no default-template look.
- A downstream planner could read this doc and start implementation without inventing product behavior, route semantics, or success thresholds.

---

## Scope Boundaries

- No streaming responses — all responses are returned as a single JSON payload from `/chat`.
- No multi-turn conversation memory — each `/chat` request is independent; clarification re-routing happens within a single round-trip via the user re-submitting.
- No Langfuse or OpenTelemetry — observability is structured JSON logs only.
- No authentication, accounts, or persistence of logs across runs.
- No mobile-native UI, no voice input, no calorie/nutrition coverage.
- No content beyond the supplied 50-exercise dataset — Coach answers about exercises not in the dataset use the LLM's general knowledge and the Coach prompt explicitly invites the user to verify.
- No CI pipeline configured — tests run locally; reviewer expectation is a documented local run.

---

## Key Decisions

- **Anthropic Claude with tier split (haiku for routing + log extraction, sonnet for coach + workout generation).** Haiku is fast + cheap, ideal for structured-output classification where latency and cost dominate; sonnet is reserved for generative coaching and tool-orchestrated workout assembly where quality dominates.
- **Confidence threshold of 0.6 with clarification path.** A single tunable threshold is the cheapest correct mechanism; clarification (not silent fallback) preserves the user's trust per the PRD's "make the decision explicit" directive.
- **Sub-agents as separate `StateGraph` subgraphs.** The PRD calls this out explicitly; it also lets each sub-agent be unit-tested in isolation.
- **FastAPI + single-page Tailwind HTML over Streamlit.** "Simple web view is fine" per PRD, but Streamlit's defaults visually clash with Future.co's brand; a hand-rolled page is closer in effort and lands the aesthetic.
- **`uv` + `pyproject.toml` + `src/` layout.** Fast install for the reviewer, modern Python defaults, no `requirements.txt` drift.
- **RapidFuzz `token_set_ratio` for exercise-name fuzzy match.** Handles word reordering ("flat bench press" vs "bench press flat") and partial matches better than `fuzz.ratio` or Levenshtein.
- **Bilateral pairing applied automatically inside `build_workout`, not exposed as a toggle.** The dataset says these are paired exercises; the user shouldn't have to ask for the other side.
- **`avoid_joints` extracted from the user message via structured output, not a manual flag.** Matches how `WORKOUT_LOG` parses set/rep/weight — same pattern, less surface.

---

## Dependencies / Assumptions

- The reviewer has Python 3.11+, `uv` (or `pip` as fallback), and an `ANTHROPIC_API_KEY` available.
- `exercises.json` lives at the repo root and matches the schema documented in the assessment README (50 exercises, fields `muscle_groups`, `joints_loaded`, `movement_patterns`, `equipment_required`, `priority_tier`, `is_bilateral`, `bilateral_pair_id`). **Unverified** — to confirm in planning by reading the file from the assessment repo.
- LangGraph's subgraph composition API supports the typed-state shape we need (`add_subgraph` / compiled `Graph` nodes) at the current pinned version. **Unverified** — to confirm in planning by checking the installed LangGraph version.
- Anthropic's `with_structured_output()` integration in `langchain-anthropic` reliably returns valid Pydantic models for routing (claude-haiku-4-5) and is supported at the version we pin. **Reasonable default** — to validate during the first run; the resilience requirement R15/R16 already covers the failure path if it doesn't.
- Future.co's brand colors are inferred from public marketing pages (dark navy + teal on white). Hex values are approximations and will be adjusted from a live screenshot during implementation.

---

## Outstanding Questions

### Resolve Before Planning

- None — all product decisions are settled above.

### Deferred to Planning

- [Affects R22][Technical] Exact Tailwind color tokens for the Future.co palette — pull from a current screenshot during planning rather than guessing.
- [Affects R3, R10][Needs research] Whether `langchain-anthropic`'s `with_structured_output()` returns confidence natively or whether the router prompt must explicitly request it as a Pydantic field — verify during planning.
- [Affects R26][Technical] Whether `structlog`'s context-binding API is the cleanest way to carry `trace_id` across sub-agent boundaries, or whether LangGraph's `RunnableConfig` callbacks are a better fit — settle during planning.
- [Affects R27][Technical] How `bilateral_pair_id` is populated in the dataset (pointer to canonical bilateral entry, or pair-of-pointers in both unilateral entries) — read `exercises.json` during planning to confirm.
