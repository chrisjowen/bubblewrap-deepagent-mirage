"""Small helpers: async-loop-in-thread, path translation, byte decode."""

from __future__ import annotations

import asyncio
import base64
import posixpath
import threading
from datetime import datetime
from typing import Awaitable, TypeVar

from deepagents.backends.protocol import FileData, ReadResult

T = TypeVar("T")


class AsyncLoop:
    """Owns an asyncio event loop in a background thread; sync `submit()`."""

    def __init__(self, name: str = "mirage") -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name=name, daemon=True)
        self._thread.start()

    def submit(self, coro: Awaitable[T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)


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


def parse_mtime(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def decode_content(data: bytes) -> tuple[FileData, str | None]:
    """Return `(FileData, text)`. `text` is `None` when content is binary."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileData(content=base64.b64encode(data).decode("ascii"), encoding="base64"), None
    return FileData(content=text, encoding="utf-8"), text


def slice_lines(text: str, offset: int, limit: int) -> ReadResult:
    if limit <= 0:
        return ReadResult(file_data=FileData(content="", encoding="utf-8"), no_lines_requested=True)
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if total == 0:
        return ReadResult(file_data=FileData(content="", encoding="utf-8"))
    start = max(0, min(offset, total))
    end = min(total, start + limit)
    if start >= end:
        return ReadResult(file_data=FileData(content="", encoding="utf-8"))
    return ReadResult(
        file_data=FileData(content="".join(lines[start:end]), encoding="utf-8"),
        total_lines=total,
        start_line=start + 1,
        end_line=end,
        next_offset=end if end < total else None,
    )
