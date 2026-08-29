from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from workspace_service.auth import make_current_user_dep
from workspace_service.config import load_config
from workspace_service.rest.exec import build_router as build_exec_router
from workspace_service.rest.files import build_router as build_files_router
from workspace_service.rest.workspaces import build_router as build_workspaces_router
from workspace_service.workspaces import WorkspaceManager


def create_app() -> FastAPI:
    config_path = Path(os.environ.get("WORKSPACES_YAML", "./workspaces.yaml"))
    config = load_config(config_path)
    manager = WorkspaceManager(config)
    current_user_dep = make_current_user_dep(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.close_all()

    app = FastAPI(title="vfs-workspace service", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(build_workspaces_router(manager, current_user_dep))
    app.include_router(build_files_router(manager, current_user_dep))
    app.include_router(build_exec_router(manager, current_user_dep))

    app.state.manager = manager
    app.state.config = config
    return app


app = create_app() if os.environ.get("WORKSPACES_YAML") else None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
