"""Workspace lookup, ownership check, per-workspace Mirage IO cache.

Sits between config (declarative workspaces) and the runtime layer
(sessions + code interpreter). No knowledge of code_interpreter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mirage import MountMode, Workspace
from mirage.cache.file.config import CacheConfig
from mirage.cache.index.config import IndexConfig
from mirage.resource.s3 import S3Config, S3Resource
from mirage.runtime.python.local import LocalRuntime
from mirage.types import CacheType, IndexType

from workspace_service.config import WorkspaceSpec, WorkspacesConfig
from workspace_service.mirage_io import MirageIO

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    workspace_id: str
    owner: str
    label: str
    runtime: str
    mount_name: str


def _build_file_workspace(spec: WorkspaceSpec) -> Workspace:
    """Mirage workspace for file browse/read/write/delete/ls.

    Runtime list has a placeholder LocalRuntime — we never call
    workspace.execute() on this workspace. Code execution lives on
    the CodeInterpreter port instead.
    """
    resource = S3Resource(S3Config(
        bucket=spec.storage.bucket,
        region=spec.storage.region,
        key_prefix=spec.storage.prefix,
    ))
    mount_path = f"/{spec.mount_name.strip('/')}"
    return Workspace(
        {mount_path: resource},
        mode=MountMode.WRITE,
        cache=CacheConfig(type=CacheType.RAM, limit="512MB"),
        # TTL kept short: docker runtimes write via mount-s3 (bypasses
        # Mirage), so this cache would otherwise show stale listings
        # for up to 10 minutes. 10s balances freshness vs. S3 LIST cost.
        index=IndexConfig(type=IndexType.RAM, ttl=10),
        runtimes=[LocalRuntime()],
    )


class WorkspaceRegistry:
    """Workspace lookups + per-workspace MirageIO cache."""

    def __init__(self, config: WorkspacesConfig) -> None:
        self._config = config
        self._file_workspaces: dict[str, Workspace] = {}
        self._file_io: dict[str, MirageIO] = {}

    @property
    def config(self) -> WorkspacesConfig:
        return self._config

    def exists(self, workspace_id: str) -> bool:
        return workspace_id in self._config.workspaces

    def spec(self, workspace_id: str) -> WorkspaceSpec:
        return self._config.workspaces[workspace_id]

    def owner_of(self, workspace_id: str) -> str:
        return self._config.workspaces[workspace_id].owner

    def view(self, workspace_id: str) -> WorkspaceView:
        s = self.spec(workspace_id)
        return WorkspaceView(
            workspace_id=workspace_id,
            owner=s.owner,
            label=s.label,
            runtime=s.runtime,
            mount_name=s.mount_name,
        )

    def list_for_user(self, user_id: str) -> list[WorkspaceView]:
        return [
            self.view(wid) for wid, ws in self._config.workspaces.items()
            if ws.owner == user_id
        ]

    def file_io(self, workspace_id: str) -> MirageIO:
        if workspace_id not in self._file_io:
            spec = self.spec(workspace_id)
            ws = _build_file_workspace(spec)
            self._file_workspaces[workspace_id] = ws
            self._file_io[workspace_id] = MirageIO(ws, spec.mount_name)
        return self._file_io[workspace_id]

    def close_all(self) -> None:
        for ws in self._file_workspaces.values():
            try:
                ws.close()
            except Exception:
                log.exception("file workspace close failed")
        self._file_workspaces.clear()
        self._file_io.clear()

    def refresh(self, workspace_id: str) -> None:
        """Drop the cached MirageIO so the next call rebuilds it.

        Docker runtimes write to S3 via mount-s3 which bypasses Mirage's
        index cache — the cached listing goes stale until TTL expires.
        The UI refresh button hits this to force a clean re-list.
        """
        ws = self._file_workspaces.pop(workspace_id, None)
        self._file_io.pop(workspace_id, None)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                log.exception("refresh close failed for %s", workspace_id)
