"""Single global FastMCP at /mcp.

Two families of tools:
- File IO (session-less) — routed through Mirage. read/write/delete/ls.
- Session lifecycle + code/command execution — routed through the
  CodeInterpreter abstraction (docker-local or aws code-interpreter).
  Session tools verify caller ownership.

Caller is resolved from X-User-Id via contextvar populated by the /mcp
auth middleware in main.py.
"""

from __future__ import annotations

import base64
from typing import Literal

from fastapi import HTTPException
from fastmcp import FastMCP

from workspace_service.mirage_io import is_dir
from workspace_service.session_ctx import current_user_id
from workspace_service.workspaces import SessionManager


def _require_user() -> str:
    uid = current_user_id.get()
    if not uid:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return uid


def build_mcp(manager: SessionManager) -> FastMCP:
    mcp = FastMCP("vfs-workspace")

    # --- Mirage-backed file IO (no session) ---

    @mcp.tool
    async def read(file_path: str) -> dict:
        """Read a file from the caller's Mirage workspace."""
        io = manager.file_io(_require_user())
        rc, data, err = await io.cat(file_path)
        if rc != 0:
            return {"error": err.decode(errors="replace") or "read failed"}
        try:
            return {"content": data.decode("utf-8")}
        except UnicodeDecodeError:
            return {"content_b64": base64.b64encode(data).decode()}

    @mcp.tool
    async def write(file_path: str, content: str) -> dict:
        """Write a file to the caller's Mirage workspace."""
        io = manager.file_io(_require_user())
        rc, _, err = await io.tee(file_path, content.encode("utf-8"))
        if rc != 0:
            return {"error": err.decode(errors="replace") or "write failed"}
        return {"path": file_path}

    @mcp.tool
    async def delete(file_path: str) -> dict:
        """Delete a file from the caller's Mirage workspace."""
        io = manager.file_io(_require_user())
        rc, _, err = await io.rm(file_path)
        if rc != 0:
            return {"error": err.decode(errors="replace") or "delete failed"}
        return {"path": file_path}

    @mcp.tool
    async def ls(path: str = "/") -> dict:
        """List directory entries in the caller's Mirage workspace."""
        io = manager.file_io(_require_user())
        try:
            entries = await io.readdir(path)
        except Exception as exc:
            return {"error": str(exc)}
        out = []
        for mp in entries:
            virtual = io.virtual_path(mp) or "/"
            try:
                st = await io.stat(virtual)
            except Exception:
                st = None
            out.append({
                "path": virtual,
                "is_dir": is_dir(st) if st else virtual.endswith("/"),
                "size": getattr(st, "size", None) if st else None,
            })
        return {"entries": out}

    # --- session lifecycle ---

    @mcp.tool
    async def start_session() -> dict:
        """Start a new code interpreter session for the caller."""
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

    # --- code / command execution (session-scoped, ownership-checked) ---

    @mcp.tool
    async def execute_code(
        session_id: str,
        code: str,
        language: Literal["python", "node", "bash"] = "python",
        clear_context: bool = False,
    ) -> dict:
        """Run inline code in the session's interpreter (AWS: executeCode)."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        return _result_dict(
            await session.interpreter.execute_code(code, language, clear_context)
        )

    @mcp.tool
    async def execute_command(session_id: str, command: str) -> dict:
        """Run a shell command in the session (AWS: executeCommand)."""
        session = _require_own_session(manager, session_id)
        if isinstance(session, dict):
            return session
        return _result_dict(await session.interpreter.execute_command(command))

    @mcp.tool
    async def start_command_execution(session_id: str, command: str) -> dict:
        """Start a long-running command; returns a task_id (AWS: startCommandExecution)."""
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
        """Fetch status + captured output of a task (AWS: getTask)."""
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
        """Cancel a running task (AWS: stopTask)."""
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
