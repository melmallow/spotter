# Multi-Turn Conversation Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real multi-turn conversation memory to the hub so each `/chat` carries prior turns forward, fixing the logger disambiguation dead-end and enabling coach/generator follow-ups.

**Architecture:** LangGraph `MemorySaver` checkpointer keyed by `thread_id = conversation_id`. The shared `HubState.messages` field gets an `add_messages` reducer so updates append. Each sub-agent reads trimmed history and emits its final response as an `AIMessage` delta. The generator gets a dedicated `generator_scratch` field for its tool-call loop so its working messages don't pollute the conversation transcript.

**Tech Stack:** Python 3.14, LangGraph (`langgraph.checkpoint.memory.MemorySaver`, `langgraph.graph.message.add_messages`), LangChain (`BaseMessage`, `HumanMessage`, `AIMessage`), FastAPI, pytest, `FakeMessagesListChatModel`-based stubs.

**Spec:** `docs/brainstorms/2026-06-02-multi-turn-conversation-context.md`

---

## File Structure

**New files:**
- `src/spotter/conversations.py` — `trim_history()` helper. ~30 lines, single responsibility (trim a message list to last N turns, dropping leading orphan AIMessages).
- `tests/test_multiturn_disambiguation.py` — critical-path test #3: the screenshot scenario end-to-end.

**Modified files:**
- `src/spotter/config.py` — add `MAX_HISTORY_TURNS = 8`.
- `src/spotter/schemas.py` — `HubState.messages` gets `Annotated[..., add_messages]`; new `generator_scratch` field; `user_input` is removed.
- `src/spotter/agents/router.py` — read trimmed `state["messages"]`, pass as message list to LLM.
- `src/spotter/agents/coach.py` — read trimmed messages, return AIMessage delta.
- `src/spotter/agents/clarification.py` — return AIMessage delta so disambiguation question lands in transcript.
- `src/spotter/agents/logger.py` — read trimmed messages in `_extract`, update `LOGGER_SYSTEM_PROMPT` for disambiguation-reply context, both nodes return AIMessage deltas.
- `src/spotter/agents/generator.py` — new `_init_scratch` node; `_agent_node`/`_tools_node`/`_should_continue`/`_finalize` read/write `generator_scratch`; `_finalize` emits AIMessage delta to shared `messages`.
- `src/spotter/hub.py` — `build_hub()` accepts `checkpointer` kwarg (default `MemorySaver()`); `run_hub()` takes `conversation_id`, builds input with `HumanMessage`, passes `thread_id` in config. Preserves existing `_resolved_log_entry` logic.
- `src/spotter/web/app.py` — `ChatRequest.conversation_id` field; `/chat` handler passes it through.
- `src/spotter/web/templates/index.html` — mint `crypto.randomUUID()` on page load, send `conversation_id` in every `/chat` body.
- `tests/conftest.py` — add `multiturn_hub` fixture that wraps `build_hub` with an explicit `MemorySaver`.
- `tests/test_router_clarification.py` — input shape change from `{"user_input": "..."}` to `{"messages": [HumanMessage(content="...")]}`.
- `tests/test_generator_empty_search.py` — same input shape change.
- `tests/test_logger_movement_bias.py` — same input shape change.

**Files this plan deliberately leaves alone:**
- `src/spotter/data.py`, `src/spotter/llm.py`, `src/spotter/logging_setup.py`, `src/spotter/tools/*.py` — not in scope.
- `src/spotter/evals/*` — multi-turn eval scenarios are a follow-up (spec §10).
- The in-progress `_resolved_log_entry` (`hub.py`), static-files mount (`web/app.py`), `log_entry` response field, and `index.html` redesign — preserved as-is; this plan builds on top of them.

---

## Task 1: Add `trim_history` helper and history-window constant

**Files:**
- Create: `src/spotter/conversations.py`
- Modify: `src/spotter/config.py` (add one constant)
- Test: `tests/test_conversations.py` (new)

- [ ] **Step 1: Add the `MAX_HISTORY_TURNS` constant**

Modify `src/spotter/config.py` — after line 22 (`FUZZY_MATCH_THRESHOLD`), add:

```python
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "8"))
```

- [ ] **Step 2: Write failing tests for `trim_history`**

Create `tests/test_conversations.py`:

```python
"""Unit tests for the trim_history helper."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from spotter.conversations import trim_history


def _alternating(n: int) -> list:
    """Build a list of n alternating HumanMessage/AIMessage."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(HumanMessage(content=f"u{i}"))
        else:
            out.append(AIMessage(content=f"a{i}"))
    return out


def test_trim_returns_last_2n_when_long():
    msgs = _alternating(20)
    trimmed = trim_history(msgs, max_turns=8)
    assert len(trimmed) == 16
    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "u4"
    assert trimmed[-1].content == "a19"


def test_trim_returns_all_when_short():
    msgs = _alternating(4)
    trimmed = trim_history(msgs, max_turns=8)
    assert len(trimmed) == 4
    assert trimmed == msgs


def test_trim_drops_leading_orphan_ai_message():
    # 17 messages: u0,a1,u2,a3,...,a15,u16. Slice last 16 → starts at a1.
    msgs = _alternating(17)
    trimmed = trim_history(msgs, max_turns=8)
    # After slicing to last 16, a1 is the first; drop it.
    assert len(trimmed) == 15
    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "u2"


def test_trim_empty_list():
    assert trim_history([], max_turns=8) == []


def test_trim_single_human_message():
    msgs = [HumanMessage(content="hello")]
    trimmed = trim_history(msgs, max_turns=8)
    assert trimmed == msgs
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_conversations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spotter.conversations'`.

- [ ] **Step 4: Implement `conversations.py`**

Create `src/spotter/conversations.py`:

```python
"""Conversation helpers — history-window trimming.

The full untrimmed transcript is held by LangGraph's checkpointer keyed by
thread_id. This module only handles the "trim to last N turns before passing
to an LLM" boundary.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage


def trim_history(messages: list[BaseMessage], max_turns: int) -> list[BaseMessage]:
    """Return the last `2 * max_turns` messages, dropping a leading orphan AIMessage.

    A "turn" is one HumanMessage + one AIMessage. The trimmed list is guaranteed
    to start with a HumanMessage so LLM calls don't begin with a dangling
    assistant reply. If trimming would cut mid-turn (leaving an AIMessage at the
    front), drop that orphan.

    Empty input returns empty output. Lists shorter than the window are returned
    unchanged.
    """
    if not messages:
        return []
    keep = 2 * max_turns
    trimmed = messages[-keep:] if len(messages) > keep else list(messages)
    if trimmed and isinstance(trimmed[0], AIMessage):
        trimmed = trimmed[1:]
    return trimmed
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_conversations.py -v`
Expected: all five tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/spotter/conversations.py src/spotter/config.py tests/test_conversations.py
git commit -m "$(cat <<'EOF'
feat(conversations): add trim_history helper + MAX_HISTORY_TURNS

