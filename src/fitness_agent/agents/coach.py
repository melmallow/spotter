"""Coach subgraph — single sonnet call with scope-guarded system prompt."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from fitness_agent.llm import chat_model
from fitness_agent.logging_setup import get_logger
from fitness_agent.schemas import HubState


log = get_logger("coach")


COACH_SYSTEM_PROMPT = """You are Future Coach, an evidence-informed fitness coach.

You answer questions about:
- Exercise anatomy (which muscles, joints, and movement patterns are involved)
- Exercise form and common cues
- Programming concepts (volume, intensity, frequency, progressive overload)
- Differences between exercises and training styles

You do NOT cover:
- Medical advice, injury diagnosis, or rehab protocols
- Nutrition, supplements, calories, macros, or diet
- Anything unrelated to physical training

When a question is off-topic, briefly say so in one sentence and offer to help with a fitness-related question instead.

Keep answers concise (2-4 sentences) unless the user asks for more depth. Cite anatomy precisely and avoid hedging."""


def _answer(state: HubState, *, model: BaseChatModel) -> dict[str, Any]:
    user_input = state["user_input"]
    started = time.perf_counter()
    try:
        response = model.invoke(
            [
                ("system", COACH_SYSTEM_PROMPT),
                ("human", user_input),
            ]
        )
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        log.warning(
            "coach_answered",
            success=False,
            error_class=type(exc).__name__,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return {
            "sub_agent_output": {"answer": None, "error": str(exc)},
            "final_response": (
                "Sorry — I hit an error answering that. Try rephrasing?"
            ),
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "coach_answered",
        success=True,
        length=len(answer) if isinstance(answer, str) else 0,
        latency_ms=latency_ms,
    )
    return {
        "sub_agent_output": {"answer": answer},
        "final_response": answer,
    }


def build_coach_subgraph(model: BaseChatModel | None = None):
    chat = model if model is not None else chat_model("sonnet", temperature=0.3)

    graph = StateGraph(HubState)
    graph.add_node("answer", lambda s: _answer(s, model=chat))
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()
