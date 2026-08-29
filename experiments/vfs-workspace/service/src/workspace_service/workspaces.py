from __future__ import annotations

import asyncio
import logging
import time

from mirage import MountMode, Workspace
from mirage.cache.file.config import CacheConfig
from mirage.cache.index.config import IndexConfig
from mirage.resource.s3 import S3Config, S3Resource
from mirage.types import CacheType, IndexType

from workspace_service.config import UserSpec, WorkspacesConfig

log = logging.getLogger(__name__)


def _build_runtime(name: str, user: UserSpec, runtime_spec: dict):
    if name == "docker-local":
        from mirage_runtimes.docker_local import DockerLocalConfig, MountLocalPython
        cfg = DockerLocalConfig(
            s3_bucket=user.s3_bucket,
            s3_prefix=user.s3_prefix,
            image=runtime_spec.get("image", "mirage-runtime:latest"),
            aws_env_forwarding=runtime_spec.get("aws_env_forwarding", True),
        )
        return MountLocalPython(config=cfg)
    if name == "code-interpreter":
        from mirage_runtimes.code_interpreter import (
            CodeInterpreterConfig,
            CodeInterpreterPython,
        )
        cfg = CodeInterpreterConfig(
            region=runtime_spec.get("region", user.s3_region),
            code_interpreter_identifier=runtime_spec["code_interpreter_identifier"],
            session_timeout_seconds=runtime_spec.get("session_timeout_seconds", 900),
        )
        return CodeInterpreterPython(config=cfg)
    raise ValueError(f"unknown runtime: {name}")


def _build_workspace(user: UserSpec, runtime_specs: dict) -> Workspace:
    resource = S3Resource(S3Config(
        bucket=user.s3_bucket,
        region=user.s3_region,
        key_prefix=user.s3_prefix,
    ))
    runtime = _build_runtime(user.runtime, user, runtime_specs.get(user.runtime, {}))
    mount_path = f"/{user.mount_name.strip('/')}"
    return Workspace(
        {mount_path: resource},
        mode=MountMode.WRITE,
        cache=CacheConfig(type=CacheType.RAM, limit="512MB"),
        index=IndexConfig(type=IndexType.RAM, ttl=600),
        runtimes=[runtime],
    )


class WorkspaceManager:
    """Per-user Mirage Workspace cache. One workspace per user_id for Phase 0."""

    def __init__(self, config: WorkspacesConfig) -> None:
        self._config = config
        self._workspaces: dict[str, Workspace] = {}
        self._last_touched: dict[str, float] = {}

    @property
    def config(self) -> WorkspacesConfig:
        return self._config

    def get_or_open(self, user_id: str) -> Workspace:
        if user_id not in self._config.users:
            raise KeyError(user_id)
        ws = self._workspaces.get(user_id)
        if ws is None:
            ws = _build_workspace(
                self._config.users[user_id],
                self._config.runtimes,
            )
            self._workspaces[user_id] = ws
        self._last_touched[user_id] = time.monotonic()
        return ws

    def open(self, user_id: str) -> Workspace:
        return self.get_or_open(user_id)

    def close(self, user_id: str) -> None:
        ws = self._workspaces.pop(user_id, None)
        self._last_touched.pop(user_id, None)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                log.exception("workspace close failed for %s", user_id)

    def close_all(self) -> None:
        for user_id in list(self._workspaces):
            self.close(user_id)

    def runtime_for(self, user_id: str) -> str:
        return self._config.users[user_id].runtime

    def mount_name_for(self, user_id: str) -> str:
        return self._config.users[user_id].mount_name

    async def close_idle_task(self, idle_seconds: float = 900, poll_seconds: float = 60) -> None:
        while True:
            await asyncio.sleep(poll_seconds)
            cutoff = time.monotonic() - idle_seconds
            for user_id, last in list(self._last_touched.items()):
                if last < cutoff:
                    log.info("closing idle workspace: %s", user_id)
                    self.close(user_id)
