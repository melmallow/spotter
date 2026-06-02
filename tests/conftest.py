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
    """Fake chat model with overridable structured output + tool binding."""

    structured_responses: list[BaseModel] = []
    tool_call_responses: list[list[dict[str, Any]]] = []
    _structured_idx: int = 0
    _tool_idx: int = 0
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
            type(self)._structured_idx_setter(self, i + 1)
            return responses[i]

        return RunnableLambda(_emit)

    @staticmethod
    def _structured_idx_setter(obj: "FakeStructuredChatModel", val: int) -> None:
        object.__setattr__(obj, "_structured_idx", val)

    def bind_tools(  # type: ignore[override]
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> "FakeStructuredChatModel":
        """Return self with the scripted tool_call_responses unchanged."""
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
        if self.tool_call_responses:
            calls = self.tool_call_responses[self._tool_idx % len(self.tool_call_responses)]
            type(self)._tool_idx_setter(self, self._tool_idx + 1)
            msg = AIMessage(content="", tool_calls=calls)
            from langchain_core.outputs import ChatGeneration, ChatResult

            return ChatResult(generations=[ChatGeneration(message=msg)])
        return super()._generate(messages, stop, run_manager, **kwargs)

    @staticmethod
    def _tool_idx_setter(obj: "FakeStructuredChatModel", val: int) -> None:
        object.__setattr__(obj, "_tool_idx", val)


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
        tool_calls: list[list[dict[str, Any]]] | None = None,
        raise_on_call: bool = False,
        responses: list[BaseMessage] | None = None,
    ) -> FakeStructuredChatModel:
        return FakeStructuredChatModel(
            responses=responses or [AIMessage(content="")],
            structured_responses=structured or [],
            tool_call_responses=tool_calls or [],
            raise_on_call=raise_on_call,
        )

    return _build
