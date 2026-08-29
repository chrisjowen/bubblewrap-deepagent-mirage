"""Exec is available via MCP only (session-scoped).

Kept as an empty router for backward compat with main.py's include_router
call; can be removed once main.py drops it.
"""

from __future__ import annotations

from fastapi import APIRouter

from workspace_service.workspaces import WorkspaceManager


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:  # noqa: ARG001
    return APIRouter(prefix="/workspaces", tags=["exec"])
