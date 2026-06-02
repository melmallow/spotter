"""Workout Logger subgraph — structured-extract + RapidFuzz match."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from rapidfuzz import fuzz, process, utils

from spotter.config import FUZZY_MATCH_THRESHOLD
from spotter.data import Dataset, get_dataset
from spotter.llm import chat_model
from spotter.logging_setup import get_logger
from spotter.schemas import HubState, LogEntry


log = get_logger("logger")


LOGGER_SYSTEM_PROMPT = """Extract a structured workout log entry from the user's message.

Return the exercise name verbatim as the user said it (e.g. "bench press", not a canonical form),
the number of sets, reps per set, and any weight + unit. If weight wasn't mentioned, omit it.

ALSO populate `movement_keyword` with a single short keyword identifying the kind of movement —
this biases the fuzzy match toward the right exercise family. See the schema description for
the allowed values. Examples: 'I did rows' → 'row'; 'bench press' → 'press'; 'RDLs' → 'deadlift';
'preacher curls' → 'curl'. Pick the dominant keyword; leave as None only if no clear one applies.

If the input is not a workout log (e.g. a question), still attempt extraction — downstream
will reject low-confidence matches."""


def _extract(state: HubState, *, model: BaseChatModel) -> dict[str, Any]:
    structured = model.with_structured_output(LogEntry)
    started = time.perf_counter()
    try:
        entry: LogEntry = structured.invoke(
            [
                ("system", LOGGER_SYSTEM_PROMPT),
                ("human", state["user_input"]),
            ]
        )
    except (ValidationError, Exception) as exc:
        log.warning(
            "log_extracted",
            success=False,
            error_class=type(exc).__name__,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return {
            "sub_agent_output": {
                "resolved": False,
                "error": f"Couldn't parse the log: {type(exc).__name__}",
            },
            "final_response": (
                "I couldn't parse that as a workout log. Try something like "
                "'3x10 bench press at 185 lbs'."
            ),
        }

    log.info(
        "log_extracted",
        success=True,
        sets=entry.sets,
        reps=entry.reps,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return {"sub_agent_output": {"log_entry": entry.model_dump()}}


def _match(state: HubState, *, dataset: Dataset) -> dict[str, Any]:
    pending = state.get("sub_agent_output", {})
    if "log_entry" not in pending:
        return {}

    entry_dict = pending["log_entry"]
    raw_name = entry_dict["exercise_name_raw"]
    keyword = (entry_dict.get("movement_keyword") or "").strip().lower()

    # When the LLM gave us a movement keyword, prefer candidates whose name
    # contains the keyword. This stops WRatio over-weighting an equipment token
    # like 'Dumbbell' and steering 'dumbbell rows' to 'Alternating Dumbbell
    # Decline Bench Press'. If the keyword pool is empty (the LLM picked a word
    # the dataset doesn't use), fall back to the full dataset.
    if keyword:
        biased_pool = [e for e in dataset.all if keyword in e.name.lower()]
        pool = biased_pool if biased_pool else list(dataset.all)
    else:
        pool = list(dataset.all)

    candidate_names = [e.name for e in pool]
    # WRatio combines partial/token_set/token_sort strategies, which is what we
    # want: "bench press" should match "Barbell Flat Bench Press" highly because
    # the user's name is a partial substring of the canonical name.
    matches = process.extract(
        raw_name,
        candidate_names,
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        limit=3,
    )
    top_name, top_score, top_idx = matches[0]
    exercise = pool[top_idx]

    if top_score >= FUZZY_MATCH_THRESHOLD:
        log.info(
            "log_matched",
            matched=True,
            top_score=top_score,
            exercise_id=exercise.id,
            movement_keyword=keyword or None,
            pool_size=len(pool),
        )
        weight_str = ""
        if entry_dict["weight"] is not None:
            unit = entry_dict.get("weight_unit") or "lbs"
            weight_str = f" at {entry_dict['weight']:g} {unit}"
        response = (
            f"Logged: {entry_dict['sets']}x{entry_dict['reps']} {exercise.name}{weight_str}."
        )
        return {
            "sub_agent_output": {
                "resolved": True,
                "exercise_id": exercise.id,
                "canonical_name": exercise.name,
                "log_entry": entry_dict,
                "match_score": top_score,
            },
            "final_response": response,
        }

    candidate_list = [
        {"name": name, "score": score, "exercise_id": pool[idx].id}
        for name, score, idx in matches
    ]
    log.info(
        "log_matched",
        matched=False,
        top_score=top_score,
        candidates=len(candidate_list),
        movement_keyword=keyword or None,
        pool_size=len(pool),
    )
    options = ", ".join(f"'{c['name']}'" for c in candidate_list)
    response = (
        f"I couldn't confidently match '{raw_name}'. Did you mean one of: {options}?"
    )
    return {
        "sub_agent_output": {
            "resolved": False,
            "candidates": candidate_list,
            "log_entry": entry_dict,
        },
        "final_response": response,
    }


def build_logger_subgraph(
    model: BaseChatModel | None = None,
    dataset: Dataset | None = None,
):
    chat = model if model is not None else chat_model("haiku")
    ds = dataset if dataset is not None else get_dataset()

    graph = StateGraph(HubState)
    graph.add_node("extract", lambda s: _extract(s, model=chat))
    graph.add_node("match", lambda s: _match(s, dataset=ds))
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "match")
    graph.add_edge("match", END)
    return graph.compile()
