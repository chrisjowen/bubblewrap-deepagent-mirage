from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workspace_service.auth import make_current_user_dep
from workspace_service.config import load_config
from workspace_service.mcp.server import mount_mcp_apps
from workspace_service.rest.exec import build_router as build_exec_router
from workspace_service.rest.files import build_router as build_files_router
from workspace_service.rest.workspaces import build_router as build_workspaces_router
from workspace_service.workspaces import WorkspaceManager


def create_app() -> FastAPI:
    config_path = Path(os.environ.get("WORKSPACES_YAML", "./workspaces.yaml"))
    config = load_config(config_path)
    manager = WorkspaceManager(config)
    current_user_dep = make_current_user_dep(config)

    # Pre-build MCP sub-apps to collect their lifespans; mounted below.
    from fastmcp import FastMCP
    from workspace_service.mcp.server import _build_mcp_for

    mcp_apps: list[tuple[str, FastMCP, object]] = []
    for user_id in config.users:
        mcp = _build_mcp_for(manager, user_id)
        sub_app = mcp.http_app()
        mcp_apps.append((user_id, mcp, sub_app))

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        # Enter each MCP sub-app's lifespan so FastMCP's task groups start.
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            for _uid, _mcp, sub_app in mcp_apps:
                await stack.enter_async_context(sub_app.router.lifespan_context(sub_app))
            yield
        manager.close_all()

    app = FastAPI(title="vfs-workspace service", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5273,http://127.0.0.1:5273,http://localhost:5173,http://127.0.0.1:5173",
        ).split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _mcp_auth(request, call_next):
        path = request.url.path
        prefix = "/mcp/workspaces/"
        if path.startswith(prefix):
            rest = path[len(prefix):]
            wanted = rest.split("/", 1)[0]
            header_user = request.headers.get("x-user-id")
            if not header_user:
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "X-User-Id header required"}, status_code=401)
            if header_user != wanted or header_user not in config.users:
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "not your workspace"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(build_workspaces_router(manager, current_user_dep))
    app.include_router(build_files_router(manager, current_user_dep))
    app.include_router(build_exec_router(manager, current_user_dep))

    for user_id, _mcp, sub_app in mcp_apps:
        app.mount(f"/mcp/workspaces/{user_id}", sub_app)

    app.state.manager = manager
    app.state.config = config
    return app


app = create_app() if os.environ.get("WORKSPACES_YAML") else None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
