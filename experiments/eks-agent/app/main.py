"""FastAPI HTTP entrypoint. Streams LangGraph events as SSE text.

POST /invoke
    Body: {"prompt": "..."}
    Header: X-Session-Id (optional; defaults to "default")
    Returns: text/event-stream — one chunk per model text delta.

GET /healthz  → 200
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from agent import build_agent

_agent = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _agent
    _agent = build_agent()
    yield


app = FastAPI(lifespan=_lifespan)


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


def _text_from_chunk(chunk) -> str:
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


@app.post("/invoke")
async def invoke(request: Request, x_session_id: str | None = Header(default=None)):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise HTTPException(status_code=400, detail="prompt must be a string")

    session_id = x_session_id or "default"

    async def _stream():
        async for event in _agent.astream_events(
            {"messages": [{"role": "user", "content": prompt}]},
            version="v2",
            config={"configurable": {"thread_id": session_id}},
        ):
            if event.get("event") != "on_chat_model_stream":
                continue
            text = _text_from_chunk(event.get("data", {}).get("chunk"))
            if text:
                yield text

    return StreamingResponse(_stream(), media_type="text/event-stream")
