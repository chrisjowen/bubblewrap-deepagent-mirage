"""Exec is exposed via MCP only; placeholder REST prefix kept."""

from __future__ import annotations

from fastapi import APIRouter


def build_router() -> APIRouter:
    return APIRouter(prefix="/workspaces", tags=["exec"])
