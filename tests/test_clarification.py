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
