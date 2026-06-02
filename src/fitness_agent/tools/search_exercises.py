"""search_exercises tool — filters the dataset, surfaces empty-result reason."""

from __future__ import annotations

from langchain_core.tools import tool

from fitness_agent.data import Dataset, get_dataset
from fitness_agent.logging_setup import get_logger
from fitness_agent.schemas import (
    ExerciseSummary,
    SearchExercisesInput,
    SearchExercisesResult,
)


log = get_logger("tool.search_exercises")


def _do_search(
    args: SearchExercisesInput, dataset: Dataset
) -> SearchExercisesResult:
    """Pure function — easy to unit-test without the @tool decorator wrapper."""
    candidates = list(dataset.all)
    filters_applied: list[str] = []

    if args.muscle_groups:
        wanted = {m.lower() for m in args.muscle_groups}
        candidates = [
            e for e in candidates if any(m.lower() in wanted for m in e.muscle_groups)
        ]
        filters_applied.append(f"muscle_groups={list(wanted)}")

    if args.equipment:
        wanted = {eq.lower() for eq in args.equipment}
        candidates = [
            e
            for e in candidates
            if any(req.lower() in wanted for req in e.equipment_required)
        ]
        filters_applied.append(f"equipment={list(wanted)}")

    if args.movement_patterns:
        wanted = {mp.lower() for mp in args.movement_patterns}
        candidates = [
            e
            for e in candidates
            if any(mp.lower() in wanted for mp in e.movement_patterns)
        ]
        filters_applied.append(f"movement_patterns={list(wanted)}")

    if args.avoid_joints:
        avoid = {j.lower() for j in args.avoid_joints}
        candidates = [
            e
            for e in candidates
            if not any(j.lower() in avoid for j in e.joints_loaded)
        ]
        filters_applied.append(f"avoid_joints={list(avoid)}")

    candidates = candidates[: args.limit]

    if not candidates:
        reason = (
            "no exercises matched these constraints: "
            + ", ".join(filters_applied)
            if filters_applied
            else "no exercises in dataset"
        )
        log.info(
            "tool_call",
            tool_name="search_exercises",
            result_size=0,
            success=True,
            empty_reason=reason,
        )
        return SearchExercisesResult(exercises=[], reason=reason)

    summaries = [
        ExerciseSummary(
            id=e.id,
            name=e.name,
            muscle_groups=e.muscle_groups,
            equipment_required=e.equipment_required,
            joints_loaded=e.joints_loaded,
            is_bilateral=e.is_bilateral,
        )
        for e in candidates
    ]
    log.info(
        "tool_call",
        tool_name="search_exercises",
        result_size=len(summaries),
        success=True,
    )
    return SearchExercisesResult(exercises=summaries, reason=None)


@tool(args_schema=SearchExercisesInput)
def search_exercises(
    muscle_groups: list[str] | None = None,
    equipment: list[str] | None = None,
    movement_patterns: list[str] | None = None,
    avoid_joints: list[str] | None = None,
    limit: int = 10,
) -> dict:
    """Search the exercise dataset filtered by user constraints.

    Returns a dict with `exercises` (a list of compact summaries) and an
    optional `reason` field explaining empty results — never raises on empty.
    """
    args = SearchExercisesInput(
        muscle_groups=muscle_groups,
        equipment=equipment,
        movement_patterns=movement_patterns,
        avoid_joints=avoid_joints,
        limit=limit,
    )
    return _do_search(args, get_dataset()).model_dump()
