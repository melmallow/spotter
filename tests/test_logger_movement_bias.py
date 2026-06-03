"""Verifies LogEntry.movement_keyword biases the fuzzy match toward the right family.

Without the bias, 'dumbbell rows' resolved to 'Alternating Dumbbell Decline Bench Press'
because WRatio over-rewarded the shared 'Dumbbell' equipment token. With the bias,
the pool is pre-filtered to exercises whose name contains 'row' first.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from spotter.agents.logger import build_logger_subgraph
from spotter.logging_setup import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
)
from spotter.schemas import LogEntry


configure_logging()


@pytest.fixture(autouse=True)
def _trace_id():
    bind_contextvars(trace_id="test-logger-bias")
    yield
    clear_contextvars()


def test_movement_keyword_biases_match_toward_row_family(fake_chat_model_factory):
    """'dumbbell rows' + movement_keyword='row' should match a row exercise, not a bench press."""
    fake = fake_chat_model_factory(
        structured=[
            LogEntry(
                exercise_name_raw="dumbbell rows",
                movement_keyword="row",
                sets=4,
                reps=8,
                weight=50,
                weight_unit="lbs",
            )
        ]
    )
    graph = build_logger_subgraph(model=fake)
    out = graph.invoke({"messages": [HumanMessage(content="Did 4x8 dumbbell rows at 50 lbs")]})

    canonical = (out["sub_agent_output"].get("canonical_name") or "").lower()
    response = out["final_response"].lower()
    # Whatever matched, "row" must be in its name — not "bench press" or "fly"
    assert "row" in canonical or "row" in response, (
        f"Expected a row exercise; got {canonical!r}"
    )
    assert "bench press" not in canonical, (
        f"Bias should have prevented bench press match; got {canonical!r}"
    )


def test_no_keyword_falls_back_to_full_dataset(fake_chat_model_factory):
    """When movement_keyword is None, behavior matches the v1 unbiased match."""
    fake = fake_chat_model_factory(
        structured=[
            LogEntry(
                exercise_name_raw="bench press",
                movement_keyword=None,
                sets=3,
                reps=10,
                weight=185,
                weight_unit="lbs",
            )
        ]
    )
    graph = build_logger_subgraph(model=fake)
    out = graph.invoke({"messages": [HumanMessage(content="3x10 bench press at 185")]})

    canonical = (out["sub_agent_output"].get("canonical_name") or "").lower()
    assert "bench press" in canonical


def test_empty_bias_pool_falls_back_safely(fake_chat_model_factory):
    """Keyword that matches no dataset exercise → fall back to full pool instead of crashing."""
    fake = fake_chat_model_factory(
        structured=[
            LogEntry(
                exercise_name_raw="bench press",
                movement_keyword="kettlebell-swing-thing",  # not in any exercise name
                sets=3,
                reps=10,
            )
        ]
    )
    graph = build_logger_subgraph(model=fake)
    out = graph.invoke({"messages": [HumanMessage(content="anything")]})
    # No exception, response produced
    assert "final_response" in out
