"""Mirage-backed `BackendProtocol` + auto-syncing bwrap sandbox variant."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Iterator

from deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    ExecuteResponse,
    FileInfo,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)
from mirage import MountMode, Workspace
from mirage.cache.file.config import CacheConfig
from mirage.cache.index.config import IndexConfig
from mirage.resource.base import BaseResource
from mirage.types import CacheType, IndexType

from runtime._mirage_io import MirageIO, _is_dir
from runtime._mirage_sync import pull, push
from runtime._mirage_util import AsyncLoop, decode_content, slice_lines


class MirageBackend(BackendProtocol):
    """`BackendProtocol` routed through a mirage Workspace."""

    def __init__(
        self,
        resource: BaseResource,
        *,
        mount_name: str = "disk",
        name: str = "mirage",
        cache_limit: str = "512MB",
        index_ttl: float = 600,
    ) -> None:
        self._mount = f"/{mount_name.strip('/')}"
        self._name = name
        self._loop = AsyncLoop(name=f"{name}-loop")
        self._ws = self._loop.submit(self._build_ws(resource, cache_limit, index_ttl))
        self._io = MirageIO(self._ws, self._mount)

    async def _build_ws(self, resource: BaseResource, cache_limit: str, index_ttl: float) -> Workspace:
        return Workspace(
            {self._mount: resource},
            mode=MountMode.WRITE,
            cache=CacheConfig(type=CacheType.RAM, limit=cache_limit),
            index=IndexConfig(type=IndexType.RAM, ttl=index_ttl),
        )

    def close(self) -> None:
        try:
            self._loop.submit(self._ws.close())
        finally:
            self._loop.close()

    def ls(self, path: str) -> LsResult:
        try:
            entries = self._loop.submit(self._io.readdir(self._io.mount_path(path)))
        except Exception as exc:  # noqa: BLE001
            return LsResult(error=f"Path '{path}': {exc}")
        base = path.rstrip("/")
        return LsResult(entries=[self._entry_info(entry, base) for entry in entries])

    def _entry_info(self, mirage_path: str, virtual_base: str) -> FileInfo:
        name = mirage_path.rsplit("/", 1)[-1]
        display = f"{virtual_base}/{name}"
        try:
            st = self._loop.submit(self._io.stat(mirage_path))
        except Exception:  # noqa: BLE001
            return FileInfo(path=display, is_dir=False, size=None, modified_at=None)
        is_dir = _is_dir(st)
        return FileInfo(
            path=display + ("/" if is_dir else ""),
            is_dir=is_dir,
            size=getattr(st, "size", None),
            modified_at=getattr(st, "modified", None),
        )

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            rc, data, err = self._loop.submit(self._io.cat(self._io.mount_path(file_path)))
        except Exception as exc:  # noqa: BLE001
            return ReadResult(error=f"Read '{file_path}': {exc}")
        if rc != 0:
            return ReadResult(error=f"Read '{file_path}': {err.strip() or 'exit ' + str(rc)}")
        file_data, text = decode_content(data)
        if text is None:
            return ReadResult(file_data=file_data)
        return slice_lines(text, offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            rc, _, err = self._loop.submit(self._io.tee(self._io.mount_path(file_path), content.encode("utf-8")))
        except Exception as exc:  # noqa: BLE001
            return WriteResult(error=f"Write '{file_path}': {exc}")
        if rc != 0:
            return WriteResult(error=f"Write '{file_path}': {err.strip() or 'exit ' + str(rc)}")
        return WriteResult(path=file_path)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        current = self.read(file_path, offset=0, limit=10**9)
        if current.error or current.file_data is None:
            return EditResult(error=current.error or f"Edit '{file_path}': file not readable")
        content = current.file_data["content"]
        n = content.count(old_string)
        if n == 0:
            return EditResult(error=f"Edit '{file_path}': old_string not found")
        if n > 1 and not replace_all:
            return EditResult(error=f"Edit '{file_path}': old_string not unique ({n} matches)")
        count = -1 if replace_all else 1
        write_result = self.write(file_path, content.replace(old_string, new_string, count))
        if write_result.error:
            return EditResult(error=write_result.error)
        return EditResult(path=file_path, occurrences=n if replace_all else 1)

    def delete(self, file_path: str) -> DeleteResult:
        try:
            rc, _, err = self._loop.submit(self._io.rm(self._io.mount_path(file_path)))
        except Exception as exc:  # noqa: BLE001
            return DeleteResult(error=f"Delete '{file_path}': {exc}")
        if rc != 0:
            return DeleteResult(error=f"Delete '{file_path}': {err.strip() or 'exit ' + str(rc)}")
        return DeleteResult(path=file_path)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        cmd = _build_grep_cmd(self._io.mount_path(path or "/"), pattern, glob, max_count)
        rc, data, err = self._loop.submit(self._io.shell(cmd))
        if rc not in (0, 1):
            return GrepResult(error=f"Grep: {err.strip() or 'exit ' + str(rc)}")
        return GrepResult(matches=list(self._parse_grep(data.decode("utf-8", errors="replace"))))

    def _parse_grep(self, text: str) -> Iterator[GrepMatch]:
        for line in text.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            file_path, line_no_str, matched = parts
            try:
                yield GrepMatch(
                    path=self._io.virtual_path(file_path),
                    line=int(line_no_str),
                    text=matched,
                    context_before=[],
                    context_after=[],
                )
            except ValueError:
                continue

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        root = self._io.mount_path(path or "/")
        cmd = f"find {shlex.quote(root)} -type f -name {shlex.quote(pattern)}"
        rc, data, err = self._loop.submit(self._io.shell(cmd))
        if rc != 0:
            return GlobResult(error=f"Glob: {err.strip() or 'exit ' + str(rc)}")
        matches = [
            FileInfo(path=self._io.virtual_path(line) or "/", is_dir=False, size=None, modified_at=None)
            for line in data.decode("utf-8", errors="replace").splitlines()
            if line.startswith(self._mount)
        ]
        return GlobResult(matches=matches)


def _build_grep_cmd(root: str, pattern: str, glob: str | None, max_count: int | None) -> str:
    parts = ["grep", "-rniHF"]
    if glob:
        parts.append(f"--include={shlex.quote(glob)}")
    if max_count:
        parts.append(f"-m {int(max_count)}")
    parts.extend(["--", shlex.quote(pattern), shlex.quote(root)])
    return " ".join(parts)


class MirageSandboxBackend(MirageBackend, SandboxBackendProtocol):
    """`MirageBackend` + auto-syncing sandbox for `execute()`.

    Every `execute` mirrors mirage → sandbox, runs in the injected sandbox,
    mirrors back (full mirror; adds, updates, deletes). Sync is
    resource-agnostic — works over `DiskResource`, `S3Resource`, etc.

    The `sandbox` parameter is any `SandboxBackendProtocol`. Callers wire
    `BwrapBackend` for local isolation, or `LocalShellBackend` when the
    outer runtime (e.g. AgentCore) already provides isolation.
    """

    def __init__(
        self,
        resource: BaseResource,
        *,
        sandbox: SandboxBackendProtocol,
        sandbox_dir: str | Path,
        mount_name: str = "disk",
        name: str = "mirage-sandbox",
        cache_limit: str = "512MB",
        index_ttl: float = 600,
    ) -> None:
        super().__init__(
            resource=resource,
            mount_name=mount_name,
            name=name,
            cache_limit=cache_limit,
            index_ttl=index_ttl,
        )
        self._sandbox_dir = Path(sandbox_dir).expanduser().resolve()
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._sandbox = sandbox

    @property
    def id(self) -> str:
        return self._name

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        pull(self._io, self._loop, self._sandbox_dir)
        response = self._sandbox.execute(command, timeout=timeout)
        push(self._io, self._loop, self._sandbox_dir)
        return response
