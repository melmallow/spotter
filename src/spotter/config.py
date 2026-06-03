"""Process-wide configuration loaded from env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
EXERCISE_DATA_PATH = Path(
    os.environ.get("EXERCISE_DATA_PATH", REPO_ROOT / "exercises.json")
)
LOGS_DIR = REPO_ROOT / "logs"
TRACE_LOG_PATH = LOGS_DIR / "trace.jsonl"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.6"))
FUZZY_MATCH_THRESHOLD = int(os.environ.get("FUZZY_MATCH_THRESHOLD", "75"))
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "8"))

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"

LLM_TIMEOUT_SECONDS = 30
