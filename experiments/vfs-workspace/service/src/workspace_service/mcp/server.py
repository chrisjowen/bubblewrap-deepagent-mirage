"""Per-workspace HTTP MCP endpoints.

For each configured user, build a FastMCP sub-app at startup and mount
it at `/mcp/workspaces/{user_id}` (final URL for MCP JSON-RPC POSTs is
`/mcp/workspaces/{user_id}/mcp`, since FastMCP's http_app owns `/mcp`).

Auth: middleware checks the URL user_id against X-User-Id header.
"""

from __future__ import annotations

import shlex
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastmcp import FastMCP

from workspace_service.mirage_io import MirageIO
from workspace_service.workspaces import WorkspaceManager


def _build_mcp_for(manager: WorkspaceManager, user_id: str) -> FastMCP:
    """Build a FastMCP with tools bound to this user's workspace."""

    def _io() -> MirageIO:
        ws = manager.get_or_open(user_id)
        return MirageIO(ws, manager.mount_name_for(user_id))

    mcp = FastMCP(f"vfs-workspace-{user_id}")

    @mcp.tool
    async def read(file_path: str) -> dict:
        """Read a file from the workspace."""
        io = _io()
        rc, data, err = await io.cat(file_path)
        if rc != 0:
            return {"error": err.decode(errors="replace") or "read failed"}
        try:
            return {"content": data.decode("utf-8")}
        except UnicodeDecodeError:
            import base64
            return {"content_b64": base64.b64encode(data).decode()}

    @mcp.tool
    async def write(file_path: str, content: str) -> dict:
        """Write a file to the workspace."""
        io = _io()
        rc, _, err = await io.tee(file_path, content.encode("utf-8"))
        if rc != 0:
            return {"error": err.decode(errors="replace") or "write failed"}
        return {"path": file_path}

    @mcp.tool
    async def delete(file_path: str) -> dict:
        """Delete a file from the workspace."""
        io = _io()
        rc, _, err = await io.rm(file_path)
        if rc != 0:
            return {"error": err.decode(errors="replace") or "delete failed"}
        return {"path": file_path}

    @mcp.tool
    async def ls(path: str = "/") -> dict:
        """List directory entries."""
        io = _io()
        try:
            entries = await io.readdir(path)
        except Exception as exc:
            return {"error": str(exc)}
        return {"entries": [io.virtual_path(e) or "/" for e in entries]}

    @mcp.tool
    async def execute(language: str, code: str) -> dict:
        """Execute Python or Node code against the workspace runtime."""
        interpreter = {"python": "python3", "node": "node"}.get(language)
        if interpreter is None:
            return {"error": f"unsupported language: {language}"}
        ws = manager.get_or_open(user_id)
        cmd = f"{interpreter} -c {shlex.quote(code)}"
        try:
            result = await ws.execute(cmd)
        except Exception as exc:
            return {"error": f"execute failed: {exc}"}
        stdout = await result.materialize_stdout() if hasattr(result, "materialize_stdout") else getattr(result, "stdout", b"")
        stderr = await result.stderr_str() if hasattr(result, "stderr_str") else (getattr(result, "stderr", "") or "")
        return {
            "stdout": stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout),
            "stderr": stderr if isinstance(stderr, str) else (stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else ""),
            "exit_code": int(getattr(result, "exit_code", 0) or 0),
        }

    return mcp


def _auth_middleware(user_id: str) -> Callable:
    async def _mw(request: Request, call_next):
        header_user = request.headers.get("x-user-id") or request.headers.get("X-User-Id")
        if not header_user:
            raise HTTPException(status_code=401, detail="X-User-Id header required")
        if header_user != user_id:
            raise HTTPException(status_code=403, detail="not your workspace")
        return await call_next(request)
    return _mw


def mount_mcp_apps(app: FastAPI, manager: WorkspaceManager) -> list:
    """Build one FastMCP per user, mount each. Return the list of built MCPs.

    Caller must merge each MCP's http_app().lifespan into the parent lifespan.
    """
    built = []
    for user_id in manager.config.users:
        mcp = _build_mcp_for(manager, user_id)
        sub_app = mcp.http_app()  # ASGI app with /mcp route + lifespan
        app.mount(f"/mcp/workspaces/{user_id}", sub_app)
        built.append((user_id, mcp, sub_app))
    return built
