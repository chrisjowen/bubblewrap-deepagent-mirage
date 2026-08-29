from __future__ import annotations

import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from workspace_service.auth import make_current_user_dep
from workspace_service.config import load_config
from workspace_service.mcp.server import build_mcp
from workspace_service.rest.exec import build_router as build_exec_router
from workspace_service.rest.files import build_router as build_files_router
from workspace_service.rest.workspaces import build_router as build_workspaces_router
from workspace_service.session_ctx import current_user_id
from workspace_service.workspaces import SessionManager


def create_app() -> FastAPI:
    config_path = Path(os.environ.get("WORKSPACES_YAML", "./workspaces.yaml"))
    config = load_config(config_path)
    manager = SessionManager(config)
    current_user_dep = make_current_user_dep(config)

    mcp = build_mcp(manager)
    mcp_app = mcp.http_app(path="/")  # sub-app serves at its root; mounted below at /mcp

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
            yield
        await manager.close_all()

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
    async def _mcp_user_ctx(request, call_next):
        """For /mcp/* requests: validate X-User-Id, set contextvar."""
        if request.url.path.startswith("/mcp"):
            user = request.headers.get("x-user-id")
            if not user:
                return JSONResponse({"detail": "X-User-Id header required"}, status_code=401)
            if user not in config.users:
                return JSONResponse({"detail": "unknown user"}, status_code=403)
            token = current_user_id.set(user)
            try:
                return await call_next(request)
            finally:
                current_user_id.reset(token)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(build_workspaces_router(manager, current_user_dep))
    app.include_router(build_files_router(manager, current_user_dep))
    app.include_router(build_exec_router(manager, current_user_dep))

    app.mount("/mcp", mcp_app)

    app.state.manager = manager
    app.state.config = config
    return app


app = create_app() if os.environ.get("WORKSPACES_YAML") else None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
