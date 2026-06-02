"""Exercise dataset loader and indexes.

The dataset's `is_bilateral=True` field counter-intuitively marks UNILATERAL
exercises (one side at a time) that should be auto-paired with the other side;
`is_bilateral=False` marks true-bilateral exercises (both sides simultaneously).
All 18 records with a `bilateral_pair_id` are left-side and the pair IDs do not
resolve to real records in this dataset — per R27, the workout generator handles
pairing by appending a `(other side)` set of the same record rather than looking
up a separate pair record.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fitness_agent.config import EXERCISE_DATA_PATH


Side = Literal["left_arm", "left_leg", "left_side"] | None


class Exercise(BaseModel):
    """One record from exercises.json. Field names mirror the source data."""

    id: str = Field(description="Stable UUID identifying this exercise")
    name: str = Field(description="Human-readable exercise name")
    muscle_groups: list[str] = Field(description="Primary muscles worked")
    joints_loaded: list[str] = Field(
        description="Joints under load — used by the injury-avoidance filter"
    )
    movement_patterns: list[str] = Field(
        description="Biomechanical categorization, e.g. 'upper push - horizontal'"
    )
    equipment_required: list[str] = Field(
        description="Equipment the user needs to perform this exercise"
    )
    is_bilateral: bool = Field(
        description=(
            "TRUE marks a UNILATERAL exercise that pairs with another side; "
            "FALSE marks a true-bilateral exercise (both sides simultaneously). "
            "Counter-intuitive but accurate to the source dataset."
        )
    )
    side: Side = Field(default=None, description="Side label for unilateral exercises")
    priority_tier: int = Field(description="Programming priority (1 = highest)")
    is_reps: bool = Field(description="Whether sets/reps are the prescription shape")
    is_duration: bool = Field(description="Whether duration is the prescription shape")
    supports_weight: bool = Field(description="Whether external load applies")
    estimated_rep_duration: float = Field(description="Seconds per rep (estimate)")
    bilateral_pair_id: str | None = Field(
        default=None,
        description=(
            "Pointer to the canonical 'other side' record. In this dataset the "
            "pointer does NOT resolve; the workout generator handles pairing by "
            "appending an (other side) set of the same record."
        ),
    )


class Dataset:
    """In-memory exercise dataset with cheap-filter indexes."""

    def __init__(self, exercises: list[Exercise]) -> None:
        self.all: list[Exercise] = exercises
        self.by_id: dict[str, Exercise] = {e.id: e for e in exercises}
        self.by_name: dict[str, Exercise] = {e.name.lower(): e for e in exercises}

        self.index_by_muscle: dict[str, list[Exercise]] = defaultdict(list)
        self.index_by_equipment: dict[str, list[Exercise]] = defaultdict(list)
        self.index_by_movement: dict[str, list[Exercise]] = defaultdict(list)
        self.index_by_joint: dict[str, list[Exercise]] = defaultdict(list)
        for e in exercises:
            for m in e.muscle_groups:
                self.index_by_muscle[m.lower()].append(e)
            for eq in e.equipment_required:
                self.index_by_equipment[eq.lower()].append(e)
            for mp in e.movement_patterns:
                self.index_by_movement[mp.lower()].append(e)
            for j in e.joints_loaded:
                self.index_by_joint[j.lower()].append(e)

    @classmethod
    def load(cls, path: Path | None = None) -> "Dataset":
        path = path or EXERCISE_DATA_PATH
        with open(path) as f:
            raw = json.load(f)
        return cls([Exercise(**item) for item in raw])

    def all_equipment(self) -> list[str]:
        return sorted({e for ex in self.all for e in ex.equipment_required})

    def all_muscle_groups(self) -> list[str]:
        return sorted(self.index_by_muscle.keys())


_DATASET: Dataset | None = None


def get_dataset() -> Dataset:
    """Singleton loader so the file is parsed once per process."""
    global _DATASET
    if _DATASET is None:
        _DATASET = Dataset.load()
    return _DATASET
