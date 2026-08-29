"""Single global FastMCP at /mcp.

All tools resolve caller from the X-User-Id header (set into a contextvar
by the /mcp middleware in main.py). Session lifecycle + execute tools
verify session ownership.
"""

from __future__ import annotations

import base64
from typing import Literal

from fastapi import HTTPException
from fastmcp import FastMCP

from workspace_service.session_ctx import current_user_id
from workspace_service.workspaces import SessionManager


def _require_user() -> str:
    uid = current_user_id.get()
    if not uid:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return uid


def build_mcp(manager: SessionManager) -> FastMCP:
    mcp = FastMCP("vfs-workspace")

    # --- file IO (no session; hits caller's S3 prefix directly) ---

    @mcp.tool
    def read(file_path: str) -> dict:
        """Read a file from the caller's workspace."""
        data, err = manager.s3io(_require_user()).read(file_path)
        if err is not None:
            return {"error": err}
        try:
            return {"content": data.decode("utf-8")}
        except UnicodeDecodeError:
            return {"content_b64": base64.b64encode(data).decode()}

    @mcp.tool
    def write(file_path: str, content: str) -> dict:
        """Write a file to the caller's workspace."""
        err = manager.s3io(_require_user()).write(file_path, content.encode("utf-8"))
        return {"error": err} if err else {"path": file_path}

    @mcp.tool
    def delete(file_path: str) -> dict:
        """Delete a file from the caller's workspace."""
        err = manager.s3io(_require_user()).delete(file_path)
        return {"error": err} if err else {"path": file_path}

    @mcp.tool
    def ls(path: str = "/") -> dict:
        """List entries under a directory in the caller's workspace."""
        entries = [
            {"path": e.path, "is_dir": e.is_dir, "size": e.size}
            for e in manager.s3io(_require_user()).ls(path)
        ]
        return {"entries": entries}

    # --- session lifecycle (caller-owned) ---

    @mcp.tool
    async def start_session() -> dict:
        """Start a new interpreter session for the caller."""
        uid = _require_user()
        try:
            session = await manager.start_session(uid)
        except Exception as exc:
            return {"error": f"start_session failed: {exc}"}
        return {"session_id": session.session_id, "runtime": session.interpreter.runtime}

    @mcp.tool
    async def stop_session(session_id: str) -> dict:
        """Stop one of the caller's sessions."""
        uid = _require_user()
        if manager.get_session(uid, session_id) is None:
            return {"error": f"unknown session: {session_id}"}
        await manager.stop_session(uid, session_id)
        return {"stopped": True, "session_id": session_id}

    @mcp.tool
    def list_sessions() -> dict:
        """List the caller's active session ids."""
        return {"session_ids": manager.list_sessions(_require_user())}

    # --- execute (session-scoped, ownership-checked) ---

    @mcp.tool
    async def execute_code(
        session_id: str,
        code: str,
        language: Literal["python", "node", "bash"] = "python",
        clear_context: bool = False,
    ) -> dict:
        """Run inline code in the named session's interpreter."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        result = await session.interpreter.execute_code(code, language, clear_context)
        return _result_dict(result)

    @mcp.tool
    async def execute_command(session_id: str, command: str) -> dict:
        """Run a shell command in the named session's interpreter."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        result = await session.interpreter.execute_command(command)
        return _result_dict(result)

    @mcp.tool
    async def start_command_execution(session_id: str, command: str) -> dict:
        """Start a long-running command; returns a task_id."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        try:
            task_id = await session.interpreter.start_command_execution(command)
        except Exception as exc:
            return {"error": f"start_command_execution failed: {exc}"}
        return {"task_id": task_id}

    @mcp.tool
    async def get_task(session_id: str, task_id: str) -> dict:
        """Fetch status + captured output of a task."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        task = await session.interpreter.get_task(task_id)
        return {
            "task_id": task.task_id,
            "status": task.status,
            "stdout": task.stdout,
            "stderr": task.stderr,
            "exit_code": task.exit_code,
            "execution_time_ms": task.execution_time_ms,
        }

    @mcp.tool
    async def stop_task(session_id: str, task_id: str) -> dict:
        """Cancel a running task."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        await session.interpreter.stop_task(task_id)
        return {"stopped": True, "task_id": task_id}

    return mcp


def _require_own_session(manager: SessionManager, session_id: str):
    uid = _require_user()
    session = manager.get_session(uid, session_id)
    if session is None:
        return {"error": f"unknown session: {session_id}"}
    return session


def _result_dict(result) -> dict:
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "execution_time_ms": result.execution_time_ms,
    }
