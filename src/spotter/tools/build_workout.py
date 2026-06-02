"""build_workout tool — assembles a structured workout and auto-pairs bilateral exercises.

R27 implementation: when a selected exercise has `is_bilateral=True`, the tool
appends a second set tagged `(other side)` of the same record — the dataset's
`bilateral_pair_id` values do not resolve to actual records, so we use the
same record with a side-flipped annotation rather than looking up a pair.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from spotter.data import Dataset, get_dataset
from spotter.logging_setup import get_logger
from spotter.schemas import (
    BuildWorkoutInput,
    PrescribedExercise,
    WorkoutBlock,
    WorkoutPlan,
)


log = get_logger("tool.build_workout")


def _resolve_block(
    block_name: str, items: list[PrescribedExercise], dataset: Dataset
) -> WorkoutBlock:
    resolved: list[dict[str, Any]] = []
    for item in items:
        exercise = dataset.by_id.get(item.exercise_id)
        if exercise is None:
            raise ValueError(
                f"unknown exercise_id: {item.exercise_id} (not in dataset)"
            )

        # Determine the side label — for unilateral records, the dataset's
        # `side` is always "left_*"; first set keeps that, second set flips it.
        primary_side = (
            item.side_note
            or (exercise.side.replace("_", " ") if exercise.side else None)
        )
        prescription = {
            "exercise_id": exercise.id,
            "exercise_name": exercise.name,
            "sets": item.sets,
            "reps": item.reps,
            "duration_seconds": item.duration_seconds,
            "rest_seconds": item.rest_seconds,
            "side_note": primary_side,
        }
        resolved.append(prescription)

        # R27 side-flip: is_bilateral=True marks unilateral exercises in this
        # dataset. Auto-append the "other side" using the same record so both
        # sides are covered without referencing a non-existent pair record.
        if exercise.is_bilateral:
            other_side = _flip_side(primary_side)
            other = dict(prescription)
            other["side_note"] = other_side
            resolved.append(other)

    return WorkoutBlock(name=block_name, items=resolved)  # type: ignore[arg-type]


def _flip_side(side: str | None) -> str:
    """Map a left-* side label to right-*; unknown labels fall back to 'other side'."""
    if side is None:
        return "right side"
    s = side.lower().replace("_", " ")
    if "left arm" in s:
        return "right arm"
    if "left leg" in s:
        return "right leg"
    if "left side" in s or "left" in s:
        return s.replace("left", "right")
    return "other side"


def _do_build(args: BuildWorkoutInput, dataset: Dataset) -> WorkoutPlan:
    blocks = [
        _resolve_block("warmup", args.warmup, dataset),
        _resolve_block("main", args.main, dataset),
        _resolve_block("cooldown", args.cooldown, dataset),
    ]
    total_items = sum(len(b.items) for b in blocks)
    log.info(
        "tool_call",
        tool_name="build_workout",
        result_size=total_items,
        success=True,
    )
    return WorkoutPlan(blocks=blocks, notes=args.notes)


def _coerce(item: Any) -> PrescribedExercise:
    if isinstance(item, PrescribedExercise):
        return item
    if isinstance(item, dict):
        return PrescribedExercise(**item)
    raise TypeError(f"unexpected workout item type: {type(item).__name__}")


@tool(args_schema=BuildWorkoutInput)
def build_workout(
    warmup: list[Any],
    main: list[Any],
    cooldown: list[Any],
    notes: str | None = None,
) -> dict:
    """Assemble a structured workout (warmup / main / cooldown) from selected exercise IDs.

    Every `exercise_id` must reference a real exercise in the dataset — unknown
    IDs raise `ValueError`. Unilateral exercises (is_bilateral=True) are
    auto-paired with an `(other side)` second set of the same record.

    With args_schema bound, LangChain validates inputs against BuildWorkoutInput
    before calling — items may arrive as either dicts or PrescribedExercise
    instances depending on the tool-binding path. _coerce() handles both.
    """
    args = BuildWorkoutInput(
        warmup=[_coerce(w) for w in warmup],
        main=[_coerce(m) for m in main],
        cooldown=[_coerce(c) for c in cooldown],
        notes=notes,
    )
    return _do_build(args, get_dataset()).model_dump()
