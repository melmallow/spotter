"""LLM-as-judge — sonnet scores COACH responses on factuality, scope, tone."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from fitness_agent.llm import chat_model


class CoachScore(BaseModel):
    """Structured score returned by the judge."""

    factuality: int = Field(
        ge=1, le=5, description="1=many wrong claims, 5=all facts correct."
    )
    scope_adherence: int = Field(
        ge=1,
        le=5,
        description=(
            "1=drifted off-topic, 5=stayed strictly within fitness scope guard."
        ),
    )
    tone: int = Field(
        ge=1,
        le=5,
        description="1=condescending or hedgy, 5=clear, confident, conversational.",
    )
    justification: str = Field(description="One sentence explaining the scores.")


JUDGE_SYSTEM_PROMPT = """You are evaluating a COACH agent's response in a fitness coaching system.

You receive:
- The user's question
- A list of reference facts the response should align with
- The agent's response

Score each axis from 1 to 5 using the criteria in the schema. Be honest — a score of 5 means
there is nothing to improve. If the response is empty, factually wrong, or off-topic, score low."""


def judge_coach_response(
    question: str, reference_facts: list[str], response: str
) -> CoachScore:
    """Call Claude sonnet to score the response. Caller handles errors."""
    judge = chat_model("sonnet", temperature=0.0)
    structured = judge.with_structured_output(CoachScore)
    facts_block = "\n".join(f"- {f}" for f in reference_facts)
    user = (
        f"Question:\n{question}\n\n"
        f"Reference facts:\n{facts_block}\n\n"
        f"Agent response:\n{response.strip() or '<empty>'}"
    )
    return structured.invoke(
        [
            ("system", JUDGE_SYSTEM_PROMPT),
            ("human", user),
        ]
    )