Foundation for multi-turn context: a single helper that trims a BaseMessage
list to the last N turns and guarantees the result starts with a
HumanMessage (drops a leading orphan AIMessage if trimming cut mid-turn).
EOF
)"
```

---

## Task 2: Update `HubState` for shared transcript + generator scratch

**Files:**
- Modify: `src/spotter/schemas.py:14-26`

This task changes the type only. `user_input` stays on the state for now (removed in Task 9 after all agents migrate). Existing tests continue to pass because they pass `user_input` and the agents still read it.

- [ ] **Step 1: Update HubState**

In `src/spotter/schemas.py`, replace the `HubState` definition (lines 14–26) with:

```python
class HubState(TypedDict, total=False):
    """Typed state flowing through the hub StateGraph and its subgraphs.

    Conversation-scoped fields persist across turns via the checkpointer.
    Turn-scoped fields are overwritten on every clean turn — the router
    always rewrites the routing fields, and every terminal node always
    rewrites `sub_agent_output` and `final_response`.
    """

    # ---- Conversation-scoped (persist across turns via checkpointer) ----
    messages: Annotated[list[BaseMessage], add_messages]

    # ---- Turn-scoped (always overwritten) ----
    user_input: str  # legacy mirror of latest HumanMessage; removed in Task 9.
    route: Route
    confidence: float
    route_reasoning: str
    clarification_needed: bool
    sub_agent_output: dict[str, Any]
    final_response: str
    trace_id: str
    error: str

    # ---- Per-turn ephemeral (generator's tool-call loop scratch) ----
    generator_scratch: list[BaseMessage]
```

And add to the imports at the top of `schemas.py` (after the existing imports):

```python
from typing import Annotated

from langgraph.graph.message import add_messages
```

The existing `from typing import Any, Literal, TypedDict` line should be merged with `Annotated`:

```python
from typing import Annotated, Any, Literal, TypedDict
```

- [ ] **Step 2: Verify nothing breaks**

Run: `uv run pytest -v`
Expected: all existing tests still PASS. The schema is backward-compatible — `user_input` is still present, agents still read it, the new `messages` annotation doesn't affect single-turn invocations.

- [ ] **Step 3: Commit**

```bash
git add src/spotter/schemas.py
git commit -m "$(cat <<'EOF'
feat(schemas): HubState.messages uses add_messages reducer

