"""Per-suite metric calculators."""

from __future__ import annotations

from typing import Any

from spotter.data import get_dataset


def routing_accuracy(results: list[dict[str, Any]]) -> dict[str, float]:
    """Routing suite: percentage of examples whose actual route matches expected."""
    if not results:
        return {"accuracy": 0.0, "n": 0}
    correct = sum(1 for r in results if r.get("actual_route") == r.get("expected_route"))
    confidences_correct = [
        r["actual_confidence"]
        for r in results
        if r.get("actual_route") == r.get("expected_route")
        and isinstance(r.get("actual_confidence"), (int, float))
    ]
    confidences_wrong = [
        r["actual_confidence"]
        for r in results
        if r.get("actual_route") != r.get("expected_route")
        and isinstance(r.get("actual_confidence"), (int, float))
    ]
    threshold_pass = sum(
        1
        for r in results
        if r.get("actual_route") == r.get("expected_route")
        and isinstance(r.get("actual_confidence"), (int, float))
        and r["actual_confidence"] >= r.get("min_confidence", 0.0)
    )
    return {
        "n": len(results),
        "accuracy": correct / len(results),
        "min_confidence_pass_rate": threshold_pass / len(results),
        "mean_confidence_on_correct": (
            sum(confidences_correct) / len(confidences_correct)
            if confidences_correct
            else 0.0
        ),
        "mean_confidence_on_wrong": (
            sum(confidences_wrong) / len(confidences_wrong)
            if confidences_wrong
            else 0.0
        ),
    }


def clarification_recall(results: list[dict[str, Any]]) -> dict[str, float]:
    """Ambiguous suite: percentage of ambiguous inputs that triggered clarification."""
    if not results:
        return {"recall": 0.0, "n": 0}
    triggered = sum(1 for r in results if r.get("clarification_needed") is True)
    return {"n": len(results), "recall": triggered / len(results)}


def empty_search_recovery_rate(results: list[dict[str, Any]]) -> dict[str, float]:
    """Unavailable-equipment suite: rate of non-hallucinating responses."""
    if not results:
        return {"rate": 0.0, "n": 0}
    valid_ids = set(get_dataset().by_id.keys())
    safe = 0
    for r in results:
        response = (r.get("response") or "").strip()
        if not response:
            continue
        # Check no fake UUIDs appear
        fabricated = False
        for chunk in response.split():
            if len(chunk) == 36 and chunk.count("-") == 4 and chunk not in valid_ids:
                fabricated = True
                break
        # Check the response acknowledges the unavailability somehow — accept
        # any mention of the equipment word or 'don't have', "no", "can't"
        ack_words = ["don't", "no ", "not", "unavailable", "instead", "alternative"]
        acknowledges = any(w in response.lower() for w in ack_words)
        if not fabricated and acknowledges:
            safe += 1
    return {
        "n": len(results),
        "rate": safe / len(results),
    }


def coach_judge_summary(results: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate the per-response judge scores into a suite-level summary."""
    if not results:
        return {"n": 0}

    def avg(field: str) -> float:
        values = [r.get(field) for r in results if isinstance(r.get(field), (int, float))]
        return sum(values) / len(values) if values else 0.0

    return {
        "n": len(results),
        "mean_factuality": avg("factuality"),
        "mean_scope_adherence": avg("scope_adherence"),
        "mean_tone": avg("tone"),
    }
