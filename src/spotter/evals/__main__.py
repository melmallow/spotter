"""CLI entrypoint — `python -m spotter.evals --suite routing|ambiguous|...|all`."""

from __future__ import annotations

import argparse
import sys

from spotter.evals.runner import SUITES, print_summary, run_suite
from spotter.hub import build_hub
from spotter.logging_setup import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run real-Claude evaluations against the labeled prompt suites."
    )
    parser.add_argument(
        "--suite",
        choices=(*SUITES, "all"),
        default="routing",
        help="Which suite to run. 'all' runs every suite sequentially.",
    )
    args = parser.parse_args()

    configure_logging()
    hub = build_hub()

    suites_to_run = SUITES if args.suite == "all" else (args.suite,)
    for s in suites_to_run:
        try:
            payload = run_suite(s, hub=hub)
            print_summary(s, payload)
        except Exception as exc:
            print(f"\n=== {s} (FAILED) ===")
            print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
