from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from workspace_service.session_manager import SessionManager
from workspace_service.workspace_registry import WorkspaceRegistry


def build_router(
    registry: WorkspaceRegistry,
    manager: SessionManager,
    current_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["workspaces"])

    def _own(workspace_id: str, user: str) -> None:
        if not registry.exists(workspace_id):
            raise HTTPException(status_code=404, detail="unknown workspace")
        if registry.owner_of(workspace_id) != user:
            raise HTTPException(status_code=403, detail="not your workspace")

    @router.get("")
    def list_workspaces(user: str = Depends(current_user_dep)):
        return [
            {
                "id": v.workspace_id,
                "label": v.label,
                "runtime": v.runtime,
                "mount_name": v.mount_name,
            }
            for v in registry.list_for_user(user)
        ]

    @router.post("/{workspace_id}/open")
    def open_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        _own(workspace_id, user)
        v = registry.view(workspace_id)
        return {
            "status": "open",
            "id": v.workspace_id,
            "label": v.label,
            "runtime": v.runtime,
            "mount_name": v.mount_name,
        }

    @router.post("/{workspace_id}/close")
    async def close_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        _own(workspace_id, user)
        for sid in list(manager.list_sessions(workspace_id)):
            await manager.stop_session(workspace_id, sid)
        return {"status": "closed"}

    return router
