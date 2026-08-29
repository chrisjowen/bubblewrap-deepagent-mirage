from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from workspace_service.workspaces import WorkspaceManager


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["workspaces"])

    @router.get("")
    def list_workspaces(user: str = Depends(current_user_dep)):
        return [{"id": user, "runtime": manager.runtime_for(user)}]

    @router.post("/{workspace_id}/open")
    def open_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(status_code=403, detail="not your workspace")
        # No-op: sessions are managed via MCP start_session; opening the
        # workspace itself just confirms the user + runtime.
        return {"status": "open", "runtime": manager.runtime_for(user)}

    @router.post("/{workspace_id}/close")
    def close_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(status_code=403, detail="not your workspace")
        for sid in list(manager.list_sessions(user)):
            manager.stop_session(user, sid)
        return {"status": "closed"}

    return router
