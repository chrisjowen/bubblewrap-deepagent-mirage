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
        manager.get_or_open(user)
        return {"status": "open", "runtime": manager.runtime_for(user)}

    @router.post("/{workspace_id}/close")
    def close_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(status_code=403, detail="not your workspace")
        manager.close(user)
        return {"status": "closed"}

    return router
