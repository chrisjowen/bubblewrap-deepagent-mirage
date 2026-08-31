"""Config schema: users (auth membership), workspaces, runtimes.

A `Workspace` is the addressable unit end-users pick from the UI.
It couples a storage backend (S3 folder) with a runtime choice
(docker-local | code-interpreter | any future adapter).

Users own workspaces; ownership is checked at REST/MCP boundaries.
Runtime names are OPEN — no Literal — because adapters self-register
in `code_interpreter.registry`; the loader only validates that the
referenced runtime name has a block under `runtimes:`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class UserSpec(BaseModel):
    """Auth membership record. Presence in `users:` = allowed X-User-Id."""

    label: str | None = None


class StorageSpec(BaseModel):
    """S3 folder that backs a workspace's filesystem."""

    bucket: str
    region: str
    prefix: str


class WorkspaceSpec(BaseModel):
    """One selectable workspace in the UI."""

    owner: str
    label: str
    runtime: str  # must match a key under `runtimes:`
    storage: StorageSpec
    mount_name: str = "disk"


class WorkspacesConfig(BaseModel):
    users: dict[str, UserSpec]
    workspaces: dict[str, WorkspaceSpec] = Field(default_factory=dict)
    runtimes: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_refs(self) -> "WorkspacesConfig":
        for ws_id, ws in self.workspaces.items():
            if ws.owner not in self.users:
                raise ValueError(
                    f"workspace {ws_id!r}: owner {ws.owner!r} not in users"
                )
            if ws.runtime not in self.runtimes:
                raise ValueError(
                    f"workspace {ws_id!r}: runtime {ws.runtime!r} not in runtimes"
                )
        return self

    def workspaces_for(self, user_id: str) -> list[tuple[str, WorkspaceSpec]]:
        return [
            (wid, ws) for wid, ws in self.workspaces.items() if ws.owner == user_id
        ]


def load_config(path: Path) -> WorkspacesConfig:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return WorkspacesConfig.model_validate(data)
