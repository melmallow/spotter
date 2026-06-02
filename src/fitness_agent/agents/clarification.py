"""Clarification node — produces a user-facing disambiguation prompt."""

from __future__ import annotations

from typing import Any

from fitness_agent.logging_setup import get_logger
from fitness_agent.schemas import HubState


log = get_logger("clarification")


_ROUTE_LABEL = {
    "COACH": "ask me about exercises or training concepts",
    "WORKOUT_GENERATE": "build you a workout",
    "WORKOUT_LOG": "log a workout you just finished",
}


def _likely_routes(reasoning: str) -> list[str]:
    """Pick the top two routes from the router's reasoning text — heuristic but cheap."""
    lowered = reasoning.lower()
    scores: dict[str, int] = {r: 0 for r in _ROUTE_LABEL}
    for route, label in _ROUTE_LABEL.items():
        if route.lower() in lowered:
            scores[route] += 2
        for token in label.split():
            if token in lowered:
                scores[route] += 1
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [r for r, _ in ordered[:2]]


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
    return {"final_response": message, "sub_agent_output": {"clarification": True}}
