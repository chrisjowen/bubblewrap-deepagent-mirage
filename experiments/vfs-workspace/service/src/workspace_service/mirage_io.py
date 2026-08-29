"""Thin async wrappers around mirage Workspace ops for the REST/MCP layers."""

from __future__ import annotations

import posixpath
import shlex
from datetime import datetime

from mirage import Workspace


def to_mirage_path(virtual_path: str, mount: str) -> str:
    vp = (virtual_path or "").strip()
    if not vp.startswith("/"):
        vp = "/" + vp
    vp = posixpath.normpath(vp)
    if vp in ("", ".", "/"):
        return mount
    return f"{mount}{vp}"


def to_virtual_path(mirage_path: str, mount: str) -> str:
    return mirage_path[len(mount):] if mirage_path.startswith(mount) else mirage_path


def is_dir(stat_obj) -> bool:
    t = getattr(stat_obj, "type", None)
    return str(t).endswith("DIRECTORY") or t == "directory"


def parse_mtime(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


class MirageIO:
    """Async: shell exec, cat/tee/rm, readdir/stat."""

    def __init__(self, workspace: Workspace, mount: str) -> None:
        self._ws = workspace
        self._mount = f"/{mount.strip('/')}"

    @property
    def mount(self) -> str:
        return self._mount

    def mount_path(self, virtual: str) -> str:
        return to_mirage_path(virtual, self._mount)

    def virtual_path(self, mirage: str) -> str:
        return to_virtual_path(mirage, self._mount)

    async def shell(self, cmd: str, *, stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
        result = await self._ws.execute(cmd, stdin=stdin)
        stdout = await result.materialize_stdout() if hasattr(result, "materialize_stdout") else getattr(result, "stdout", b"")
        stderr_raw = await result.stderr_str() if hasattr(result, "stderr_str") else getattr(result, "stderr", "") or ""
        if isinstance(stderr_raw, str):
            stderr_raw = stderr_raw.encode("utf-8")
        return (
            getattr(result, "exit_code", 0) or 0,
            stdout if isinstance(stdout, bytes) else str(stdout).encode(),
            stderr_raw,
        )

    async def cat(self, path: str) -> tuple[int, bytes, bytes]:
        return await self.shell(f"cat {shlex.quote(self.mount_path(path))}")

    async def tee(self, path: str, data: bytes) -> tuple[int, bytes, bytes]:
        mirage = self.mount_path(path)
        parent = mirage.rsplit("/", 1)[0] or self._mount
        await self.shell(f"mkdir -p {shlex.quote(parent)}")
        return await self.shell(f"tee {shlex.quote(mirage)} > /dev/null", stdin=data)

    async def rm(self, path: str) -> tuple[int, bytes, bytes]:
        return await self.shell(f"rm -rf {shlex.quote(self.mount_path(path))}")

    async def readdir(self, path: str = "/") -> list[str]:
        return await self._ws.readdir(self.mount_path(path))

    async def stat(self, path: str):
        return await self._ws.stat(self.mount_path(path))
