from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

from code_interpreter import CodeInterpreterSession, build as build_session

from workspace_service.config import WorkspacesConfig
from workspace_service.s3io import S3IO

log = logging.getLogger(__name__)


@dataclass
class Session:
    user_id: str
    session_id: str
    interpreter: CodeInterpreterSession
    last_touched: float = field(default_factory=time.monotonic)


class SessionManager:
    """Per-user S3IO + per-(user, session_id) CodeInterpreter sessions."""

    def __init__(self, config: WorkspacesConfig) -> None:
        self._config = config
        self._sessions: dict[tuple[str, str], Session] = {}
        self._sessions_by_user: dict[str, set[str]] = {}
        self._s3io: dict[str, S3IO] = {}

    @property
    def config(self) -> WorkspacesConfig:
        return self._config

    def _check_user(self, user_id: str) -> None:
        if user_id not in self._config.users:
            raise KeyError(user_id)

    def s3io(self, user_id: str) -> S3IO:
        self._check_user(user_id)
        if user_id not in self._s3io:
            u = self._config.users[user_id]
            self._s3io[user_id] = S3IO(u.s3_bucket, u.s3_region, u.s3_prefix)
        return self._s3io[user_id]

    async def start_session(
        self, user_id: str, session_id: str | None = None
    ) -> Session:
        self._check_user(user_id)
        sid = session_id or uuid4().hex[:12]
        if (user_id, sid) in self._sessions:
            return self._sessions[(user_id, sid)]
        interpreter = build_session(
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


# Backward-compat alias for imports still using the old name.
WorkspaceManager = SessionManager
