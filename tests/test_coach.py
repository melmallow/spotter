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
    all_messages = out["messages"]
    # The add_messages reducer accumulates: input history + the AIMessage delta.
    # Verify the last message is the new AIMessage reply.
    ai_messages = [m for m in all_messages if isinstance(m, AIMessage)]
    assert len(ai_messages) == 1
    assert "Quads" in ai_messages[0].content