Annotate `messages` so updates append instead of overwrite. Add
`generator_scratch` for the generator's tool-call loop working set.
`user_input` is kept for now as a legacy mirror; it goes away once all
agents migrate to reading messages.
EOF
)"
```

---

## Task 3: Thread `conversation_id` through hub and web layer

**Files:**
- Modify: `src/spotter/hub.py`
- Modify: `src/spotter/web/app.py`
- Modify: `src/spotter/web/templates/index.html`
- Test: `tests/test_conversation_threading.py` (new)

After this task, the plumbing is complete: the browser mints a conversation_id, the web layer forwards it, the hub passes it as the LangGraph thread_id. Agents still read `user_input` — that migration happens in Tasks 4–8.

- [ ] **Step 1: Write failing test for hub's conversation handling**

Create `tests/test_conversation_threading.py`:

```python
"""Conversation-id threading: same id reuses checkpointer state; different ids isolate."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from spotter.hub import build_hub, run_hub
from spotter.schemas import RouteDecision


def test_same_conversation_id_shares_messages(fake_chat_model_factory):
    router_model = fake_chat_model_factory(
        structured=[
            RouteDecision(route="COACH", confidence=0.9, reasoning="anatomy q"),
            RouteDecision(route="COACH", confidence=0.9, reasoning="anatomy q"),
        ]
    )
    coach_model = fake_chat_model_factory(
        responses=[
            AIMessage(content="first reply"),
            AIMessage(content="second reply"),
        ]
    )
    hub = build_hub(
        checkpointer=MemorySaver(),
        router_model=router_model,
        coach_model=coach_model,
    )
    out1 = run_hub(hub, "what muscles does a deadlift work?", conversation_id="conv-A")
    out2 = run_hub(hub, "how about the conventional one?", conversation_id="conv-A")
    assert out1["response"] == "first reply"
    assert out2["response"] == "second reply"


def test_different_conversation_ids_are_isolated(fake_chat_model_factory):
    router_model = fake_chat_model_factory(
        structured=[
            RouteDecision(route="COACH", confidence=0.9, reasoning="q"),
            RouteDecision(route="COACH", confidence=0.9, reasoning="q"),
        ]
    )
    coach_model = fake_chat_model_factory(
        responses=[AIMessage(content="A reply"), AIMessage(content="B reply")]
    )
    hub = build_hub(
        checkpointer=MemorySaver(),
        router_model=router_model,
        coach_model=coach_model,
    )
    run_hub(hub, "question A", conversation_id="conv-A")
    run_hub(hub, "question B", conversation_id="conv-B")
    # If isolated, the checkpointer holds two separate threads — assert by
    # checking the state for each thread.
    state_a = hub.get_state({"configurable": {"thread_id": "conv-A"}}).values
    state_b = hub.get_state({"configurable": {"thread_id": "conv-B"}}).values
    msgs_a = state_a.get("messages", [])
    msgs_b = state_b.get("messages", [])
    assert any(
        isinstance(m, HumanMessage) and m.content == "question A" for m in msgs_a
    )
    assert any(
        isinstance(m, HumanMessage) and m.content == "question B" for m in msgs_b
    )
    assert not any(
        isinstance(m, HumanMessage) and m.content == "question B" for m in msgs_a
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_conversation_threading.py -v`
Expected: FAIL — `run_hub` doesn't accept `conversation_id` yet; `build_hub` doesn't accept `checkpointer` yet.

- [ ] **Step 3: Update `build_hub` to accept a checkpointer**

In `src/spotter/hub.py`, modify the `build_hub` signature and the `.compile()` call. Replace lines 42–76 with:

```python
def build_hub(
    *,
    checkpointer: Any = None,
    router_model: Any = None,
    coach_model: Any = None,
    generator_model: Any = None,
    logger_model: Any = None,
):
    """Compile the full hub graph.

    `checkpointer` enables multi-turn conversation memory via LangGraph
    thread_id. Pass an explicit `MemorySaver()` to enable; pass `None`
    (the default) for stateless single-turn invocation (used by some tests).
    All models are optional injection points for tests.
    """
    router = build_router_subgraph(model=router_model)
    coach = build_coach_subgraph(model=coach_model)
    generator = build_generator_subgraph(model=generator_model)
    logger = build_logger_subgraph(model=logger_model)

    graph = StateGraph(HubState)
    graph.add_node("router", router)
    graph.add_node("clarification", clarification_node)
    graph.add_node("coach", coach)
    graph.add_node("generator", generator)
    graph.add_node("logger", logger)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _route_selector,
        {
            "clarification": "clarification",
            "coach": "coach",
            "generator": "generator",
            "logger": "logger",
        },
    )
    for terminal in ("clarification", "coach", "generator", "logger"):
        graph.add_edge(terminal, END)

    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Update `run_hub` to accept `conversation_id` and pass thread_id**

Add `HumanMessage` to imports at the top of `src/spotter/hub.py`:

```python
from langchain_core.messages import HumanMessage
```

Replace the `run_hub` signature and the body (lines 79–139 in the current file, accounting for the in-progress `_resolved_log_entry` helper added above it) with:

```python
def run_hub(
    hub,
    user_input: str,
    conversation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Invoke the hub with a fresh trace_id binding + a top-level ValidationError catch.

    `conversation_id` is passed as LangGraph's `thread_id` so the checkpointer
    can rehydrate prior conversation state. If omitted, a one-shot UUID is used
    (no cross-turn continuity).
    """
    tid = trace_id or f"req-{uuid.uuid4().hex[:12]}"
    cid = conversation_id or f"oneshot-{uuid.uuid4().hex[:12]}"
    bind_contextvars(trace_id=tid, conversation_id=cid)
    started = time.perf_counter()
    log.info("hub_request", user_input=user_input)
    config = {"configurable": {"thread_id": cid}}
    try:
        out = hub.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_input": user_input,  # legacy mirror; removed in Task 9.
                "trace_id": tid,
            },
            config=config,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "hub_response",
            route=out.get("route"),
            confidence=out.get("confidence"),
            clarification_needed=out.get("clarification_needed", False),
            latency_ms=latency_ms,
        )
        return {
            "response": out.get(
                "final_response", "Sorry — no response was produced."
            ),
            "route": out.get("route"),
            "confidence": out.get("confidence"),
            "trace_id": tid,
            "conversation_id": cid,
            "log_entry": _resolved_log_entry(out),
        }
    except ValidationError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.error(
            "validation_error",
            error_class=type(exc).__name__,
            errors=exc.errors(),
            latency_ms=latency_ms,
        )
        return {
            "response": (
                "Sorry — I tried to build that but the result didn't validate. "
                "Could you rephrase or simplify the request?"
            ),
            "route": None,
            "confidence": None,
            "trace_id": tid,
            "conversation_id": cid,
            "error": "validation_error",
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.error(
            "hub_error",
            error_class=type(exc).__name__,
            error=str(exc),
            latency_ms=latency_ms,
        )
        return {
            "response": (
                "Sorry — something went wrong on our end. Please try again."
            ),
            "route": None,
            "confidence": None,
            "trace_id": tid,
            "conversation_id": cid,
            "error": type(exc).__name__,
        }
    finally:
        clear_contextvars()
```

- [ ] **Step 5: Update `web/app.py` for conversation_id**

In `src/spotter/web/app.py`, replace the `ChatRequest` class (lines 30–34) with:

```python
class ChatRequest(BaseModel):
    """Schema for POST /chat — keeps malformed bodies out of the hub."""

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
```

In the same file, modify the `/chat` handler (find the `async def chat(req: ChatRequest)` block) to pass `conversation_id` and include it in the response. Replace the chat handler body with:

```python
    @app.post("/chat")
    async def chat(req: ChatRequest) -> JSONResponse:
        result = run_hub(hub, req.message, conversation_id=req.conversation_id)
        payload = {
            "response": result["response"],
            "route": result.get("route"),
            "confidence": result.get("confidence"),
            "trace_id": result.get("trace_id"),
            "conversation_id": result.get("conversation_id"),
            "log_entry": result.get("log_entry"),
        }
        return JSONResponse(payload)
```

Also: change `hub = build_hub()` (around line 39) to:

```python
    hub = build_hub(checkpointer=MemorySaver())
```

And add the import at the top:

```python
from langgraph.checkpoint.memory import MemorySaver
```

- [ ] **Step 6: Update `index.html` to mint and send `conversation_id`**

In `src/spotter/web/templates/index.html`, in the `<script>` block, near the top of the script (before `async function send(text)`), add:

```javascript
  const CONVERSATION_ID = crypto.randomUUID();
```

Then modify the body of the `fetch('/chat', ...)` call (currently `body: JSON.stringify({ message: text })`) to:

```javascript
        body: JSON.stringify({ message: text, conversation_id: CONVERSATION_ID })
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_conversation_threading.py -v`
Expected: both tests PASS. The hub now wires conversation_id → thread_id end-to-end.

Run: `uv run pytest -v`
Expected: all existing tests still PASS (they don't pass conversation_id; the default oneshot UUID kicks in).

- [ ] **Step 8: Commit**

```bash
git add src/spotter/hub.py src/spotter/web/app.py src/spotter/web/templates/index.html tests/test_conversation_threading.py
git commit -m "$(cat <<'EOF'
feat(hub): thread conversation_id through hub, web, and frontend

`build_hub` now accepts a checkpointer (default None; web layer passes
MemorySaver). `run_hub` takes a conversation_id and passes it as LangGraph
thread_id. ChatRequest requires a conversation_id; frontend mints one per
page load via crypto.randomUUID() and sends it on every request.

Agents still read state["user_input"]; the per-agent migration follows in
the next tasks. The legacy user_input field on HubState is kept until
Task 9 to keep tests green at every commit.
EOF
)"
```

---

## Task 4: Migrate router to read trimmed messages

**Files:**
- Modify: `src/spotter/agents/router.py:35-79`
- Modify: `tests/test_router_clarification.py` (input shape)

- [ ] **Step 1: Write a failing test for history-aware routing**

Append to `tests/test_router_clarification.py` (or create a new section at the bottom):

```python
def test_router_passes_message_history_to_llm(fake_chat_model_factory):
    """Router should include prior turns in the LLM call, not just the latest input."""
    captured_messages: list = []

    class CapturingModel:
        def with_structured_output(self, schema):
            def _emit(messages):
                captured_messages.extend(messages)
                return RouteDecision(
                    route="WORKOUT_LOG", confidence=0.9, reasoning="log"
                )

            return RunnableLambda(_emit)

    graph = build_router_subgraph(model=CapturingModel())
    history = [
        HumanMessage(content="i did 3x10 bicep curls"),
        AIMessage(content="did you mean X, Y, or Z?"),
        HumanMessage(content="the preacher curl one"),
    ]
    graph.invoke({"messages": history})

    # The router must have passed the full history (system + 3 messages), not just
    # the last input.
    types = [type(m).__name__ if hasattr(m, "content") else m[0] for m in captured_messages]
    assert "system" in types or any(
        t == "SystemMessage" for t in types
    ), f"system prompt missing: {types}"
    assert (
        sum(1 for m in captured_messages if isinstance(m, HumanMessage)) == 2
    ), f"expected 2 HumanMessages in router call, got: {captured_messages}"
