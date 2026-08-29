from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

from mirage import MountMode, Workspace
from mirage.cache.file.config import CacheConfig
from mirage.cache.index.config import IndexConfig
from mirage.resource.s3 import S3Config, S3Resource
from mirage.runtime.python.local import LocalRuntime
from mirage.types import CacheType, IndexType

from code_interpreter import CodeInterpreterSession, build as build_interpreter

from workspace_service.config import WorkspacesConfig
from workspace_service.mirage_io import MirageIO

log = logging.getLogger(__name__)


def _build_file_workspace(user_spec) -> Workspace:
    """Per-user Mirage workspace used for file browse/read/write/delete/ls.

    Runtime is a placeholder LocalRuntime — the service never calls
    workspace.execute() on this workspace (code/command execution lives
    on the CodeInterpreter abstraction, not the Mirage runtime layer).
    Mirage requires a runtime list, so LocalRuntime is the cheapest.
    """
    resource = S3Resource(S3Config(
        bucket=user_spec.s3_bucket,
        region=user_spec.s3_region,
        key_prefix=user_spec.s3_prefix,
    ))
    mount_path = f"/{user_spec.mount_name.strip('/')}"
    return Workspace(
        {mount_path: resource},
        mode=MountMode.WRITE,
        cache=CacheConfig(type=CacheType.RAM, limit="512MB"),
        index=IndexConfig(type=IndexType.RAM, ttl=600),
        runtimes=[LocalRuntime()],
    )


@dataclass
class Session:
    user_id: str
    session_id: str
    interpreter: CodeInterpreterSession
    last_touched: float = field(default_factory=time.monotonic)


class SessionManager:
    """Per-user Mirage workspace (file ops) + per-(user, session) CodeInterpreter."""

    def __init__(self, config: WorkspacesConfig) -> None:
        self._config = config
        self._sessions: dict[tuple[str, str], Session] = {}
        self._sessions_by_user: dict[str, set[str]] = {}
        self._file_workspaces: dict[str, Workspace] = {}
        self._file_io: dict[str, MirageIO] = {}

    @property
    def config(self) -> WorkspacesConfig:
        return self._config

    def _check_user(self, user_id: str) -> None:
        if user_id not in self._config.users:
            raise KeyError(user_id)

    # --- Mirage-backed file IO (session-less) ---

    def file_io(self, user_id: str) -> MirageIO:
        self._check_user(user_id)
        if user_id not in self._file_io:
            user_spec = self._config.users[user_id]
            ws = _build_file_workspace(user_spec)
            self._file_workspaces[user_id] = ws
            self._file_io[user_id] = MirageIO(ws, user_spec.mount_name)
        return self._file_io[user_id]

    # --- code interpreter sessions ---

    async def start_session(
        self, user_id: str, session_id: str | None = None
    ) -> Session:
        self._check_user(user_id)
        sid = session_id or uuid4().hex[:12]
        if (user_id, sid) in self._sessions:
            return self._sessions[(user_id, sid)]
        interpreter = build_interpreter(
            self._config.users[user_id],
            self._config.runtimes.get(self._config.users[user_id].runtime, {}),
        )
        await interpreter.start()
        session = Session(user_id=user_id, session_id=sid, interpreter=interpreter)
        self._sessions[(user_id, sid)] = session
        self._sessions_by_user.setdefault(user_id, set()).add(sid)
        return session

    async def stop_session(self, user_id: str, session_id: str) -> bool:
        key = (user_id, session_id)
        session = self._sessions.pop(key, None)
        self._sessions_by_user.get(user_id, set()).discard(session_id)
        if session is None:
            return False
        try:
            await session.interpreter.stop()
        except Exception:
            log.exception("stop_session failed for %s / %s", user_id, session_id)
        return True

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        session = self._sessions.get((user_id, session_id))
        if session is not None:
            session.last_touched = time.monotonic()
        return session

    def list_sessions(self, user_id: str) -> list[str]:
        self._check_user(user_id)
        return sorted(self._sessions_by_user.get(user_id, set()))

    async def close_all(self) -> None:
        for key in list(self._sessions):
            await self.stop_session(*key)
        for ws in self._file_workspaces.values():
            try:
                ws.close()
            except Exception:
                log.exception("file workspace close failed")
        self._file_workspaces.clear()
        self._file_io.clear()

    def runtime_for(self, user_id: str) -> str:
        return self._config.users[user_id].runtime

    async def close_idle_task(self, idle_seconds: float = 900, poll_seconds: float = 60) -> None:
        while True:
            await asyncio.sleep(poll_seconds)
            cutoff = time.monotonic() - idle_seconds
            for key, session in list(self._sessions.items()):
                if session.last_touched < cutoff:
                    log.info("closing idle session: %s / %s", *key)
                    await self.stop_session(*key)


WorkspaceManager = SessionManager  # back-compat alias
