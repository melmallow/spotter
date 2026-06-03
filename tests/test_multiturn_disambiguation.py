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
