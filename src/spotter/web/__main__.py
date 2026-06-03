"""Launch the FastAPI demo via `python -m spotter.web` or `python -m spotter`."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port_env = os.environ.get("PORT")
    host = "0.0.0.0" if port_env else "127.0.0.1"
    port = int(port_env) if port_env else 8000
    uvicorn.run(
        "spotter.web.app:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
