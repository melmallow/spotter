"""Hub StateGraph composing the router and three sub-agent subgraphs."""

from __future__ import annotations

import time
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from spotter.agents.clarification import clarification_node
from spotter.agents.coach import build_coach_subgraph
from spotter.agents.generator import build_generator_subgraph
from spotter.agents.logger import build_logger_subgraph
from spotter.agents.router import build_router_subgraph
from spotter.logging_setup import (
    bind_contextvars,
    clear_contextvars,
    get_logger,
)
from spotter.schemas import HubState


log = get_logger("hub")


def _resolved_log_entry(out: dict[str, Any]) -> dict[str, Any] | None:
    """Surface just the fields the client needs to render a Recent Logs row."""
    if out.get("route") != "WORKOUT_LOG":
        return None
    sub = out.get("sub_agent_output") or {}
    if not sub.get("resolved") or "log_entry" not in sub:
        return None
    entry = sub["log_entry"]
    return {
        "exercise_id": sub.get("exercise_id"),
        "exercise_name": sub.get("canonical_name"),
        "sets": entry.get("sets"),
        "reps": entry.get("reps"),
        "weight": entry.get("weight"),
        "weight_unit": entry.get("weight_unit"),
    }


def _resolved_workout(out: dict[str, Any]) -> dict[str, Any] | None:
    """Surface the structured workout payload for WORKOUT_GENERATE responses."""
    if out.get("route") != "WORKOUT_GENERATE":
        return None
    sub = out.get("sub_agent_output") or {}
    workout = sub.get("workout")
    if not isinstance(workout, dict) or not workout.get("blocks"):
        return None
    return workout


def _route_selector(state: HubState) -> str:
    """Conditional edge function — pick the next node based on router output."""
    if state.get("clarification_needed"):
        return "clarification"
    route = state.get("route")
    if route == "COACH":
        return "coach"
    if route == "WORKOUT_GENERATE":
        return "generator"
    if route == "WORKOUT_LOG":
        return "logger"
    return "clarification"


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
            "workout": _resolved_workout(out),
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
