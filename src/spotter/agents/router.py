"""Router subgraph — classifies user input into a Route via structured output."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from spotter.config import CONFIDENCE_THRESHOLD
from spotter.llm import chat_model
from spotter.logging_setup import get_logger
from spotter.schemas import HubState, RouteDecision


log = get_logger("router")


ROUTER_SYSTEM_PROMPT = """You are a routing agent inside a fitness coaching system.
Classify the user's message into exactly one of these intents:

- COACH: questions about exercise knowledge, anatomy, form, programming, training concepts.
  Example: "What muscles does a deadlift work?"
- WORKOUT_GENERATE: requests to build, plan, design, or generate a workout/session.
  Example: "Build me a 30 min upper body session with dumbbells"
- WORKOUT_LOG: reports of completed work — sets, reps, weights actually performed.
  Example: "I just did 3x10 bench press at 185 lbs"
- UNKNOWN: intent is genuinely ambiguous or insufficient (e.g., bare exercise name with no verb).

Return your confidence in [0, 1] and one short sentence of reasoning.
Be honest about ambiguity — a confidence below 0.6 triggers a clarification flow."""


def _classify(state: HubState, *, model: BaseChatModel) -> dict[str, Any]:
    """Single router node. Caller injects the model so tests can stub it."""
    user_input = state["user_input"]
    structured = model.with_structured_output(RouteDecision)
    started = time.perf_counter()
    try:
        decision: RouteDecision = structured.invoke(
            [
                ("system", ROUTER_SYSTEM_PROMPT),
                ("human", user_input),
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


def build_router_subgraph(model: BaseChatModel | None = None):
    """Compile the router subgraph. Pass `model` to inject a fake for tests."""
    chat = model if model is not None else chat_model("haiku")

    graph = StateGraph(HubState)
    graph.add_node("classify", lambda s: _classify(s, model=chat))
    graph.add_edge(START, "classify")
    graph.add_edge("classify", END)
    return graph.compile()
