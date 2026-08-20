"""FastAPI application: the sourcing advisor UI and its streaming endpoint.

    python -m web.app        # http://127.0.0.1:8000

The agent run is streamed to the browser as Server-Sent Events. SSE rather than a
WebSocket because the traffic is strictly one-way -- the browser sends one request
and then only reads -- and SSE reconnects on its own.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse

from agent.sourcing_agent import (
    CUSTOM_TOOLS,
    PLAYWRIGHT_TOOLS,
    build_options,
    run_sourcing_query,
)

load_dotenv()

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Import Sourcing Advisor", version="1.0.0")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "index.html")


@app.get("/api/health")
async def health() -> dict:
    """What the app knows about its own configuration, for the connections panel."""
    options = build_options()
    return {
        "data_mode": os.environ.get("SOURCING_MODE", "live"),
        "model": options.model,
        "credential": "ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY") else "Claude Code login",
        "servers": {
            "trade-sourcing": {"transport": "stdio", "declared_tools": CUSTOM_TOOLS},
            "playwright": {"transport": "stdio", "declared_tools": PLAYWRIGHT_TOOLS},
        },
    }


@app.get("/api/run")
async def run(
    question: str = Query(..., min_length=5, description="The sourcing question to answer."),
    replay: bool = Query(False, description="Serve trade data from recorded fixtures."),
    playwright: bool = Query(True, description="Attach the Playwright MCP server."),
    break_playwright: bool = Query(False, description="Point the browser at an unreachable host."),
) -> StreamingResponse:
    """Stream one agent run as Server-Sent Events."""

    async def event_stream():
        # Tell the client the run started before the first agent turn, so the UI can
        # switch out of its idle state even if the model takes a while to respond.
        yield _sse({"kind": "status", "text": "connecting to MCP servers", "data": {}})
        try:
            async for event in run_sourcing_query(
                question,
                replay=replay,
                include_playwright=playwright,
                break_playwright=break_playwright,
            ):
                yield _sse(event.to_dict())
        except asyncio.CancelledError:  # browser navigated away
            raise
        except Exception as exc:  # noqa: BLE001 - surface, never swallow
            yield _sse({"kind": "error", "text": f"{type(exc).__name__}: {exc}", "data": {}})
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def main() -> None:
    import uvicorn

    uvicorn.run(
        "web.app:app",
        host=os.environ.get("SOURCING_HOST", "127.0.0.1"),
        port=int(os.environ.get("SOURCING_PORT", "8000")),
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
