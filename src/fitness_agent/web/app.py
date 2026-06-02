"""FastAPI app — serves the chat UI and exposes POST /chat."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from fitness_agent.hub import build_hub, run_hub
from fitness_agent.logging_setup import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
    get_logger,
)


configure_logging()
log = get_logger("web")

_INDEX_HTML_PATH = Path(__file__).parent / "templates" / "index.html"


class ChatRequest(BaseModel):
    """Schema for POST /chat — keeps malformed bodies out of the hub."""

    message: str = Field(min_length=1, max_length=2000)


def create_app() -> FastAPI:
    """Build the FastAPI app with a long-lived hub instance."""
    app = FastAPI(title="Future Coach", version="0.1.0")
    hub = build_hub()

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

    _index_html = _INDEX_HTML_PATH.read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return HTMLResponse(content=_index_html)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(req: ChatRequest) -> JSONResponse:
        result = run_hub(hub, req.message)
        # Convert any workout payload sitting inside sub_agent_output into the
        # human-facing response text — keeps the response string self-contained.
        rendered = _render_response(result["response"], result.get("workout"))
        payload = {
            "response": rendered,
            "route": result.get("route"),
            "confidence": result.get("confidence"),
            "trace_id": result.get("trace_id"),
        }
        return JSONResponse(payload)

    return app


def _render_response(text: str, workout: dict | None) -> str:
    """If a structured workout came back, append a human-readable summary."""
    if not workout or not isinstance(workout, dict) or "blocks" not in workout:
        return text

    lines: list[str] = []
    if text and text.strip():
        lines.append(text.strip())
        lines.append("")

    for block in workout["blocks"]:
        name = block.get("name", "block").upper()
        items = block.get("items", [])
        if not items:
            continue
        lines.append(f"**{name}**")
        for item in items:
            label = item.get("exercise_name", "exercise")
            sets = item.get("sets")
            reps = item.get("reps")
            duration = item.get("duration_seconds")
            rest = item.get("rest_seconds")
            side = item.get("side_note")
            prescription = (
                f"{sets}x{reps}"
                if reps
                else f"{sets}x{duration}s"
                if duration
                else f"{sets} sets"
            )
            side_str = f" ({side})" if side else ""
            rest_str = f", rest {rest}s" if rest is not None else ""
            lines.append(f"- {prescription} {label}{side_str}{rest_str}")
        lines.append("")
    return "\n".join(lines).rstrip()


app = create_app()
