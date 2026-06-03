"""FastAPI app — serves the chat UI and exposes POST /chat."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from spotter.hub import build_hub, run_hub
from spotter.logging_setup import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
    get_logger,
)


configure_logging()
log = get_logger("web")

_INDEX_HTML_PATH = Path(__file__).parent / "templates" / "index.html"
_STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    """Schema for POST /chat — keeps malformed bodies out of the hub."""

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )


def create_app() -> FastAPI:
    """Build the FastAPI app with a long-lived hub instance."""
    app = FastAPI(title="Spotter", version="0.1.0")
    hub = build_hub(checkpointer=MemorySaver())

    _STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        trace_id = f"req-{uuid.uuid4().hex[:12]}"
        bind_contextvars(trace_id=trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            clear_contextvars()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        # Read fresh each request so template edits show on refresh without a restart.
        return HTMLResponse(content=_INDEX_HTML_PATH.read_text(encoding="utf-8"))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(req: ChatRequest) -> JSONResponse:
        result = run_hub(hub, req.message, conversation_id=req.conversation_id)
        payload = {
            "response": result["response"],
            "route": result.get("route"),
            "confidence": result.get("confidence"),
            "trace_id": result.get("trace_id"),
            "conversation_id": result.get("conversation_id"),
            "log_entry": result.get("log_entry"),
        }
        return JSONResponse(payload)

    return app


app = create_app()
