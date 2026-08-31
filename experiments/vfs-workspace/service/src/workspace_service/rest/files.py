from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from workspace_service.mirage_io import is_dir
from workspace_service.workspace_registry import WorkspaceRegistry


def build_router(registry: WorkspaceRegistry, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["files"])

    def _own(workspace_id: str, user: str) -> None:
        if not registry.exists(workspace_id):
            raise HTTPException(status_code=404, detail="unknown workspace")
        if registry.owner_of(workspace_id) != user:
            raise HTTPException(status_code=403, detail="not your workspace")

    @router.get("/{workspace_id}/tree")
    async def tree(workspace_id: str, path: str = "/", refresh: bool = False,
                   user: str = Depends(current_user_dep)):
        _own(workspace_id, user)
        if refresh:
            registry.refresh(workspace_id)
        io = registry.file_io(workspace_id)
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
        _own(workspace_id, user)
        io = registry.file_io(workspace_id)
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
        _own(workspace_id, user)
        io = registry.file_io(workspace_id)
        body = await request.body()
        rc, _, err = await io.tee(file_path, body)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "write failed")
        registry.refresh(workspace_id)
        return Response(status_code=204)

    @router.delete("/{workspace_id}/files/{file_path:path}", status_code=204)
    async def delete(workspace_id: str, file_path: str,
                     user: str = Depends(current_user_dep)):
        _own(workspace_id, user)
        io = registry.file_io(workspace_id)
        rc, _, err = await io.rm(file_path)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "delete failed")
        registry.refresh(workspace_id)
        return Response(status_code=204)

    @router.post("/{workspace_id}/mkdir", status_code=204)
    async def mkdir(workspace_id: str, payload: dict = Body(...),
                    user: str = Depends(current_user_dep)):
        _own(workspace_id, user)
        path = (payload or {}).get("path")
        if not path:
            raise HTTPException(400, "path required")
        io = registry.file_io(workspace_id)
        rc, _, err = await io.mkdir(path)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "mkdir failed")
        registry.refresh(workspace_id)
        return Response(status_code=204)

    @router.post("/{workspace_id}/move", status_code=204)
    async def move(workspace_id: str, payload: dict = Body(...),
                   user: str = Depends(current_user_dep)):
        _own(workspace_id, user)
        src = (payload or {}).get("src")
        dst = (payload or {}).get("dst")
        if not src or not dst:
            raise HTTPException(400, "src and dst required")
        io = registry.file_io(workspace_id)
        rc, _, err = await io.mv(src, dst)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "move failed")
        registry.refresh(workspace_id)
        return Response(status_code=204)

    return router
