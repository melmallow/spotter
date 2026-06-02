"""Eval runner — invokes the hub against labeled prompt suites."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from spotter.config import REPO_ROOT
from spotter.evals.judge import judge_coach_response
from spotter.evals.metrics import (
    clarification_recall,
    coach_judge_summary,
    empty_search_recovery_rate,
    routing_accuracy,
)
from spotter.hub import build_hub, run_hub
from spotter.logging_setup import configure_logging, get_logger


log = get_logger("evals")

EVAL_DATA_DIR = REPO_ROOT / "evals" / "data"
EVAL_RESULTS_DIR = REPO_ROOT / "evals" / "results"

SUITES = ("routing", "ambiguous", "unavailable_equipment", "coach")


def _load_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _run_one(hub, example: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_hub(hub, example["input"])
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "input": example["input"],
        "actual_route": result.get("route"),
        "actual_confidence": result.get("confidence"),
        "response": result.get("response"),
        "trace_id": result.get("trace_id"),
        "latency_ms": latency_ms,
    }


def run_routing(hub) -> tuple[list[dict[str, Any]], dict[str, float]]:
    examples = list(_load_jsonl(EVAL_DATA_DIR / "routing.jsonl"))
    results = []
    for ex in examples:
        row = _run_one(hub, ex)
        row["expected_route"] = ex["expected_route"]
        row["min_confidence"] = ex.get("min_confidence", 0.0)
        results.append(row)
    return results, routing_accuracy(results)


def run_ambiguous(hub) -> tuple[list[dict[str, Any]], dict[str, float]]:
    examples = list(_load_jsonl(EVAL_DATA_DIR / "ambiguous.jsonl"))
    results = []
    for ex in examples:
        row = _run_one(hub, ex)
        row["expected_clarification"] = ex.get("expected_clarification", True)
        # The router output ride along inside `actual_route`/`actual_confidence`,
        # but the actual clarification signal lives in the hub response shape:
        # the clarification node sets route=UNKNOWN-ish behavior; we infer from
        # the response text and the absence of a real route.
        row["clarification_needed"] = (
            row.get("actual_route") in (None, "UNKNOWN")
            or (
                isinstance(row.get("actual_confidence"), (int, float))
                and row["actual_confidence"] < 0.6
            )
            or "not sure" in (row.get("response") or "").lower()
        )
        results.append(row)
    return results, clarification_recall(results)


def run_unavailable_equipment(hub) -> tuple[list[dict[str, Any]], dict[str, float]]:
    examples = list(_load_jsonl(EVAL_DATA_DIR / "unavailable_equipment.jsonl"))
    results = []
    for ex in examples:
        row = _run_one(hub, ex)
        row["unavailable_equipment"] = ex.get("unavailable_equipment")
        results.append(row)
    return results, empty_search_recovery_rate(results)


def run_coach(hub) -> tuple[list[dict[str, Any]], dict[str, float]]:
    examples = list(_load_jsonl(EVAL_DATA_DIR / "coach.jsonl"))
    results = []
    for ex in examples:
        row = _run_one(hub, ex)
        try:
            score = judge_coach_response(
                ex["input"], ex.get("reference_facts", []), row["response"] or ""
            )
            row["factuality"] = score.factuality
            row["scope_adherence"] = score.scope_adherence
            row["tone"] = score.tone
            row["judge_justification"] = score.justification
        except Exception as exc:
            row["judge_error"] = type(exc).__name__
        results.append(row)
    return results, coach_judge_summary(results)


def write_results(suite: str, results: list[dict[str, Any]]) -> Path:
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = EVAL_RESULTS_DIR / f"{suite}-{timestamp}.jsonl"
    with open(path, "w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")
    return path


def run_suite(suite_name: str, hub=None) -> dict[str, Any]:
    if hub is None:
        configure_logging()
        hub = build_hub()
    if suite_name == "routing":
        results, summary = run_routing(hub)
    elif suite_name == "ambiguous":
        results, summary = run_ambiguous(hub)
    elif suite_name == "unavailable_equipment":
        results, summary = run_unavailable_equipment(hub)
    elif suite_name == "coach":
        results, summary = run_coach(hub)
    else:
        raise ValueError(f"unknown suite: {suite_name}")
    out_path = write_results(suite_name, results)
    return {"suite": suite_name, "results_path": str(out_path), "summary": summary}


def print_summary(suite: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {suite} ===")
    for k, v in payload["summary"].items():
        if isinstance(v, float):
            print(f"  {k:30s} {v:.3f}")
        else:
            print(f"  {k:30s} {v}")
    print(f"  results -> {payload['results_path']}")
