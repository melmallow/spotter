"""Critical path #1: low-confidence routing triggers clarification, not silent misroute.

See tests/README.md for why this test was chosen.
"""

from __future__ import annotations

import pytest

from spotter.agents.router import build_router_subgraph
from spotter.logging_setup import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
)
from spotter.schemas import RouteDecision


configure_logging()


@pytest.fixture(autouse=True)
def _trace_id():
    bind_contextvars(trace_id="test-router")
    yield
    clear_contextvars()


def test_low_confidence_triggers_clarification(fake_chat_model_factory):
    """AE2 / F2 / R5: 'Bench press' → UNKNOWN low-confidence → clarification_needed."""
    fake = fake_chat_model_factory(
        structured=[
            RouteDecision(route="UNKNOWN", confidence=0.4, reasoning="bare name")
        ]
    )
    graph = build_router_subgraph(model=fake)

    out = graph.invoke({"user_input": "Bench press"})

    assert out["route"] == "UNKNOWN"
    assert out["confidence"] == 0.4
    assert out["clarification_needed"] is True


def test_high_confidence_routes_without_clarification(fake_chat_model_factory):
    """AE1 / R3, R4: explicit ask → WORKOUT_GENERATE with confidence ≥ 0.8."""
    fake = fake_chat_model_factory(
        structured=[
            RouteDecision(
                route="WORKOUT_GENERATE", confidence=0.92, reasoning="explicit ask"
            )
        ]
    )
    graph = build_router_subgraph(model=fake)

    out = graph.invoke({"user_input": "Build me a 30 min upper body workout"})

    assert out["route"] == "WORKOUT_GENERATE"
    assert out["confidence"] == 0.92
    assert out["clarification_needed"] is False


def test_threshold_boundary_is_strict_less_than(fake_chat_model_factory):
    """Confidence == threshold (0.6) is NOT low-confidence."""
    fake = fake_chat_model_factory(
        structured=[
            RouteDecision(route="COACH", confidence=0.6, reasoning="borderline")
        ]
    )
    graph = build_router_subgraph(model=fake)

    out = graph.invoke({"user_input": "What is hypertrophy?"})

    assert out["confidence"] == 0.6
    assert out["clarification_needed"] is False


def test_router_error_falls_back_to_clarification(fake_chat_model_factory):
    """R16: LLM failure → clarification path, no uncaught exception."""
    fake = fake_chat_model_factory(structured=[], raise_on_call=True)
    graph = build_router_subgraph(model=fake)

    out = graph.invoke({"user_input": "anything"})

    assert out["clarification_needed"] is True
    assert out["route"] == "UNKNOWN"
    assert "error" in out
