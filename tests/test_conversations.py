"""Unit tests for the trim_history helper."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from spotter.conversations import trim_history


def _alternating(n: int) -> list:
    """Build a list of n alternating HumanMessage/AIMessage."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(HumanMessage(content=f"u{i}"))
        else:
            out.append(AIMessage(content=f"a{i}"))
    return out


def test_trim_returns_last_2n_when_long():
    msgs = _alternating(20)
    trimmed = trim_history(msgs, max_turns=8)
    assert len(trimmed) == 16
    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "u4"
    assert trimmed[-1].content == "a19"


def test_trim_returns_all_when_short():
    msgs = _alternating(4)
    trimmed = trim_history(msgs, max_turns=8)
    assert len(trimmed) == 4
    assert trimmed == msgs


def test_trim_drops_leading_orphan_ai_message():
    # 17 messages: u0,a1,u2,a3,...,a15,u16. Slice last 16 → starts at a1.
    msgs = _alternating(17)
    trimmed = trim_history(msgs, max_turns=8)
    # After slicing to last 16, a1 is the first; drop it.
    assert len(trimmed) == 15
    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "u2"


def test_trim_empty_list():
    assert trim_history([], max_turns=8) == []


def test_trim_single_human_message():
    msgs = [HumanMessage(content="hello")]
    trimmed = trim_history(msgs, max_turns=8)
    assert trimmed == msgs
