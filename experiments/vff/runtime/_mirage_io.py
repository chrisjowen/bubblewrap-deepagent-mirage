"""Byte-safe async I/O primitives around a mirage Workspace."""

from __future__ import annotations

import shlex

from mirage import Workspace

from runtime._mirage_util import parse_mtime, to_mirage_path, to_virtual_path


def _is_dir(stat) -> bool:
    t = getattr(stat, "type", None)
    return str(t).endswith("DIRECTORY") or t == "directory"


class MirageIO:
    """Async wrappers: shell exec, byte-safe cat/tee/rm, recursive walk."""

    def __init__(self, workspace: Workspace, mount: str) -> None:
        self._ws = workspace
        self._mount = mount

    def mount_path(self, virtual: str) -> str:
        return to_mirage_path(virtual, self._mount)

    def virtual_path(self, mirage: str) -> str:
        return to_virtual_path(mirage, self._mount)

    async def shell(self, cmd: str, *, stdin: bytes | None = None) -> tuple[int, bytes, str]:
        result = await self._ws.execute(cmd, stdin=stdin)
        stdout = await result.materialize_stdout()
        stderr = await result.stderr_str() if hasattr(result, "stderr_str") else ""
        return getattr(result, "exit_code", 0) or 0, stdout, stderr

    async def cat(self, mirage_path: str) -> tuple[int, bytes, str]:
        return await self.shell(f"cat {shlex.quote(mirage_path)}")

    async def tee(self, mirage_path: str, data: bytes) -> tuple[int, bytes, str]:
        parent = mirage_path.rsplit("/", 1)[0] or self._mount
        await self.shell(f"mkdir -p {shlex.quote(parent)}")
        return await self.shell(f"tee {shlex.quote(mirage_path)} > /dev/null", stdin=data)

    async def rm(self, mirage_path: str) -> tuple[int, bytes, str]:
        return await self.shell(f"rm -rf {shlex.quote(mirage_path)}")

    async def readdir(self, mirage_path: str) -> list[str]:
        return await self._ws.readdir(mirage_path)

    async def stat(self, mirage_path: str):
        return await self._ws.stat(mirage_path)

    async def walk(self, virtual_root: str = "/") -> dict[str, tuple[int, float | None]]:
        """Recursively enumerate files. Returns `rel_path → (size, mtime_epoch)`."""
        out: dict[str, tuple[int, float | None]] = {}
        stack = [virtual_root]
        while stack:
            current = stack.pop()
            try:
                entries = await self.readdir(self.mount_path(current))
            except Exception:  # noqa: BLE001
                continue
            for entry in entries:
                virtual = self.virtual_path(entry)
                try:
                    st = await self.stat(entry)
                except Exception:  # noqa: BLE001
                    continue
                if _is_dir(st):
                    stack.append(virtual)
                    continue
                rel = virtual.lstrip("/")
                out[rel] = (int(getattr(st, "size", 0) or 0), parse_mtime(getattr(st, "modified", None)))
        return out
