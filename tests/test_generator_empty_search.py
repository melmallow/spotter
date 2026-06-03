"""Critical path #2: empty search → graceful recovery with no fabricated exercises.

See tests/README.md for why this test was chosen.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from spotter.agents.generator import build_generator_subgraph
from spotter.data import get_dataset
from spotter.logging_setup import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
)
from spotter.tools.build_workout import _do_build, _flip_side
from spotter.tools.search_exercises import _do_search
from spotter.schemas import (
    BuildWorkoutInput,
    PrescribedExercise,
    SearchExercisesInput,
)


configure_logging()


@pytest.fixture(autouse=True)
def _trace_id():
    bind_contextvars(trace_id="test-generator")
    yield
    clear_contextvars()


def test_empty_search_recovery_no_hallucination(fake_chat_model_factory):
    """AE4 / F5 / R14: unavailable equipment → honest 'no match', no fabricated IDs.

    This is critical path #2. We script:
    1. Agent's first turn calls `search_exercises(equipment=['Rowing Machine'])`
    2. The tool returns an empty list with a reason
    3. Agent's second turn writes a final message that names the unavailability
       and suggests an alternative — without inventing any exercise IDs.
    """
    fake = fake_chat_model_factory(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_exercises",
                        "args": {"equipment": ["Rowing Machine"]},
                        "id": "call_search_1",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "I don't have any rowing-machine exercises in my dataset. "
                    "Want me to build something with dumbbells or a barbell instead?"
                )
            ),
        ]
    )

    graph = build_generator_subgraph(model=fake)
    out = graph.invoke({"messages": [HumanMessage(content="Build me a workout using a rowing machine")]})

    # Final response surfaces the unavailability honestly
    assert "rowing" in out["final_response"].lower()

    # No fabricated exercise IDs anywhere in the conversation
    dataset = get_dataset()
    valid_ids = set(dataset.by_id.keys())
    for msg in out["messages"]:
        if isinstance(msg, AIMessage) and msg.content:
            # The model's text response should not reference any specific UUID
            for chunk in str(msg.content).split():
                # UUIDs in this dataset are 36-char strings with hyphens
                if len(chunk) == 36 and chunk.count("-") == 4:
                    assert chunk in valid_ids, (
                        f"Hallucinated exercise ID in response: {chunk}"
                    )

    # The tool response should be the empty result with a reason.
    # Tool messages live in generator_scratch (the per-turn working list),
    # NOT in the shared conversation transcript.
    tool_messages = [
        m for m in out["generator_scratch"] if isinstance(m, ToolMessage)
    ]
    assert tool_messages, "Generator must have invoked at least one tool"
    payload = json.loads(tool_messages[0].content)
    assert payload["exercises"] == []
    assert payload["reason"] is not None
    assert "rowing" in payload["reason"].lower()


def test_search_with_avoid_joints_excludes_knee_loading(fake_chat_model_factory):
    """AE6 / R28: avoid_joints=['knee'] excludes knee-loading exercises."""
    # Direct tool unit test — doesn't need the agent loop
    dataset = get_dataset()
    args = SearchExercisesInput(
        muscle_groups=["quads"], avoid_joints=["knee"], limit=50
    )
    result = _do_search(args, dataset)

    for ex in result.exercises:
        assert "knee" not in [j.lower() for j in ex.joints_loaded], (
            f"Exercise {ex.name} loads knee but avoid_joints requested its exclusion"
        )


def test_build_workout_auto_pairs_unilateral_via_side_flip(fake_chat_model_factory):
    """AE5 / R27: is_bilateral=True exercise → second set tagged (other side)."""
    dataset = get_dataset()
    # Find a unilateral exercise
    unilateral = next(e for e in dataset.all if e.is_bilateral)

    args = BuildWorkoutInput(
        warmup=[],
        main=[
            PrescribedExercise(
                exercise_id=unilateral.id, sets=3, reps=10, rest_seconds=60
            )
        ],
        cooldown=[],
        notes="test",
    )
    plan = _do_build(args, dataset)
    main_items = plan.blocks[1].items

    assert len(main_items) == 2, (
        "Unilateral exercise should auto-pair into 2 entries (both sides)"
    )
    assert main_items[0]["exercise_id"] == unilateral.id
    assert main_items[1]["exercise_id"] == unilateral.id  # same record, flipped side
    # First entry has the dataset's original side, second has the flipped side
    assert main_items[0]["side_note"] != main_items[1]["side_note"]
    assert main_items[0]["sets"] == main_items[1]["sets"]
    assert main_items[0]["reps"] == main_items[1]["reps"]


def test_build_workout_rejects_unknown_exercise_id(fake_chat_model_factory):
    """R15 jointly with R17: unknown exercise ID rejected with a clear error."""
    dataset = get_dataset()
    args = BuildWorkoutInput(
        warmup=[],
        main=[
            PrescribedExercise(
                exercise_id="not-a-real-uuid", sets=3, reps=10, rest_seconds=60
            )
        ],
        cooldown=[],
    )
    with pytest.raises(ValueError, match="unknown exercise_id"):
        _do_build(args, dataset)


def test_flip_side_handles_all_dataset_side_values():
    """Coverage for the side-flip helper across the dataset's side vocabulary."""
    assert _flip_side("left arm") == "right arm"
    assert _flip_side("left_arm") == "right arm"
    assert _flip_side("left leg") == "right leg"
    assert _flip_side("left side") == "right side"
    assert _flip_side(None) == "right side"
