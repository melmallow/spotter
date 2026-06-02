# Critical-path tests

This suite is intentionally small. The PRD asks for at least two critical-path tests, and these are the two we picked — chosen because each catches a class of failure that, if regressed, would silently degrade the system's trustworthiness:

## `test_router_clarification.py` — critical path #1

**What it catches:** silent misrouting on ambiguous input.

The router is the only component that makes a routing decision per request. If it misroutes confidently, every downstream sub-agent runs against the wrong intent, the user gets a wrong answer, and the structured logs make it look like the system worked. The PRD explicitly calls out "Bench press" as the kind of input that should not silently misroute. This test asserts that low confidence → clarification, not silent fallback.

The companion assertions cover (a) high-confidence routing succeeds without clarification, (b) routing errors (LLM failures) fall back to clarification rather than crashing, and (c) threshold boundary behavior is exact.

## `test_generator_empty_search.py` — critical path #2

**What it catches:** hallucinated exercises when the dataset doesn't contain the requested equipment.

This is the highest-leverage resilience check because the failure is invisible to the user without ground truth — a fabricated "Rowing Machine Pull" sounds plausible to a non-expert reader. The test asserts that when `search_exercises` returns no results, the generator surfaces an honest "no match" reply and that **every exercise ID referenced in the response exists in the dataset**.

The companion assertions also cover bilateral auto-pairing (same record, side-flipped second set) and the injury filter (joints exclusion).

## What these tests deliberately do not prove

These tests stub the LLM with a wrapper around `FakeMessagesListChatModel` that overrides `.with_structured_output()` and `.bind_tools()` to return canned Pydantic instances and tool-call messages. They prove the graph wiring works given a scripted LLM. They do **not** prove Claude actually routes correctly in production — that's what the `evals/` suite measures against real Claude. The unit tests don't pretend to be the eval suite.
