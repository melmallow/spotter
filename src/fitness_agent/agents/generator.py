"""Workout Generator subgraph — tool-calling agent using sonnet."""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from fitness_agent.llm import chat_model
from fitness_agent.logging_setup import get_logger
from fitness_agent.schemas import HubState
from fitness_agent.tools.build_workout import build_workout
from fitness_agent.tools.search_exercises import search_exercises


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
   warmup, main, and cooldown blocks with sets/reps/rest.
4. After tools complete, write a brief response describing the workout in plain language.

Constraints:
- Every exercise_id you pass to build_workout MUST come from a previous search_exercises result.
- Aim for 1-2 warmup, 3-5 main, 1-2 cooldown items unless the user requests otherwise.
- Match prescription style to dataset (rep-based vs duration-based)."""


_MAX_TOOL_LOOPS = 6


def _agent_node(
    state: HubState, *, model: BaseChatModel, tools: list[Any]
) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages:
        messages = [
            SystemMessage(content=GENERATOR_SYSTEM_PROMPT),
            HumanMessage(content=state["user_input"]),
        ]

    bound = model.bind_tools(tools)
    started = time.perf_counter()
    response: AIMessage = bound.invoke(messages)
    log.info(
        "agent_step",
        success=True,
        has_tool_calls=bool(getattr(response, "tool_calls", None)),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return {"messages": messages + [response]}


def _tools_node(
    state: HubState, *, tools_by_name: dict[str, Any]
) -> dict[str, Any]:
    last = state["messages"][-1]
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
    return {"messages": list(state["messages"]) + tool_messages}


def _should_continue(state: HubState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "finalize"


def _finalize(state: HubState) -> dict[str, Any]:
    last_ai = next(
        (
            m
            for m in reversed(state["messages"])
            if isinstance(m, AIMessage) and not m.tool_calls
        ),
        None,
    )
    text = (
        last_ai.content
        if last_ai is not None and isinstance(last_ai.content, str)
        else "I couldn't put a workout together — please try a different request."
    )

    # Extract the most recent build_workout tool result for the sub_agent_output
    workout_payload: dict | None = None
    for m in reversed(state["messages"]):
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
    }


def build_generator_subgraph(model: BaseChatModel | None = None):
    chat = model if model is not None else chat_model("sonnet", temperature=0.4)
    tools = [search_exercises, build_workout]
    tools_by_name = {t.name: t for t in tools}

    graph = StateGraph(HubState)
    graph.add_node("agent", lambda s: _agent_node(s, model=chat, tools=tools))
    graph.add_node(
        "tools", lambda s: _tools_node(s, tools_by_name=tools_by_name)
    )
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "finalize": "finalize"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile().with_config(recursion_limit=_MAX_TOOL_LOOPS * 3)