```

Also update the imports at the top of `tests/test_router_clarification.py` to include `HumanMessage`, `AIMessage`, and `RunnableLambda`:

```python
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
```

(The file already imports `RouteDecision` from `spotter.schemas`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_router_clarification.py::test_router_passes_message_history_to_llm -v`
Expected: FAIL — router currently passes `("human", user_input)`, not the message list.

- [ ] **Step 3: Update router to read trimmed messages**

In `src/spotter/agents/router.py`, replace the `_classify` function (lines 35–79) with:

```python
def _classify(state: HubState, *, model: BaseChatModel) -> dict[str, Any]:
    """Single router node. Caller injects the model so tests can stub it."""
    messages = state.get("messages") or []
    if not messages:
        # Defensive: callers should always pass a HumanMessage. Treat as UNKNOWN.
        return {
            "route": "UNKNOWN",
            "confidence": 0.0,
            "route_reasoning": "no messages on state",
            "clarification_needed": True,
        }
    trimmed = trim_history(messages, MAX_HISTORY_TURNS)
    structured = model.with_structured_output(RouteDecision)
    started = time.perf_counter()
    try:
        decision: RouteDecision = structured.invoke(
            [
                SystemMessage(content=ROUTER_SYSTEM_PROMPT),
                *trimmed,
            ]
        )
    except Exception as exc:
        log.warning(
            "routed",
            success=False,
            error_class=type(exc).__name__,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return {
            "route": "UNKNOWN",
            "confidence": 0.0,
            "route_reasoning": f"router error: {type(exc).__name__}",
            "clarification_needed": True,
            "error": str(exc),
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    clarification = (
        decision.confidence < CONFIDENCE_THRESHOLD or decision.route == "UNKNOWN"
    )
    log.info(
        "routed",
        success=True,
        route=decision.route,
        confidence=decision.confidence,
        clarification_needed=clarification,
        latency_ms=latency_ms,
    )
    return {
        "route": decision.route,
        "confidence": decision.confidence,
        "route_reasoning": decision.reasoning,
        "clarification_needed": clarification,
    }
```

Add to the imports at the top of `src/spotter/agents/router.py`:

```python
from langchain_core.messages import SystemMessage

from spotter.config import CONFIDENCE_THRESHOLD, MAX_HISTORY_TURNS
from spotter.conversations import trim_history
```

(Replace the existing `from spotter.config import CONFIDENCE_THRESHOLD` line.)

- [ ] **Step 4: Update existing router tests to use messages input**

In `tests/test_router_clarification.py`, change the three existing `graph.invoke({"user_input": "..."})` calls to use messages instead. Replace each:

```python
out = graph.invoke({"user_input": "Bench press"})
```

with:

```python
out = graph.invoke({"messages": [HumanMessage(content="Bench press")]})
```

Do the same for the other two calls (`"Build me a 30 min upper body workout"` and `"What is hypertrophy?"` and `"anything"`).

Add to the imports at the top of `tests/test_router_clarification.py`:

```python
from langchain_core.messages import HumanMessage
```

- [ ] **Step 5: Run all router tests**

Run: `uv run pytest tests/test_router_clarification.py -v`
Expected: all PASS, including the new history-passing test.

- [ ] **Step 6: Commit**

```bash
git add src/spotter/agents/router.py tests/test_router_clarification.py
git commit -m "$(cat <<'EOF'
feat(router): classify with full message history, not just latest input

The router now reads state["messages"] (trimmed to last MAX_HISTORY_TURNS
turns) and passes the full BaseMessage list to the LLM. This lets short
follow-ups like "yeah, the preacher curl" route correctly when the prior
assistant turn was a disambiguation question.
EOF
)"
```

---

## Task 5: Migrate coach to read history and emit AIMessage delta

**Files:**
- Modify: `src/spotter/agents/coach.py:37-72`
- Test: extend `tests/test_coach.py` (new — coach has no existing test file)

- [ ] **Step 1: Write a failing test for the coach**

Create `tests/test_coach.py`:

```python
"""Coach agent — reads message history and emits an AIMessage delta."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from spotter.agents.coach import build_coach_subgraph


def test_coach_reads_history_and_returns_ai_message_delta(fake_chat_model_factory):
    """Coach passes history to LLM and returns the answer as an AIMessage in messages."""
    captured: list = []

    class CapturingModel:
        def invoke(self, messages):
            captured.extend(messages)
            return AIMessage(content="Quads, glutes, hamstrings, and lower back.")

    graph = build_coach_subgraph(model=CapturingModel())
    history = [
        HumanMessage(content="what muscles does a deadlift work?"),
    ]
    out = graph.invoke({"messages": history})

    # LLM saw the system prompt + the history.
    assert len(captured) >= 2
    assert any(
        isinstance(m, HumanMessage) and "deadlift" in m.content for m in captured
    )

    # Final response and AIMessage delta both present.
    assert "Quads" in out["final_response"]
    new_messages = out["messages"]
    assert len(new_messages) == 1
    assert isinstance(new_messages[0], AIMessage)
    assert "Quads" in new_messages[0].content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_coach.py -v`
Expected: FAIL — coach currently reads `state["user_input"]` (KeyError) and doesn't return messages.

- [ ] **Step 3: Update coach to read history and emit AIMessage delta**

In `src/spotter/agents/coach.py`, replace the `_answer` function (lines 37–72) with:

```python
def _answer(state: HubState, *, model: BaseChatModel) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages:
        return {
            "sub_agent_output": {"answer": None, "error": "no messages"},
            "final_response": "Sorry — no question to answer.",
            "messages": [AIMessage(content="Sorry — no question to answer.")],
        }
    trimmed = trim_history(messages, MAX_HISTORY_TURNS)
    started = time.perf_counter()
    try:
        response = model.invoke(
            [
                SystemMessage(content=COACH_SYSTEM_PROMPT),
                *trimmed,
            ]
        )
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        log.warning(
            "coach_answered",
            success=False,
            error_class=type(exc).__name__,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        text = "Sorry — I hit an error answering that. Try rephrasing?"
        return {
            "sub_agent_output": {"answer": None, "error": str(exc)},
            "final_response": text,
            "messages": [AIMessage(content=text)],
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "coach_answered",
        success=True,
        length=len(answer) if isinstance(answer, str) else 0,
        latency_ms=latency_ms,
    )
    return {
        "sub_agent_output": {"answer": answer},
        "final_response": answer,
        "messages": [AIMessage(content=answer)],
    }
```

