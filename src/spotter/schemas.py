"""Pydantic schemas and the LangGraph HubState TypedDict."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


Route = Literal["COACH", "WORKOUT_GENERATE", "WORKOUT_LOG", "UNKNOWN"]


class HubState(TypedDict, total=False):
    """Typed state flowing through the hub StateGraph and its subgraphs.

    Conversation-scoped fields persist across turns via the checkpointer.
    Turn-scoped fields are overwritten on every clean turn — the router
    always rewrites the routing fields, and every terminal node always
    rewrites `sub_agent_output` and `final_response`.
    """

    # ---- Conversation-scoped (persist across turns via checkpointer) ----
    messages: Annotated[list[BaseMessage], add_messages]

    # ---- Turn-scoped (always overwritten) ----
    user_input: str  # legacy mirror of latest HumanMessage; removed in Task 9.
    route: Route
    confidence: float
    route_reasoning: str
    clarification_needed: bool
    sub_agent_output: dict[str, Any]
    final_response: str
    trace_id: str
    error: str

    # ---- Per-turn ephemeral (generator's tool-call loop scratch) ----
    generator_scratch: list[BaseMessage]


# ---- Router structured output -------------------------------------------------


class RouteDecision(BaseModel):
    """LLM-emitted routing decision with self-reported confidence."""

    route: Route = Field(
        description=(
            "Which sub-agent should handle this message: "
            "COACH for fitness knowledge questions, "
            "WORKOUT_GENERATE for requests to build a workout, "
            "WORKOUT_LOG for reports of completed sets/reps, "
            "UNKNOWN when intent is unclear."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-reported confidence in the route, between 0 and 1.",
    )
    reasoning: str = Field(
        description="One short sentence explaining the routing decision."
    )


# ---- Workout logger structured output ----------------------------------------


class LogEntry(BaseModel):
    """Structured extraction of one completed workout entry."""

    exercise_name_raw: str = Field(
        description="The exercise name as the user said it, verbatim."
    )
    movement_keyword: str | None = Field(
        default=None,
        description=(
            "A single short keyword identifying the kind of movement the user "
            "named — used to bias the fuzzy-match candidate pool. Pick one of: "
            "press, row, squat, deadlift, curl, extension, fly, pulldown, "
            "pull-up, chin-up, push-up, lunge, raise, carry, stretch, plank, "
            "bridge — or None if no clear keyword applies. Example: 'rows' → "
            "'row'; 'overhead press' → 'press'; 'RDLs' → 'deadlift'."
        ),
    )
    sets: int = Field(ge=1, description="Number of sets performed.")
    reps: int = Field(ge=1, description="Number of reps per set.")
    weight: float | None = Field(
        default=None, description="External load applied, if any."
    )
    weight_unit: Literal["lbs", "kg"] | None = Field(
        default=None, description="Unit for `weight` when present."
    )


# ---- Tool input schemas ------------------------------------------------------


class SearchExercisesInput(BaseModel):
    """Filter the exercise dataset by user-stated constraints."""

    muscle_groups: list[str] | None = Field(
        default=None,
        description=(
            "Muscle group names to include (e.g. 'chest', 'quads'). "
            "Pass None to skip muscle filtering."
        ),
    )
    equipment: list[str] | None = Field(
        default=None,
        description=(
            "Available equipment names from the dataset's equipment list. "
            "Pass None to skip equipment filtering."
        ),
    )
    movement_patterns: list[str] | None = Field(
        default=None,
        description=(
            "Movement pattern strings, e.g. 'upper push - horizontal'. "
            "Pass None to skip movement-pattern filtering."
        ),
    )
    avoid_joints: list[str] | None = Field(
        default=None,
        description=(
            "Joints the user wants to avoid loading (e.g. 'knee', 'shoulder'). "
            "Exercises whose joints_loaded includes any of these are excluded."
        ),
    )
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return.")


class ExerciseSummary(BaseModel):
    """Compact exercise record returned by search_exercises."""

    id: str
    name: str
    muscle_groups: list[str]
    equipment_required: list[str]
    joints_loaded: list[str]
    is_bilateral: bool


class SearchExercisesResult(BaseModel):
    """search_exercises return shape — never raises on empty; surfaces reason."""

    exercises: list[ExerciseSummary] = Field(
        description="Matching exercise summaries; empty when nothing matched."
    )
    reason: str | None = Field(
        default=None,
        description="Human-readable reason when `exercises` is empty.",
    )


class PrescribedExercise(BaseModel):
    """One exercise prescription inside a workout block."""

    exercise_id: str = Field(description="Must reference a real exercise in the dataset.")
    sets: int = Field(ge=1, description="Number of sets to perform.")
    reps: int | None = Field(default=None, ge=1, description="Reps per set, if rep-based.")
    duration_seconds: int | None = Field(
        default=None, ge=1, description="Duration per set, if duration-based."
    )
    rest_seconds: int = Field(ge=0, description="Rest between sets, in seconds.")
    side_note: str | None = Field(
        default=None,
        description=(
            "Free-form annotation, e.g. 'left side' / 'right side' for auto-paired "
            "bilateral exercises."
        ),
    )


class BuildWorkoutInput(BaseModel):
    """Build a structured workout from selected exercise IDs."""

    warmup: list[PrescribedExercise] = Field(
        description="Warmup block — 1-3 mobility or light cardio items."
    )
    main: list[PrescribedExercise] = Field(
        description="Main block — primary strength or conditioning work."
    )
    cooldown: list[PrescribedExercise] = Field(
        description="Cooldown block — 1-3 stretches or breathing items."
    )
    notes: str | None = Field(
        default=None, description="One-sentence description for the user."
    )


class WorkoutBlock(BaseModel):
    """Resolved workout block with full exercise data attached."""

    name: Literal["warmup", "main", "cooldown"]
    items: list[dict[str, Any]]


class WorkoutPlan(BaseModel):
    """Final assembled workout returned to the user."""

    blocks: list[WorkoutBlock]
    notes: str | None = None
