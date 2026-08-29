from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from workspace_service.mirage_io import is_dir
from workspace_service.workspaces import SessionManager


def build_router(manager: SessionManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["files"])

    @router.get("/{workspace_id}/tree")
    async def tree(workspace_id: str, path: str = "/",
                   user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        io = manager.file_io(user)
        try:
            entries = await io.readdir(path)
        except Exception as exc:
            raise HTTPException(500, f"readdir failed: {exc}")
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

    @router.get("/{workspace_id}/files/{file_path:path}")
    async def read(workspace_id: str, file_path: str,
                   user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        io = manager.file_io(user)
        rc, data, err = await io.cat(file_path)
        if rc != 0:
            raise HTTPException(404, err.decode(errors="replace") or "not found")
        try:
            return Response(content=data.decode("utf-8"),
                            media_type="text/plain; charset=utf-8")
        except UnicodeDecodeError:
            return Response(content=data, media_type="application/octet-stream")

    @router.put("/{workspace_id}/files/{file_path:path}", status_code=204)
    async def write(workspace_id: str, file_path: str, request: Request,
                    user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        io = manager.file_io(user)
        body = await request.body()
        rc, _, err = await io.tee(file_path, body)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "write failed")
        return Response(status_code=204)

    @router.delete("/{workspace_id}/files/{file_path:path}", status_code=204)
    async def delete(workspace_id: str, file_path: str,
                     user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        io = manager.file_io(user)
        rc, _, err = await io.rm(file_path)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "delete failed")
        return Response(status_code=204)

    return router
