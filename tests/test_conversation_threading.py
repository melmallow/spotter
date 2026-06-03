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

    # Verify the checkpointer actually persisted both turns under the same thread.
    state = hub.get_state({"configurable": {"thread_id": "conv-A"}}).values
    msgs = state.get("messages", [])
    human_msgs = [m for m in msgs if isinstance(m, HumanMessage)]
    assert len(human_msgs) == 2
    assert human_msgs[0].content == "what muscles does a deadlift work?"
    assert human_msgs[1].content == "how about the conventional one?"


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
