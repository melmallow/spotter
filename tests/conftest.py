"""Pytest fixtures — fake chat model wrappers for deterministic testing.

`FakeMessagesListChatModel` from langchain-core does not implement
`with_structured_output()` or `bind_tools()` by default. This module wraps it
with a subclass that overrides both so router/logger/generator tests can script
exact structured-output Pydantic instances and tool-call messages without ever
hitting Anthropic's API.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel


class FakeStructuredChatModel(FakeMessagesListChatModel):
    """Fake chat model with overridable structured output + tool binding.

    For tool-calling tests, script the multi-turn conversation via `responses`:
    each AIMessage in the list is consumed in order — include tool_calls when
    the model should call a tool, plain content when it should return the
    final answer.
    """

    structured_responses: list[BaseModel] = []
    _structured_idx: int = 0
    raise_on_call: bool = False

    def with_structured_output(  # type: ignore[override]
        self, schema: type[BaseModel], **kwargs: Any
    ) -> Runnable:
        """Return a Runnable that yields the next scripted Pydantic instance."""
        responses = self.structured_responses

        def _emit(_input: Any) -> BaseModel:
            if self.raise_on_call:
                raise RuntimeError("scripted LLM failure")
            if not responses:
                raise AssertionError(
                    f"No structured_responses scripted for {schema.__name__}"
                )
            i = self._structured_idx % len(responses)
            object.__setattr__(self, "_structured_idx", i + 1)
            return responses[i]

        return RunnableLambda(_emit)

    def bind_tools(  # type: ignore[override]
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> "FakeStructuredChatModel":
        """Return self — tool-call scripting is via `responses` AIMessages."""
        return self

    def _generate(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ):
        if self.raise_on_call:
            raise RuntimeError("scripted LLM failure")
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.fixture
def fake_chat_model_factory():
    """Returns a builder that produces a `FakeStructuredChatModel`.

    Usage in tests:
        model = fake_chat_model_factory(structured=[RouteDecision(...)])
        model = fake_chat_model_factory(tool_calls=[[{"name": "...", ...}]])
        model = fake_chat_model_factory(raise_on_call=True)
    """

    def _build(
        *,
        structured: list[BaseModel] | None = None,
        responses: list[BaseMessage] | None = None,
        raise_on_call: bool = False,
    ) -> FakeStructuredChatModel:
        return FakeStructuredChatModel(
            responses=responses or [AIMessage(content="")],
            structured_responses=structured or [],
            raise_on_call=raise_on_call,
        )

    return _build


@pytest.fixture
def multiturn_hub():
    """Build a hub with an explicit MemorySaver for multi-turn tests.

    Usage:
        hub = multiturn_hub(router_model=..., logger_model=..., ...)
        out1 = run_hub(hub, "first message", conversation_id="conv-1")
        out2 = run_hub(hub, "follow-up", conversation_id="conv-1")
    """
    from langgraph.checkpoint.memory import MemorySaver

    from spotter.hub import build_hub

    def _build(**model_kwargs):
        return build_hub(checkpointer=MemorySaver(), **model_kwargs)

    return _build
