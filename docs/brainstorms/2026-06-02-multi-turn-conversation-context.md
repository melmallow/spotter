# Multi-Turn Conversation Context — Design

**Status:** Draft — awaiting user review
**Date:** 2026-06-02
**Branch:** `fix/logger-movement-pattern-bias` (this work will start a new branch)
**Supersedes (partial):** the "No multi-turn conversation memory" constraint in `docs/brainstorms/future-fitness-multi-agent-requirements.md` (line 156). That constraint was a v1 simplification; this spec is the v2 lift.

## 1. Problem

Each `/chat` request is currently stateless. The hub starts fresh, the router classifies in isolation, every sub-agent sees only the single latest user message. Two concrete failure modes the user hit in the running app:

1. **Disambiguation dead-end.** Logger asks "I couldn't confidently match 'bicep curls'. Did you mean one of: 'Resistance Band Reverse Curl', 'Single-Arm Dumbbell Preacher Curl', 'Wide-Grip Preacher Curl with EZ Bar'?" The user replies "yeah - Single-Arm Dumbbell Preacher Curl". The hub re-routes from scratch, the router sees a short reply with no verb and falls through to UNKNOWN, the user gets the generic "I'm not sure what you meant" clarification. The log is lost.
2. **No conversational follow-up.** "What muscles does a deadlift work?" works. "How about the conventional one?" fails — coach has no idea what was previously asked.

The fix: real multi-turn conversation memory. The agent should hand down context, and any sub-agent (router included) should be able to interpret a new message in light of the prior turns.

## 2. Goals & non-goals

**Goals:**
- The router can interpret short follow-ups ("yeah, that one", "how about the conventional one?") by reading prior turns.
- Each sub-agent receives trimmed conversation history and can interpret the new user message against it.
- The screenshot scenario (logger disambiguation → user picks a candidate → log succeeds) works end-to-end without a special "resume" path or carry slot.
- The web layer is unchanged in surface area: same `POST /chat`, plus one new field `conversation_id`.
- A LangGraph-literate reviewer reads the code and immediately recognizes the pattern.

**Non-goals:**
- Persistence across page reloads or server restarts. State is in-memory only.
- Authentication, multi-user sessions, or any concept of users.
- Generator-edit functionality ("swap the second exercise"). Sub-agents will all receive history, but the generator does not get a special edit path in this spec. It is a follow-up.
- Cross-conversation memory or "user remembers I prefer dumbbells."

## 3. Approach: LangGraph checkpointer + `thread_id`

Use LangGraph's built-in checkpointer mechanism. The graph is compiled with a `MemorySaver`; each `/chat` invocation passes `config={"configurable": {"thread_id": conversation_id}}`. LangGraph rehydrates state for the thread, merges the new `HumanMessage` into `messages` via the `add_messages` reducer, runs the graph, persists the result.

**Alternatives considered.**

- **Custom in-memory conversation store keyed by id, holding a transcript list, with carry slots for structured handoffs.** Standard framework-agnostic pattern, works fine, but rolls custom infrastructure that LangGraph already provides. A reviewer wouldn't immediately recognize the pattern.
- **Two-tier: stateless hub with a pre-router continuation check.** Only addresses the disambiguation dead-end, not real multi-turn. Coach follow-ups and any future generator edits still fail. Rejected.

The checkpointer approach is more idiomatic for LangGraph and the right shape for what we actually want. The one consideration is that `HubState` mixes conversation-scoped fields (`messages`) with turn-scoped fields (`route`, `confidence`, `clarification_needed`, `sub_agent_output`, `final_response`). The checkpointer persists all of them. We handle this by guaranteeing the router always overwrites the four routing fields and every terminal node always overwrites `sub_agent_output` and `final_response`. The current router error path already does this (`agents/router.py:54-60`); sub-agents already do this. No staleness in practice.

## 4. Architecture

