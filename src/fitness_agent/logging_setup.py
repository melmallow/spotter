"""structlog configuration — JSON output, trace_id contextvar propagation."""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

from fitness_agent.config import LOGS_DIR, TRACE_LOG_PATH


def configure_logging() -> None:
    """Configure structlog and stdlib logging — call once at process start."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(TRACE_LOG_PATH, mode="a")
    file_handler.setFormatter(logging.Formatter("%(message)s"))

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [stdout_handler, file_handler]

    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


__all__ = [
    "bind_contextvars",
    "clear_contextvars",
    "configure_logging",
    "get_logger",
]
