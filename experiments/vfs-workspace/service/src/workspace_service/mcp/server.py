"""Single global FastMCP at /mcp.

Two tool families:
- File IO — routed through Mirage; scoped by workspace_id (session-less).
- Session lifecycle + code/command execution — routed through the
  CodeInterpreter port; sessions belong to a workspace.

Ownership is verified against the caller's X-User-Id (populated by the
/mcp auth middleware in main.py). A workspace_id argument is required
on every tool.
"""

from __future__ import annotations

import base64
from typing import Literal

from fastapi import HTTPException
from fastmcp import FastMCP

from workspace_service.mirage_io import is_dir
from workspace_service.session_ctx import current_user_id
from workspace_service.session_manager import SessionManager
from workspace_service.workspace_registry import WorkspaceRegistry


def _require_user() -> str:
    uid = current_user_id.get()
    if not uid:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return uid


def build_mcp(registry: WorkspaceRegistry, manager: SessionManager) -> FastMCP:
    mcp = FastMCP("vfs-workspace")

    def _own_workspace(workspace_id: str) -> dict | None:
        uid = _require_user()
        if not registry.exists(workspace_id):
            return {"error": f"unknown workspace: {workspace_id}"}
        if registry.owner_of(workspace_id) != uid:
            return {"error": "not your workspace"}
        return None

    def _own_session(workspace_id: str, session_id: str):
        err = _own_workspace(workspace_id)
        if err:
            return err
        session = manager.get_session(workspace_id, session_id)
        if session is None:
            return {"error": f"unknown session: {session_id}"}
        return session

    # --- workspace discovery ---

    @mcp.tool
    def list_workspaces() -> dict:
        """List workspaces owned by the caller."""
        uid = _require_user()
        return {
            "workspaces": [
                {"id": v.workspace_id, "label": v.label, "runtime": v.runtime,
                 "mount_name": v.mount_name}
                for v in registry.list_for_user(uid)
            ]
        }

    # --- Mirage-backed file IO ---

    @mcp.tool
    async def read(workspace_id: str, file_path: str) -> dict:
        """Read a file from the given workspace."""
        err = _own_workspace(workspace_id)
        if err:
            return err
        io = registry.file_io(workspace_id)
        rc, data, err_bytes = await io.cat(file_path)
        if rc != 0:
            return {"error": err_bytes.decode(errors="replace") or "read failed"}
        try:
            return {"content": data.decode("utf-8")}
        except UnicodeDecodeError:
            return {"content_b64": base64.b64encode(data).decode()}

    @mcp.tool
    async def write(workspace_id: str, file_path: str, content: str) -> dict:
        """Write a file to the given workspace."""
        err = _own_workspace(workspace_id)
        if err:
            return err
        io = registry.file_io(workspace_id)
        rc, _, err_bytes = await io.tee(file_path, content.encode("utf-8"))
        if rc != 0:
            return {"error": err_bytes.decode(errors="replace") or "write failed"}
        registry.refresh(workspace_id)
        return {"path": file_path}

    @mcp.tool
    async def delete(workspace_id: str, file_path: str) -> dict:
        """Delete a file from the given workspace."""
        err = _own_workspace(workspace_id)
        if err:
            return err
        io = registry.file_io(workspace_id)
        rc, _, err_bytes = await io.rm(file_path)
        if rc != 0:
            return {"error": err_bytes.decode(errors="replace") or "delete failed"}
        registry.refresh(workspace_id)
        return {"path": file_path}

    @mcp.tool
    async def ls(workspace_id: str, path: str = "/") -> dict:
        """List entries in the workspace at path."""
        err = _own_workspace(workspace_id)
        if err:
            return err
        io = registry.file_io(workspace_id)
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
    async def start_session(workspace_id: str) -> dict:
        """Start a new code interpreter session bound to a workspace."""
        err = _own_workspace(workspace_id)
        if err:
            return err
        try:
            session = await manager.start_session(workspace_id)
        except Exception as exc:
            return {"error": f"start_session failed: {exc}"}
        return {
            "workspace_id": workspace_id,
            "session_id": session.session_id,
            "runtime": session.interpreter.runtime,
        }

    @mcp.tool
    async def stop_session(workspace_id: str, session_id: str) -> dict:
        """Stop a session belonging to one of the caller's workspaces."""
        result = _own_session(workspace_id, session_id)
        if isinstance(result, dict):
            return result
        await manager.stop_session(workspace_id, session_id)
        return {"stopped": True, "session_id": session_id}

    @mcp.tool
    def list_sessions(workspace_id: str) -> dict:
        """List active session ids for a workspace."""
        err = _own_workspace(workspace_id)
        if err:
            return err
        return {"session_ids": manager.list_sessions(workspace_id)}

    # --- code / command execution ---

    @mcp.tool
    async def execute_code(
        workspace_id: str,
        session_id: str,
        code: str,
        language: Literal["python", "node", "bash"] = "python",
        clear_context: bool = False,
    ) -> dict:
        """Run inline code in the session's interpreter."""
        session = _own_session(workspace_id, session_id)
        if isinstance(session, dict):
            return session
        result = await session.interpreter.execute_code(code, language, clear_context)
        registry.refresh(workspace_id)
        return _result_dict(result)

    @mcp.tool
    async def execute_command(
        workspace_id: str, session_id: str, command: str
    ) -> dict:
        """Run a shell command in the session."""
        session = _own_session(workspace_id, session_id)
        if isinstance(session, dict):
            return session
        result = await session.interpreter.execute_command(command)
        registry.refresh(workspace_id)
        return _result_dict(result)

    @mcp.tool
    async def start_command_execution(
        workspace_id: str, session_id: str, command: str
    ) -> dict:
        """Start a long-running command; returns a task_id."""
        session = _own_session(workspace_id, session_id)
        if isinstance(session, dict):
            return session
        try:
            task_id = await session.interpreter.start_command_execution(command)
        except Exception as exc:
            return {"error": f"start_command_execution failed: {exc}"}
        return {"task_id": task_id}

    @mcp.tool
    async def get_task(
        workspace_id: str, session_id: str, task_id: str
    ) -> dict:
        """One-shot status peek of a running task."""
        session = _own_session(workspace_id, session_id)
        if isinstance(session, dict):
            return session
        task = await session.interpreter.get_task(task_id)
        return _task_dict(task)

    @mcp.tool
    async def stop_task(
        workspace_id: str, session_id: str, task_id: str
    ) -> dict:
        """Cancel a running task."""
        session = _own_session(workspace_id, session_id)
        if isinstance(session, dict):
            return session
        await session.interpreter.stop_task(task_id)
        return {"stopped": True, "task_id": task_id}

    @mcp.tool
    async def wait_task(
        workspace_id: str,
        session_id: str,
        task_id: str,
        timeout_s: float = 60.0,
    ) -> dict:
        """Block until task finishes or timeout_s elapses.

        Prefer this over looping get_task — repeated get_task calls burn
        per-session InvokeCodeInterpreter connection quota on AgentCore.
        """
        session = _own_session(workspace_id, session_id)
        if isinstance(session, dict):
            return session
        try:
            task = await session.interpreter.wait_task(task_id, timeout_s=timeout_s)
        except Exception as exc:
            return {"error": f"wait_task failed: {exc}"}
        if task.status in ("succeeded", "failed", "cancelled"):
            registry.refresh(workspace_id)
        return _task_dict(task)

    return mcp


def _result_dict(result) -> dict:
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "execution_time_ms": result.execution_time_ms,
    }


def _task_dict(task) -> dict:
    return {
        "task_id": task.task_id,
        "status": task.status,
        "stdout": task.stdout,
        "stderr": task.stderr,
        "exit_code": task.exit_code,
        "execution_time_ms": task.execution_time_ms,
    }