Add imports at the top of `src/spotter/agents/coach.py`:

```python
from langchain_core.messages import AIMessage, SystemMessage

from spotter.config import MAX_HISTORY_TURNS
from spotter.conversations import trim_history
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_coach.py -v`
Expected: PASS.

Run: `uv run pytest -v`
Expected: all existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/spotter/agents/coach.py tests/test_coach.py
git commit -m "$(cat <<'EOF'
feat(coach): read message history; return AIMessage delta

Coach now passes the trimmed message list to the LLM so follow-ups like
"how about the conventional one?" resolve via prior turns. Its reply
also lands in state.messages as an AIMessage delta so the shared
conversation transcript stays in sync.
EOF
)"
```

---

## Task 6: Migrate clarification to emit AIMessage delta

**Files:**
- Modify: `src/spotter/agents/clarification.py:35-48`
- Test: `tests/test_clarification.py` (new)

The clarification node doesn't need history — it operates on `route_reasoning` from the router. It only needs to emit its disambiguation question as an AIMessage delta so the next turn's router sees it.

- [ ] **Step 1: Write a failing test**

Create `tests/test_clarification.py`:

```python
"""Clarification node — emits disambiguation message as AIMessage delta."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from spotter.agents.clarification import clarification_node


def test_clarification_returns_ai_message_delta():
    out = clarification_node({"route_reasoning": "could be coach or generate"})
    assert "final_response" in out
    new_messages = out["messages"]
    assert len(new_messages) == 1
    assert isinstance(new_messages[0], AIMessage)
    assert new_messages[0].content == out["final_response"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_clarification.py -v`
Expected: FAIL — clarification doesn't return `messages` yet.

- [ ] **Step 3: Update clarification to emit AIMessage**

In `src/spotter/agents/clarification.py`, replace the `clarification_node` function (lines 35–48) with:

```python
def clarification_node(state: HubState) -> dict[str, Any]:
    """Return a short clarification message naming the two most-likely routes."""
    reasoning = state.get("route_reasoning") or ""
    top_two = _likely_routes(reasoning)
    if not top_two:
        top_two = ["COACH", "WORKOUT_GENERATE"]

    options_text = " or ".join(_ROUTE_LABEL[r] for r in top_two)
    message = (
        "I'm not sure what you meant — would you like me to "
        f"{options_text}? A bit more detail will help me route correctly."
    )
    log.info("clarification_emitted", offered=top_two)
    return {
        "final_response": message,
        "sub_agent_output": {"clarification": True},
        "messages": [AIMessage(content=message)],
    }
```

Add to the imports at the top of `src/spotter/agents/clarification.py`:

```python
from langchain_core.messages import AIMessage
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_clarification.py -v`
Expected: PASS.

Run: `uv run pytest -v`
Expected: all existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/spotter/agents/clarification.py tests/test_clarification.py
git commit -m "$(cat <<'EOF'
feat(clarification): emit disambiguation message as AIMessage delta

So the next turn's router sees the prior clarifying question in the
conversation transcript and can interpret a short follow-up correctly.
EOF
)"
```

---

## Task 7: Migrate logger to read history and emit AIMessage deltas

**Files:**
- Modify: `src/spotter/agents/logger.py:37-159`
- Modify: `tests/test_logger_movement_bias.py` (input shape)

This is the keystone task — handles the screenshot scenario. The logger's `_extract` node reads message history and the `LOGGER_SYSTEM_PROMPT` gets updated to handle disambiguation-reply context. Both `_extract` and `_match` end up emitting AIMessage deltas (well, `_match` does, since it's the terminal node that produces `final_response`; `_extract` only does in its error path).

- [ ] **Step 1: Update existing logger tests to use messages input**

In `tests/test_logger_movement_bias.py`, change the existing `graph.invoke({"user_input": "..."})` calls to:

```python
out = graph.invoke({"messages": [HumanMessage(content="Did 4x8 dumbbell rows at 50 lbs")]})
```

Do the same for the other two calls. Add to imports:

```python
from langchain_core.messages import HumanMessage
```

- [ ] **Step 2: Run tests to verify they fail in a known way**

Run: `uv run pytest tests/test_logger_movement_bias.py -v`
Expected: FAIL — logger reads `state["user_input"]` which is now missing.

- [ ] **Step 3: Update logger `_extract` to read messages and the prompt to handle disambiguation context**

In `src/spotter/agents/logger.py`, replace `LOGGER_SYSTEM_PROMPT` (lines 23–34) with:

```python
LOGGER_SYSTEM_PROMPT = """Extract a structured workout log entry from the conversation.

You receive the full recent conversation history. The user's most recent message is
the new input. Earlier messages may include:
- Prior log requests (e.g., "I did 3x10 bicep curls").
- An assistant disambiguation question listing 2–3 candidate exercise names
  ("I couldn't confidently match X. Did you mean Y, Z, or W?").

If the most recent user message looks like a reply to a disambiguation question
(it picks one of the candidates, possibly with a typo or short prefix), MERGE
sets/reps/weight from the earlier log request with the exercise the user just
named. Return the merged LogEntry, using the user's chosen exercise as
`exercise_name_raw`.

Otherwise, extract from the most recent user message directly (verbatim exercise
name, sets, reps, weight + unit if mentioned).

ALSO populate `movement_keyword` with a single short keyword identifying the kind
of movement — see the schema description for allowed values. Examples: 'I did rows'
→ 'row'; 'bench press' → 'press'; 'RDLs' → 'deadlift'; 'preacher curls' → 'curl'.

