from __future__ import annotations

import shlex
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from workspace_service.workspaces import WorkspaceManager


class ExecRequest(BaseModel):
    language: Literal["python", "node"]
    code: str
    args: list[str] = Field(default_factory=list)
    stdin: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float | None = None


class ExecResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int


_INTERPRETER = {"python": "python3", "node": "node"}


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["exec"])

    @router.post("/{workspace_id}/exec", response_model=ExecResponse)
    async def exec_code(workspace_id: str, req: ExecRequest,
                        user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        interpreter = _INTERPRETER.get(req.language)
        if interpreter is None:
            raise HTTPException(400, f"unsupported language: {req.language}")

        ws = manager.get_or_open(user)
        started = time.monotonic()
        cmd_parts = [interpreter, "-c", req.code, *req.args]
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        stdin_bytes = req.stdin.encode() if req.stdin else None
        try:
            result = await ws.execute(cmd, stdin=stdin_bytes)
        except Exception as exc:
            raise HTTPException(500, f"execute failed: {exc}")
        elapsed_ms = int((time.monotonic() - started) * 1000)

        stdout = _bytes_to_str(_await_or_attr(result, "materialize_stdout", "stdout"))
        stderr_raw = _await_or_attr(result, "stderr_str", "stderr") or ""
        stderr = stderr_raw if isinstance(stderr_raw, str) else _bytes_to_str(stderr_raw)
        return ExecResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=int(getattr(result, "exit_code", 0) or 0),
            elapsed_ms=elapsed_ms,
        )

    return router


def _await_or_attr(obj, method_name: str, attr_name: str):
    if hasattr(obj, method_name):
        import asyncio
        m = getattr(obj, method_name)()
        if asyncio.iscoroutine(m):
            import concurrent.futures
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Called from async context — cannot block. Caller must await.
                # Fall back to sync attr.
                return getattr(obj, attr_name, b"")
        return m
    return getattr(obj, attr_name, b"")


def _bytes_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)