```
Browser ──conversation_id, message──► FastAPI /chat
                                          │
                                          ▼
                              hub.invoke(
                                input  = {messages: [HumanMessage(user_input)], trace_id},
                                config = {configurable: {thread_id: conversation_id}}
                              )
                                          │
                                          ▼
                              ┌── MemorySaver checkpointer ──┐
                              │  loads state for thread_id   │
                              │  merges input (add_messages  │
                              │  appends HumanMessage)       │
                              └──────────────┬───────────────┘
                                             ▼
                                          router
                                             │
                                             ▼
                                    coach / generator /
                                    logger / clarification
                                             │
                                             ▼
                              ┌── checkpointer persists ─────┐
                              │  appended AIMessage,         │
                              │  turn-scoped fields, etc.    │
                              └──────────────┬───────────────┘
                                             ▼
                                  final state returned;
                                  web extracts final_response
```

**Components touched:**

- `src/spotter/hub.py` — `build_hub()` accepts a `checkpointer` kwarg, defaults to `MemorySaver()`. `run_hub()` takes a `conversation_id`, passes it as `thread_id`, builds input as `{"messages": [HumanMessage(content=user_input)], "trace_id": trace_id}`.
- `src/spotter/schemas.py` — `HubState.messages` gets `Annotated[..., add_messages]`; `HubState.user_input` removed.
- `src/spotter/agents/router.py` — reads `state["messages"]`, trims, passes the full history (system prompt + trimmed messages) to the LLM.
- `src/spotter/agents/logger.py` — reads `state["messages"]`, trims, passes history to the extractor LLM; system prompt updated to handle disambiguation-reply context.
- `src/spotter/agents/coach.py` — reads `state["messages"]`, trims, passes history.
- `src/spotter/agents/generator.py` — reads `state["messages"]`, trims, passes history. No carry slot for `last_workout` in this spec.
- `src/spotter/agents/clarification.py` — unchanged (operates on `route_reasoning`, not history).
- All terminal nodes — return `{"messages": [AIMessage(content=final_response)], ...}` so the transcript stays consistent via the `add_messages` reducer.
- `src/spotter/conversations.py` — new module, ~30 lines. Exports `trim_history(messages, max_turns)` and the `MAX_HISTORY_TURNS = 8` constant. No store, no class — the checkpointer is the store.
- `src/spotter/web/app.py` — `ChatRequest` gets a required `conversation_id: str` field; the `/chat` handler passes it through to `run_hub`.
- `src/spotter/web/templates/index.html` — mints `crypto.randomUUID()` on page load, sends `conversation_id` in every `/chat` body.

**No graph topology change.** Same nodes, same edges, same conditional routing logic.

## 5. Data model

```python
class HubState(TypedDict, total=False):
    # Conversation-scoped (persist across turns via checkpointer)
    messages: Annotated[list[BaseMessage], add_messages]

    # Turn-scoped (always overwritten by router + terminal node on every clean turn)
    route: Route
    confidence: float
    route_reasoning: str
    clarification_needed: bool
    sub_agent_output: dict[str, Any]
    final_response: str
    trace_id: str
```

Removed: `HubState.user_input`. Each node reads the latest user input from `state["messages"][-1].content` when needed.

No carry slots. The LLM extractors with full message history handle disambiguation replies natively — see §6 worked example.

## 6. Data flow (per-turn lifecycle)

1. Web layer mints `trace_id`, calls `hub.invoke(input, config={"configurable": {"thread_id": conversation_id}})` where `input = {"messages": [HumanMessage(content=msg)], "trace_id": trace_id}`.
2. Checkpointer loads prior state for the thread. The new `HumanMessage` is appended to `messages` via the `add_messages` reducer.
3. Router reads `state["messages"]`, trims to last `2 * MAX_HISTORY_TURNS` items via `trim_history`, calls the LLM with `[system_prompt, *trimmed]`. Writes `route`, `confidence`, `route_reasoning`, `clarification_needed`.
4. Conditional edge `_route_selector` reads `route` and `clarification_needed`, picks a terminal node. Unchanged.
5. Terminal node (logger / coach / generator / clarification) reads `state["messages"]`, trims, runs its work, returns `{"sub_agent_output": ..., "final_response": text, "messages": [AIMessage(content=text)]}`.
6. Checkpointer persists. Web layer pulls `final_response`, `route`, `confidence` from the returned state. Returns JSON to browser.

