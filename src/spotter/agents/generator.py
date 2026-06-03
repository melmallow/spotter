"""Workout Generator subgraph — tool-calling agent using sonnet."""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph

from spotter.config import MAX_HISTORY_TURNS
from spotter.conversations import trim_history
from spotter.llm import chat_model
from spotter.logging_setup import get_logger
from spotter.schemas import HubState
from spotter.tools.build_workout import build_workout
from spotter.tools.search_exercises import search_exercises


log = get_logger("generator")


GENERATOR_SYSTEM_PROMPT = """You build personalized workouts using two tools.

Workflow:
1. Call `search_exercises` to find candidates matching the user's muscle / equipment /
   movement / avoid_joints constraints. ALWAYS extract `avoid_joints` from the user message
   when they mention injuries, joints to avoid, or "bad" body parts.
2. Read the search results. If `exercises` is empty, the result includes a `reason` —
   surface that honestly to the user and suggest alternatives the dataset DOES support.
   NEVER fabricate exercise IDs or names that did not appear in a search result.
3. If results are good, call `build_workout` with selected exercise IDs grouped into
   warmup, main, and cooldown blocks with sets/reps/rest. The `notes` field MUST
   be a short title — a noun phrase of 3–7 words, NO commas, NO em-dashes, NO
   sentences. It becomes the saved-workout's TITLE in a compact list, like a
   filename. GOOD: "Arms day · biceps and triceps", "30-min upper push", "Glute
   strength block", "Full-body kettlebell flow". BAD (do NOT do this):
   "A focused arms workout targeting biceps, triceps, and forearms", "A glute-
   focused lower body workout hitting the glutes from multiple angles". If you
   write a full sentence in `notes`, you have done it wrong.
4. After tools complete, write a SHORT chat reply: at most 2 sentences, total
   length under 240 characters. Describe the workout's intent in plain prose.
   You MUST NOT include any of the following: bullet points, numbered lists,
   markdown headings, tables, equipment lists, tip lists, exercise names, or
   sets/reps/duration. The UI renders the full structured workout card right
   below your text — repeating any of that information is duplication and
   clutters the chat. Plain prose only. If you find yourself writing "Tips:"
   or "Equipment:" or a bullet, delete it and write a single prose sentence
   instead.

Dataset vocabulary — use these EXACT terms in tool calls:
- muscle_groups: biceps, calves, chest, core, deltoids (= shoulders), forearms, glutes,
  hamstrings, hip adductors, hip flexors, lats, lower back, middle back, obliques, quads,
  rotator cuff, traps, triceps, upper back
- equipment (singular, capitalized): Adjustable Bench - Decline, Adjustable Bench - Incline,
  Barbell, BOSU, Box, Cable Resistance Machine, Chest Supported Row Machine, Dumbbell, EZ Bar,
  Flat Bench, Handle Attachment, Horizontal Leg Press Machine, Jump Rope, Kettlebell,
  Lacrosse Ball, Medicine Ball, Miniband, Plate, Preacher Curl Bench, Pull-Up Bar, Rack,
  Resistance Band - Loop, Resistance Band - With Handles, Sandbag, Seated Lat Pulldown Machine,
  SkiErg, Slant Board, Stability Ball, Stair Climber, Suspension Trainer, Yoga Mat
- joints (for avoid_joints): ankle, cervical spine, elbow, hip, knee, lumbar spine,
  shoulder, thoracic spine, wrist

Constraints:
- Every exercise_id you pass to build_workout MUST come from a previous search_exercises result.
- Aim for 1-2 warmup, 3-5 main, 1-2 cooldown items unless the user requests otherwise.
- Match prescription style to dataset (rep-based vs duration-based).
- For build_workout items, each entry needs: exercise_id, sets, reps OR duration_seconds,
  rest_seconds. Use rest_seconds=30-90 for typical work."""


_MAX_TOOL_LOOPS = 6


def _init_scratch(state: HubState) -> dict[str, Any]:
    """Build the generator's tool-call working list from the conversation transcript."""
    messages = state.get("messages") or []
    trimmed = trim_history(messages, MAX_HISTORY_TURNS)
    scratch: list[BaseMessage] = [
        SystemMessage(content=GENERATOR_SYSTEM_PROMPT),
        *trimmed,
    ]
    return {"generator_scratch": scratch}


def _agent_node(
    state: HubState, *, model: BaseChatModel, tools: list[Any]
) -> dict[str, Any]:
    scratch = state["generator_scratch"]
    bound = model.bind_tools(tools)
    started = time.perf_counter()
    response: AIMessage = bound.invoke(scratch)
    log.info(
        "agent_step",
        success=True,
        has_tool_calls=bool(getattr(response, "tool_calls", None)),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return {"generator_scratch": scratch + [response]}


def _tools_node(
    state: HubState, *, tools_by_name: dict[str, Any]
) -> dict[str, Any]:
    scratch = state["generator_scratch"]
    last = scratch[-1]
    tool_messages: list[ToolMessage] = []
    for call in getattr(last, "tool_calls", []) or []:
        tool = tools_by_name.get(call["name"])
        if tool is None:
            tool_messages.append(
                ToolMessage(
                    content=f"unknown tool: {call['name']}",
                    tool_call_id=call.get("id", "unknown"),
                )
            )
            continue
        try:
            result = tool.invoke(call.get("args", {}))
        except Exception as exc:
            log.warning(
                "tool_call",
                tool_name=call["name"],
                success=False,
                error_class=type(exc).__name__,
            )
            result = {"error": str(exc), "error_class": type(exc).__name__}
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, default=str),
                tool_call_id=call.get("id", "unknown"),
            )
        )
    return {"generator_scratch": scratch + tool_messages}


def _should_continue(state: HubState) -> str:
    last = state["generator_scratch"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "finalize"


def _finalize(state: HubState) -> dict[str, Any]:
    scratch = state["generator_scratch"]
    last_ai = next(
        (
            m
            for m in reversed(scratch)
            if isinstance(m, AIMessage) and not m.tool_calls
        ),
        None,
    )
    text = (
        last_ai.content
        if last_ai is not None and isinstance(last_ai.content, str)
        else "I couldn't put a workout together — please try a different request."
    )

    workout_payload: dict | None = None
    for m in reversed(scratch):
        if isinstance(m, ToolMessage):
            try:
                payload = json.loads(m.content)
                if isinstance(payload, dict) and "blocks" in payload:
                    workout_payload = payload
                    break
            except (json.JSONDecodeError, TypeError):
                continue

    return {
        "sub_agent_output": {"workout": workout_payload, "narrative": text},
        "final_response": text,
        "messages": [AIMessage(content=text)],
    }


def build_generator_subgraph(model: BaseChatModel | None = None):
    chat = model if model is not None else chat_model("sonnet", temperature=0.4)
    tools = [search_exercises, build_workout]
    tools_by_name = {t.name: t for t in tools}

    graph = StateGraph(HubState)
    graph.add_node("init", _init_scratch)
    graph.add_node("agent", lambda s: _agent_node(s, model=chat, tools=tools))
    graph.add_node(
        "tools", lambda s: _tools_node(s, tools_by_name=tools_by_name)
    )
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "init")
    graph.add_edge("init", "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "finalize": "finalize"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile().with_config(recursion_limit=_MAX_TOOL_LOOPS * 3)
