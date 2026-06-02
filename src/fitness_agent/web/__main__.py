"""Launch the FastAPI demo via `python -m fitness_agent.web` or `python -m fitness_agent`."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "fitness_agent.web.app:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