**Worked example — the screenshot scenario:**

```
Turn 1 — user: "i just did 3 sets of 10 rep of 10lb bicep curls"
  state.messages becomes [HumanMessage(t1)]
  router → WORKOUT_LOG, conf 0.9
  logger.extract → LogEntry(sets=3, reps=10, weight=10,
                             exercise_name_raw="bicep curls", keyword="curl")
  logger.match → no candidate >= threshold; returns top 3
  writes:
    final_response = "I couldn't confidently match 'bicep curls'. Did you mean..."
    messages becomes [HumanMessage(t1), AIMessage(disambig)]

Turn 2 — user: "yeah - Single-Arm Dumbbell Preacher Curl"
  state.messages becomes [HumanMessage(t1), AIMessage(disambig), HumanMessage(t2)]
  router sees the prior assistant question → WORKOUT_LOG, conf ~0.95
  logger.extract called with the full message history → returns
    LogEntry(sets=3, reps=10, weight=10,
             exercise_name_raw="Single-Arm Dumbbell Preacher Curl", keyword="curl")
  logger.match → fuzzy 95+ against exact canonical name
  writes:
    final_response = "Logged: 3x10 Single-Arm Dumbbell Preacher Curl at 10 lbs."
    messages becomes [..., AIMessage("Logged: ...")]
```

The logger's behavior change is two things only: (a) pass `messages` (trimmed) into the extractor instead of just the latest user input, and (b) add one or two sentences to `LOGGER_SYSTEM_PROMPT` telling the extractor that the prior assistant turn may be a disambiguation question and to merge sets/reps from the original log with the exercise the user just picked.

## 7. Error handling

**Failures inside the graph (router or sub-agent raises).** Caught by `run_hub`'s existing `try/except`. User gets the canned error response. By the time the exception fires, `add_messages` has already appended the new `HumanMessage` to the transcript. There will be **no matching `AIMessage`** for this turn — the transcript is left unbalanced. We don't patch it with a synthetic apology. Reasons: keeps the failure observable in logs, the LLM handles odd transcripts fine on the next turn, and inserting fake assistant text would mislead the next turn's classification.

**Stale turn-scoped fields after a graph failure.** Not a risk in practice:
- Router error path already overwrites `route`, `confidence`, `route_reasoning`, `clarification_needed`. Even on consecutive router failures, those four fields are always fresh.
- If the router succeeds but a sub-agent crashes mid-execution: `route` / `confidence` / `clarification_needed` are still freshly written by the router; only `sub_agent_output` and `final_response` are missing for this turn. The next turn's router rewrites the four turn-scoped fields and the next sub-agent rewrites the other two.

**Pydantic validation failure in a sub-agent's structured output.** Same as today — caught at `run_hub` level. Existing canned validation-error response. Transcript stays unbalanced for that turn.

**Missing or invalid `conversation_id` in `/chat` body.** `ChatRequest.conversation_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")`. Pydantic rejects malformed values with a 422. If omitted, FastAPI returns 422. We don't paper over it — the frontend always sends one (minted at page load), so a missing id signals a real client bug worth seeing.

**Concurrent requests on the same `conversation_id`.** Possible if a user double-submits before the first response returns. `MemorySaver` isn't transactional — last-writer-wins, one turn's state can be partially overwritten. Mitigations: the frontend already serializes (`send()` awaits the previous fetch), and we add no server-side lock. Known limitation.

**History trimming boundary.** `trim_history(messages, max_turns)` returns the last `2 * max_turns` items but drops a leading orphan `AIMessage` if trimming cut mid-turn. Guarantees the trimmed list starts with a `HumanMessage`.

