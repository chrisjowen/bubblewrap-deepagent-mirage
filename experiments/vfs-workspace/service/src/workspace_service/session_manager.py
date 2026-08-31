"""Per-workspace CodeInterpreter session lifecycle.

Sessions are keyed by (workspace_id, session_id). One workspace can
own many concurrent sessions. Runtime construction goes through the
`code_interpreter.registry` port — this module knows nothing about
docker or AWS.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

from code_interpreter import CodeInterpreterSession, StorageBinding, build as build_interpreter

from workspace_service.workspace_registry import WorkspaceRegistry

log = logging.getLogger(__name__)


@dataclass
class Session:
    workspace_id: str
    session_id: str
    interpreter: CodeInterpreterSession
    last_touched: float = field(default_factory=time.monotonic)


class SessionManager:
    """CodeInterpreter sessions keyed by (workspace_id, session_id)."""

    def __init__(self, registry: WorkspaceRegistry) -> None:
        self._registry = registry
        self._sessions: dict[tuple[str, str], Session] = {}
        self._by_workspace: dict[str, set[str]] = {}

    async def start_session(
        self, workspace_id: str, session_id: str | None = None
    ) -> Session:
        if not self._registry.exists(workspace_id):
            raise KeyError(workspace_id)
        sid = session_id or uuid4().hex[:12]
        key = (workspace_id, sid)
        if key in self._sessions:
            return self._sessions[key]

        spec = self._registry.spec(workspace_id)
        binding = StorageBinding(
            bucket=spec.storage.bucket,
            region=spec.storage.region,
            prefix=spec.storage.prefix,
            mount_name=spec.mount_name,
        )
        runtime_spec = self._registry.config.runtimes.get(spec.runtime, {})
        interpreter = build_interpreter(spec.runtime, binding, runtime_spec)
        await interpreter.start()

        session = Session(workspace_id=workspace_id, session_id=sid, interpreter=interpreter)
        self._sessions[key] = session
        self._by_workspace.setdefault(workspace_id, set()).add(sid)
        return session

    async def stop_session(self, workspace_id: str, session_id: str) -> bool:
        key = (workspace_id, session_id)
        session = self._sessions.pop(key, None)
        self._by_workspace.get(workspace_id, set()).discard(session_id)
        if session is None:
            return False
        try:
            await session.interpreter.stop()
        except Exception:
            log.exception("stop_session failed for %s / %s", workspace_id, session_id)
        return True

    def get_session(self, workspace_id: str, session_id: str) -> Session | None:
        session = self._sessions.get((workspace_id, session_id))
        if session is not None:
            session.last_touched = time.monotonic()
        return session

    def list_sessions(self, workspace_id: str) -> list[str]:
        return sorted(self._by_workspace.get(workspace_id, set()))

    async def close_all(self) -> None:
        for key in list(self._sessions):
            await self.stop_session(*key)
        self._registry.close_all()

    async def close_idle_task(
        self, idle_seconds: float = 900, poll_seconds: float = 60
    ) -> None:
        while True:
            await asyncio.sleep(poll_seconds)
            cutoff = time.monotonic() - idle_seconds
            for key, session in list(self._sessions.items()):
                if session.last_touched < cutoff:
                    log.info("closing idle session: %s / %s", *key)
                    await self.stop_session(*key)
