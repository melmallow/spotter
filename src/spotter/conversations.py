"""Conversation helpers — history-window trimming.

The full untrimmed transcript is held by LangGraph's checkpointer keyed by
thread_id. This module only handles the "trim to last N turns before passing
to an LLM" boundary.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage


def trim_history(messages: list[BaseMessage], max_turns: int) -> list[BaseMessage]:
    """Return the last `2 * max_turns` messages, dropping a leading orphan AIMessage.

    A "turn" is one HumanMessage + one AIMessage. The trimmed list is guaranteed
    to start with a HumanMessage so LLM calls don't begin with a dangling
    assistant reply. If trimming would cut mid-turn (leaving an AIMessage at the
    front), drop that orphan.

    Empty input returns empty output. Lists shorter than the window are returned
    unchanged.
    """
    if not messages:
        return []
    keep = 2 * max_turns
    trimmed = messages[-keep:] if len(messages) > keep else list(messages)
    if trimmed and isinstance(trimmed[0], AIMessage):
        trimmed = trimmed[1:]
    return trimmed
