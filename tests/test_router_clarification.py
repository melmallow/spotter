"""Critical path #1: low-confidence routing triggers clarification, not silent misroute.

See tests/README.md for why this test was chosen.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

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

    out = graph.invoke({"messages": [HumanMessage(content="Bench press")]})

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

    out = graph.invoke({"messages": [HumanMessage(content="Build me a 30 min upper body workout")]})

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

    out = graph.invoke({"messages": [HumanMessage(content="What is hypertrophy?")]})

    assert out["confidence"] == 0.6
    assert out["clarification_needed"] is False


def test_router_error_falls_back_to_clarification(fake_chat_model_factory):
    """R16: LLM failure → clarification path, no uncaught exception."""
    fake = fake_chat_model_factory(structured=[], raise_on_call=True)
    graph = build_router_subgraph(model=fake)

    out = graph.invoke({"messages": [HumanMessage(content="anything")]})

    assert out["clarification_needed"] is True
    assert out["route"] == "UNKNOWN"
    assert "error" in out


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
    assert any(
        type(m).__name__ == "SystemMessage" for m in captured_messages
    ), f"system prompt missing: {[type(m).__name__ for m in captured_messages]}"
    assert (
        sum(1 for m in captured_messages if isinstance(m, HumanMessage)) == 2
    ), f"expected 2 HumanMessages in router call, got: {captured_messages}"