**First turn (empty prior state).** Checkpointer returns empty state for a new `thread_id`. `add_messages` merges the input `HumanMessage` into an empty list. Router sees a one-message history. No special-case code needed.

**Memory bound.** `MemorySaver` retains every checkpoint for every thread for the process lifetime. For a demo this is fine; over a long-running session it grows. Known limitation; production fix would be `SqliteSaver` with TTL cleanup, out of scope here.

**Logging additions.** `bind_contextvars(trace_id=..., conversation_id=...)` so every log line tags both. Existing `logging_setup.py` already supports binding additional keys.

## 8. Testing

One new critical-path test, two updates to existing tests, manual browser walkthrough.

**New: `tests/test_multiturn_disambiguation.py` (critical-path #3).** The screenshot scenario, end-to-end. Builds a hub with a `MemorySaver` and stubbed LLMs:
- Router stub returns `WORKOUT_LOG` on both turns.
- Logger extractor stub on turn 1 returns `LogEntry(sets=3, reps=10, weight=10, exercise_name_raw="bicep curls", keyword="curl")`.
- Logger extractor stub on turn 2, having received the full message history including the assistant's disambiguation question, returns `LogEntry(sets=3, reps=10, weight=10, exercise_name_raw="Single-Arm Dumbbell Preacher Curl", keyword="curl")`.

Asserts:
- Turn 1 `final_response` contains "couldn't confidently match" and offers candidates.
- Turn 2 `final_response` contains "Logged: 3x10 Single-Arm Dumbbell Preacher Curl at 10 lbs".
- Turn 2's logger extractor received a message history that included both turn 1's user message and the assistant's disambiguation question (verified by inspecting what the stub was called with).
- Both invocations used the same `thread_id`.
- Inline assertion: a second `thread_id` doesn't see the first conversation's messages.

**Updated: `tests/test_router_clarification.py` and `tests/test_generator_empty_search.py`.** Input shape changes from `{"user_input": "..."}` to `{"messages": [HumanMessage(content="...")]}`. Assertions unchanged. Confirms no regression in the original two critical paths.

**Updated: `tests/conftest.py`.** Add a fixture `multiturn_hub(checkpointer=None)` that wraps `build_hub` with an explicit `MemorySaver` so test cases can drive multiple turns against the same `thread_id`. Existing single-turn tests keep using their existing fixture (no checkpointer) — proves the graph still works without one too.

**Unit test on the trim helper.** `test_trim_history` in the same file as the multiturn test: build a 20-message list, assert `trim_history(msgs, max_turns=8)` returns 16 messages, asserts the returned list starts with a `HumanMessage` even when the cut would naturally land on an orphan `AIMessage`.

**Deliberately not tested:**
- Concurrent same-thread_id requests. Known limitation.
- `MemorySaver` memory bound. Known limitation.
- Real-Claude multi-turn behavior. The evals suite exists for that; adding a multi-turn eval scenario is a follow-up.

**Manual verification before declaring done.** Restart dev server, open browser, walk the screenshot scenario:
1. "i just did 3 sets of 10 rep of 10lb bicep curls" → expect disambiguation.
2. "yeah - Single-Arm Dumbbell Preacher Curl" → expect "Logged: 3x10 ..." with the canonical name and weight.
3. Refresh page, repeat first message, then ask coach a question — confirm new conversation has no leaked state from the prior one.

## 9. Open questions

None at design-approval time. Implementation may surface small choices (e.g., whether `trim_history` lives in `conversations.py` or `schemas.py`) — those are implementation-plan-scoped, not spec-scoped.

## 10. Follow-ups (explicitly out of scope)

- Generator edit support (`last_workout` carry, edit-shaped extractor prompt, `swap`/`replace`/`shorten` operations).
- Multi-turn eval scenarios in the `evals/` suite.
- Persistence to disk (`SqliteSaver`) + TTL cleanup.
- Conversation reset endpoint (`POST /chat/reset` with a `conversation_id`).