If the input is not a workout log (e.g. a question), still attempt extraction —
downstream will reject low-confidence matches."""
```

Replace the `_extract` function (lines 37–72) with:

```python
def _extract(state: HubState, *, model: BaseChatModel) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages:
        text = (
            "I couldn't parse that as a workout log. Try something like "
            "'3x10 bench press at 185 lbs'."
        )
        return {
            "sub_agent_output": {"resolved": False, "error": "no messages"},
            "final_response": text,
            "messages": [AIMessage(content=text)],
        }
    trimmed = trim_history(messages, MAX_HISTORY_TURNS)
    structured = model.with_structured_output(LogEntry)
    started = time.perf_counter()
    try:
        entry: LogEntry = structured.invoke(
            [
                SystemMessage(content=LOGGER_SYSTEM_PROMPT),
                *trimmed,
            ]
        )
    except (ValidationError, Exception) as exc:
        log.warning(
            "log_extracted",
            success=False,
            error_class=type(exc).__name__,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        text = (
            "I couldn't parse that as a workout log. Try something like "
            "'3x10 bench press at 185 lbs'."
        )
        return {
            "sub_agent_output": {
                "resolved": False,
                "error": f"Couldn't parse the log: {type(exc).__name__}",
            },
            "final_response": text,
            "messages": [AIMessage(content=text)],
        }

    log.info(
        "log_extracted",
        success=True,
        sets=entry.sets,
        reps=entry.reps,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return {"sub_agent_output": {"log_entry": entry.model_dump()}}
```

- [ ] **Step 4: Update logger `_match` to emit AIMessage delta**

In the same file, replace the `_match` function. The function body stays mostly the same but **both return paths** (successful match and ambiguous candidates) need to include the AIMessage delta. Replace the existing `_match` function with:

```python
def _match(state: HubState, *, dataset: Dataset) -> dict[str, Any]:
    pending = state.get("sub_agent_output", {})
    if "log_entry" not in pending:
        return {}

    entry_dict = pending["log_entry"]
    raw_name = entry_dict["exercise_name_raw"]
    keyword = (entry_dict.get("movement_keyword") or "").strip().lower()

    if keyword:
        biased_pool = [e for e in dataset.all if keyword in e.name.lower()]
        pool = biased_pool if biased_pool else list(dataset.all)
    else:
        pool = list(dataset.all)

    candidate_names = [e.name for e in pool]
    matches = process.extract(
        raw_name,
        candidate_names,
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        limit=3,
    )
    top_name, top_score, top_idx = matches[0]
    exercise = pool[top_idx]

    if top_score >= FUZZY_MATCH_THRESHOLD:
        log.info(
            "log_matched",
            matched=True,
            top_score=top_score,
            exercise_id=exercise.id,
            movement_keyword=keyword or None,
            pool_size=len(pool),
        )
        weight_str = ""
        if entry_dict["weight"] is not None:
            unit = entry_dict.get("weight_unit") or "lbs"
            weight_str = f" at {entry_dict['weight']:g} {unit}"
        response = (
            f"Logged: {entry_dict['sets']}x{entry_dict['reps']} {exercise.name}{weight_str}."
        )
        return {
            "sub_agent_output": {
                "resolved": True,
                "exercise_id": exercise.id,
                "canonical_name": exercise.name,
                "log_entry": entry_dict,
                "match_score": top_score,
            },
            "final_response": response,
            "messages": [AIMessage(content=response)],
        }

    candidate_list = [
        {"name": name, "score": score, "exercise_id": pool[idx].id}
        for name, score, idx in matches
    ]
    log.info(
        "log_matched",
        matched=False,
        top_score=top_score,
        candidates=len(candidate_list),
        movement_keyword=keyword or None,
        pool_size=len(pool),
    )
    options = ", ".join(f"'{c['name']}'" for c in candidate_list)
    response = (
        f"I couldn't confidently match '{raw_name}'. Did you mean one of: {options}?"
    )
    return {
        "sub_agent_output": {
            "resolved": False,
            "candidates": candidate_list,
            "log_entry": entry_dict,
        },
        "final_response": response,
        "messages": [AIMessage(content=response)],
    }
```

Add to the imports at the top of `src/spotter/agents/logger.py`:

```python
from langchain_core.messages import AIMessage, SystemMessage

from spotter.config import FUZZY_MATCH_THRESHOLD, MAX_HISTORY_TURNS
from spotter.conversations import trim_history
```

(Replace the existing `from spotter.config import FUZZY_MATCH_THRESHOLD` line.)

- [ ] **Step 5: Run all logger tests**

Run: `uv run pytest tests/test_logger_movement_bias.py -v`
Expected: PASS — logger now reads messages and emits AIMessage deltas.

- [ ] **Step 6: Commit**

```bash
git add src/spotter/agents/logger.py tests/test_logger_movement_bias.py
git commit -m "$(cat <<'EOF'
feat(logger): read message history; merge disambiguation replies

The logger extractor now sees the trimmed conversation history. The
system prompt teaches it to recognize a disambiguation-reply pattern
(prior assistant turn was "did you mean X/Y/Z?", current user message
names one of those candidates) and merge sets/reps from the earlier log
request with the chosen exercise.

Both extract-error and match-result paths emit AIMessage deltas so the
disambiguation question and the final "Logged: ..." both land in the
shared conversation transcript.
EOF
)"
```

---

## Task 8: Refactor generator for scratch-vs-shared message split

**Files:**
- Modify: `src/spotter/agents/generator.py:57-175`
- Modify: `tests/test_generator_empty_search.py` (input shape)

The generator's tool-call loop threads working messages between its `_agent_node` and `_tools_node`. Under the `add_messages` reducer on the shared `messages` field, threading through the same field would (a) pollute the conversation transcript with tool calls, and (b) double-append because the existing `return {"messages": full_list + [new]}` doesn't play well with the appending reducer. Fix: dedicated `generator_scratch` field.

- [ ] **Step 1: Update existing generator test to use messages input**

In `tests/test_generator_empty_search.py`, find the `graph.invoke({"user_input": "Build me a workout using a rowing machine"})` call (line 70) and change it to:

```python
out = graph.invoke({"messages": [HumanMessage(content="Build me a workout using a rowing machine")]})
```

Add to imports:

```python
from langchain_core.messages import HumanMessage
```

- [ ] **Step 2: Run test to confirm it fails in the expected way**

Run: `uv run pytest tests/test_generator_empty_search.py -v`
Expected: FAIL — `state["user_input"]` is missing; the generator currently falls into the `if not messages:` branch and tries to read `state["user_input"]`.

- [ ] **Step 3: Refactor generator nodes for the scratch field**

In `src/spotter/agents/generator.py`, replace lines 57–175 with:

```python
_MAX_TOOL_LOOPS = 6


def _init_scratch(state: HubState) -> dict[str, Any]:
    """Build the generator's tool-call working list from the conversation transcript."""
    messages = state.get("messages") or []
    trimmed = trim_history(messages, MAX_HISTORY_TURNS)
    scratch: list[BaseMessage] = [
        SystemMessage(content=GENERATOR_SYSTEM_PROMPT),
        *trimmed,
    ]
    return {"generator_scratch": scratch}


