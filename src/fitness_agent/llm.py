"""Anthropic Claude chat-model factory with haiku/sonnet tiering."""

from __future__ import annotations

from typing import Literal

from langchain_anthropic import ChatAnthropic

from fitness_agent.config import (
    ANTHROPIC_API_KEY,
    HAIKU_MODEL,
    LLM_TIMEOUT_SECONDS,
    SONNET_MODEL,
)

Tier = Literal["haiku", "sonnet"]


def chat_model(tier: Tier = "haiku", temperature: float = 0.0) -> ChatAnthropic:
    """Return a ChatAnthropic configured for the requested tier.

    - haiku: fast/cheap structured-output classification (router, log extraction).
    - sonnet: quality-dominant generation (coach answers, workout tool-calling).
    """
    model_name = HAIKU_MODEL if tier == "haiku" else SONNET_MODEL
    return ChatAnthropic(
        model=model_name,
        temperature=temperature,
        timeout=LLM_TIMEOUT_SECONDS,
        api_key=ANTHROPIC_API_KEY or None,
        max_retries=2,
    )
