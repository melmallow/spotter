"""Launch the FastAPI demo via `python -m spotter.web` or `python -m spotter`."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "spotter.web.app:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