def _agent_node(
    state: HubState, *, model: BaseChatModel, tools: list[Any]
) -> dict[str, Any]:
    scratch = state["generator_scratch"]
    bound = model.bind_tools(tools)
    started = time.perf_counter()
    response: AIMessage = bound.invoke(scratch)
    log.info(
        "agent_step",
        success=True,
        has_tool_calls=bool(getattr(response, "tool_calls", None)),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return {"generator_scratch": scratch + [response]}


def _tools_node(
    state: HubState, *, tools_by_name: dict[str, Any]
) -> dict[str, Any]:
    scratch = state["generator_scratch"]
    last = scratch[-1]
    tool_messages: list[ToolMessage] = []
    for call in getattr(last, "tool_calls", []) or []:
        tool = tools_by_name.get(call["name"])
        if tool is None:
            tool_messages.append(
                ToolMessage(
                    content=f"unknown tool: {call['name']}",
                    tool_call_id=call.get("id", "unknown"),
                )
            )
            continue
        try:
            result = tool.invoke(call.get("args", {}))
        except Exception as exc:
            log.warning(
                "tool_call",
                tool_name=call["name"],
                success=False,
                error_class=type(exc).__name__,
            )
            result = {"error": str(exc), "error_class": type(exc).__name__}
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, default=str),
                tool_call_id=call.get("id", "unknown"),
            )
        )
    return {"generator_scratch": scratch + tool_messages}


