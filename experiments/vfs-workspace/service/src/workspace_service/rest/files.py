from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from workspace_service.workspaces import WorkspaceManager


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["files"])

    @router.get("/{workspace_id}/tree")
    def tree(workspace_id: str, path: str = "/",
             user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        io = manager.s3io(user)
        entries = [
            {"path": e.path, "is_dir": e.is_dir, "size": e.size}
            for e in io.ls(path)
        ]
        return {"entries": entries}

    @router.get("/{workspace_id}/files/{file_path:path}")
    def read(workspace_id: str, file_path: str,
             user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        data, err = manager.s3io(user).read(file_path)
        if err is not None:
            raise HTTPException(404, err)
        try:
            text = data.decode("utf-8")
            return Response(content=text, media_type="text/plain; charset=utf-8")
        except UnicodeDecodeError:
            return Response(content=data, media_type="application/octet-stream")

    @router.put("/{workspace_id}/files/{file_path:path}", status_code=204)
    async def write(workspace_id: str, file_path: str, request: Request,
                    user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        body = await request.body()
        err = manager.s3io(user).write(file_path, body)
        if err is not None:
            raise HTTPException(500, err)
        return Response(status_code=204)

    @router.delete("/{workspace_id}/files/{file_path:path}", status_code=204)
    def delete(workspace_id: str, file_path: str,
               user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        err = manager.s3io(user).delete(file_path)
        if err is not None:
            raise HTTPException(500, err)
        return Response(status_code=204)

    return router