def _should_continue(state: HubState) -> str:
    last = state["generator_scratch"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "finalize"


def _finalize(state: HubState) -> dict[str, Any]:
    scratch = state["generator_scratch"]
    last_ai = next(
        (
            m
            for m in reversed(scratch)
            if isinstance(m, AIMessage) and not m.tool_calls
        ),
        None,
    )
    text = (
        last_ai.content
        if last_ai is not None and isinstance(last_ai.content, str)
        else "I couldn't put a workout together — please try a different request."
    )

    workout_payload: dict | None = None
    for m in reversed(scratch):
        if isinstance(m, ToolMessage):
            try:
                payload = json.loads(m.content)
                if isinstance(payload, dict) and "blocks" in payload:
                    workout_payload = payload
                    break
            except (json.JSONDecodeError, TypeError):
                continue

    return {
        "sub_agent_output": {"workout": workout_payload, "narrative": text},
        "final_response": text,
        "messages": [AIMessage(content=text)],
    }


def build_generator_subgraph(model: BaseChatModel | None = None):
    chat = model if model is not None else chat_model("sonnet", temperature=0.4)
    tools = [search_exercises, build_workout]
    tools_by_name = {t.name: t for t in tools}

    graph = StateGraph(HubState)
    graph.add_node("init", _init_scratch)
    graph.add_node("agent", lambda s: _agent_node(s, model=chat, tools=tools))
    graph.add_node(
        "tools", lambda s: _tools_node(s, tools_by_name=tools_by_name)
    )
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "init")
    graph.add_edge("init", "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "finalize": "finalize"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile().with_config(recursion_limit=_MAX_TOOL_LOOPS * 3)
```

Add to the imports at the top of `src/spotter/agents/generator.py`:

```python
from langchain_core.messages import BaseMessage

from spotter.config import MAX_HISTORY_TURNS
from spotter.conversations import trim_history
```

(The file already imports `AIMessage`, `HumanMessage`, `SystemMessage`, `ToolMessage` from `langchain_core.messages` — add `BaseMessage` to that line.)

- [ ] **Step 4: Run the generator test**

Run: `uv run pytest tests/test_generator_empty_search.py -v`
Expected: PASS — the generator now initializes scratch from the conversation, threads it through the loop, and emits its final AIMessage to the shared transcript.

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/spotter/agents/generator.py tests/test_generator_empty_search.py
git commit -m "$(cat <<'EOF'
feat(generator): scratch field separates tool-loop messages from transcript

The generator's tool-call loop now threads its working messages through
state["generator_scratch"], rebuilt from the conversation history at the
start of each turn. Only the final user-facing AIMessage lands in
state["messages"], so the shared conversation transcript stays clean
(no tool calls, no intermediate AIMessages).
EOF
)"
```

---

## Task 9: Drop `user_input` from `HubState` and `run_hub`

**Files:**
- Modify: `src/spotter/schemas.py:14-30` (remove `user_input` field)
- Modify: `src/spotter/hub.py` (remove `user_input` from the input dict)

All agents now read `state["messages"]`. The legacy `user_input` mirror can go.

- [ ] **Step 1: Remove `user_input` from HubState**

In `src/spotter/schemas.py`, in the `HubState` TypedDict, remove the line:

```python
    user_input: str  # legacy mirror of latest HumanMessage; removed in Task 9.
```

- [ ] **Step 2: Remove `user_input` from `run_hub`'s invoke input**

In `src/spotter/hub.py`, in the `run_hub` function, find the `hub.invoke({...}, config=config)` call and remove the `"user_input": user_input,` line. The input dict becomes:

```python
        out = hub.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "trace_id": tid,
            },
            config=config,
        )
```

- [ ] **Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS. No tests should reference `state["user_input"]` anymore.

- [ ] **Step 4: Commit**

```bash
git add src/spotter/schemas.py src/spotter/hub.py
git commit -m "$(cat <<'EOF'
refactor(schemas): drop user_input from HubState

All agents now read from state["messages"]. The legacy mirror is no
longer needed.
EOF
)"
```

---

## Task 10: Add the `multiturn_hub` fixture

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add the fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def multiturn_hub():
    """Build a hub with an explicit MemorySaver for multi-turn tests.

    Usage:
        hub = multiturn_hub(router_model=..., logger_model=..., ...)
        out1 = run_hub(hub, "first message", conversation_id="conv-1")
        out2 = run_hub(hub, "follow-up", conversation_id="conv-1")
    """
    from langgraph.checkpoint.memory import MemorySaver

    from spotter.hub import build_hub

    def _build(**model_kwargs):
        return build_hub(checkpointer=MemorySaver(), **model_kwargs)

    return _build
```

- [ ] **Step 2: Verify the fixture is importable from a test**

Run: `uv run pytest tests/test_conversation_threading.py -v`
Expected: all tests PASS — the existing threading tests can switch to using `multiturn_hub` in a later refactor, but the current ones build their own checkpointer inline. We just verify the fixture import path works.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(conftest): add multiturn_hub fixture for multi-turn tests"
```

---

## Task 11: Critical-path test for the screenshot scenario

**Files:**
- Create: `tests/test_multiturn_disambiguation.py`

- [ ] **Step 1: Write the test**

Create `tests/test_multiturn_disambiguation.py`:

```python
"""Critical-path test #3 — multi-turn logger disambiguation.

The scenario from the screenshot in docs/brainstorms/2026-06-02-multi-turn-
conversation-context.md:

Turn 1: "i just did 3 sets of 10 rep of 10lb bicep curls" → logger asks
        "did you mean X/Y/Z?"
Turn 2: "yeah - Single-Arm Dumbbell Preacher Curl" → "Logged: 3x10 ..."

If this regresses, every user who hits a fuzzy-miss is stuck in a
dead-end. That's the bar for a critical-path test.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from spotter.hub import run_hub
from spotter.schemas import LogEntry, RouteDecision


def test_disambiguation_resume_logs_via_history(
    multiturn_hub, fake_chat_model_factory
):
    router_model = fake_chat_model_factory(
        structured=[
            RouteDecision(route="WORKOUT_LOG", confidence=0.9, reasoning="log 1"),
            RouteDecision(route="WORKOUT_LOG", confidence=0.95, reasoning="log 2"),
        ]
    )
    logger_model = fake_chat_model_factory(
        structured=[
            LogEntry(
                exercise_name_raw="bicep curls",
                movement_keyword="curl",
                sets=3,
                reps=10,
                weight=10.0,
                weight_unit="lbs",
            ),
            LogEntry(
                exercise_name_raw="Single-Arm Dumbbell Preacher Curl",
                movement_keyword="curl",
                sets=3,
                reps=10,
                weight=10.0,
                weight_unit="lbs",
            ),
        ]
    )
    hub = multiturn_hub(router_model=router_model, logger_model=logger_model)

    out1 = run_hub(
        hub,
        "i just did 3 sets of 10 rep of 10lb bicep curls",
        conversation_id="conv-screenshot",
    )
    assert "couldn't confidently match" in out1["response"].lower()
    assert "preacher curl" in out1["response"].lower()

    out2 = run_hub(
        hub,
        "yeah - Single-Arm Dumbbell Preacher Curl",
        conversation_id="conv-screenshot",
    )
    assert out2["response"].startswith("Logged:")
    assert "3x10" in out2["response"]
    assert "Single-Arm Dumbbell Preacher Curl" in out2["response"]
    assert "10 lbs" in out2["response"]


def test_separate_conversation_ids_do_not_share_state(
    multiturn_hub, fake_chat_model_factory
):
    router_model = fake_chat_model_factory(
        structured=[
            RouteDecision(route="WORKOUT_LOG", confidence=0.9, reasoning="A"),
            RouteDecision(route="WORKOUT_LOG", confidence=0.9, reasoning="B"),
        ]
    )
    logger_model = fake_chat_model_factory(
        structured=[
            LogEntry(
                exercise_name_raw="bench press",
                movement_keyword="press",
                sets=3,
                reps=10,
                weight=185.0,
                weight_unit="lbs",
            ),
            LogEntry(
                exercise_name_raw="back squat",
                movement_keyword="squat",
                sets=5,
                reps=5,
                weight=225.0,
                weight_unit="lbs",
            ),
        ]
    )
    hub = multiturn_hub(router_model=router_model, logger_model=logger_model)

    out_a = run_hub(hub, "3x10 bench at 185", conversation_id="conv-A")
    out_b = run_hub(hub, "5x5 squat at 225", conversation_id="conv-B")

    state_a = hub.get_state({"configurable": {"thread_id": "conv-A"}}).values
    state_b = hub.get_state({"configurable": {"thread_id": "conv-B"}}).values

    msgs_a = state_a.get("messages", [])
    msgs_b = state_b.get("messages", [])

    # Conversation A sees only its own messages.
    a_text = " ".join(m.content for m in msgs_a if hasattr(m, "content"))
    b_text = " ".join(m.content for m in msgs_b if hasattr(m, "content"))
    assert "bench" in a_text.lower()
    assert "squat" not in a_text.lower()
    assert "squat" in b_text.lower()
    assert "bench" not in b_text.lower()
```

- [ ] **Step 2: Run the new test file**

Run: `uv run pytest tests/test_multiturn_disambiguation.py -v`
Expected: both tests PASS. The first proves the screenshot scenario works end-to-end; the second proves conversation isolation.

- [ ] **Step 3: Run the entire suite**

Run: `uv run pytest -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_multiturn_disambiguation.py
git commit -m "$(cat <<'EOF'
test(multiturn): critical-path test #3 — disambiguation via conversation history

End-to-end test of the screenshot scenario: turn 1 logger asks "did you
mean X/Y/Z?", turn 2 user replies with the candidate, turn 2 succeeds in
logging the merged entry. Plus an isolation test that two different
conversation_ids don't share state.
EOF
)"
```

---

## Task 12: Manual browser verification

**Files:** none (manual)

This task does not commit code. It is the gate before declaring done.

- [ ] **Step 1: Restart the dev server**

Run: `uv run python -m spotter`
Expected: `INFO: Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 2: Walk the screenshot scenario in the browser**

Open http://127.0.0.1:8000. In the chat:

1. Send: `i just did 3 sets of 10 rep of 10lb bicep curls`
   Expected: assistant replies with "I couldn't confidently match 'bicep curls'. Did you mean one of: ..." (lists candidates including a preacher curl).
2. Send: `yeah - Single-Arm Dumbbell Preacher Curl`
   Expected: assistant replies with "Logged: 3x10 Single-Arm Dumbbell Preacher Curl at 10 lbs." If the in-progress Recent Logs panel is wired up, the new entry appears there as well.

- [ ] **Step 3: Verify conversation isolation**

In the same browser, refresh the page (this mints a new `conversation_id`). Send: `yeah - Single-Arm Dumbbell Preacher Curl`.
Expected: hub responds with the generic clarification ("I'm not sure what you meant — would you like me to ...") because the new conversation has no prior disambiguation context. **This is correct behavior** — proves state is per-conversation, not global.

- [ ] **Step 4: Verify a coach follow-up works**

Open a fresh page. Send: `what muscles does a deadlift work?` Then send: `how about the conventional one?`
Expected: the second response answers about the conventional deadlift specifically, because the coach now sees the prior turn in history.

- [ ] **Step 5: Tail the logs and confirm `conversation_id` is bound**

In another terminal: `tail -f logs/trace.jsonl | head -20`
Expected: every log line for the just-sent requests includes both `trace_id` and `conversation_id` fields.

- [ ] **Step 6: Done**

If all five manual checks pass, the feature is complete. If any fail, file a follow-up issue, do not mark the task done.

---

## Out of scope (deferred per spec §10)

- Generator edit support (`last_workout` carry, edit-shaped extractor prompt, swap/replace/shorten operations).
- Multi-turn eval scenarios in the `evals/` suite.
- Persistence to disk (`SqliteSaver`) + TTL cleanup.
- Conversation reset endpoint (`POST /chat/reset`).
- Server-side per-conversation locks for concurrent same-id requests.
