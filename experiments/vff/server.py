"""VFF: MCP HTTP server exposing mirage-backed FS tools + monty code exec.

Environment:
    VFF_S3_BUCKET   default "mirage-test-chris"
    VFF_S3_REGION   default "ap-southeast-1"
    VFF_S3_PREFIX   required (S3 key prefix scoping this workspace)
    VFF_MOUNT       default "disk"
    VFF_HOST        default "127.0.0.1"
    VFF_PORT        default "8765"
"""

from __future__ import annotations

import atexit
import os
from contextlib import ExitStack
from dataclasses import asdict
from typing import Any

import pydantic_monty
from dotenv import load_dotenv
from fastmcp import FastMCP
from mirage.resource.s3 import S3Config, S3Resource

from runtime import MirageBackend

load_dotenv()

BUCKET = os.getenv("VFF_S3_BUCKET", "mirage-test-chris")
REGION = os.getenv("VFF_S3_REGION", "ap-southeast-1")
PREFIX = os.getenv("VFF_S3_PREFIX")
MOUNT = os.getenv("VFF_MOUNT", "disk")
HOST = os.getenv("VFF_HOST", "127.0.0.1")
PORT = int(os.getenv("VFF_PORT", "8765"))

if not PREFIX:
    raise SystemExit("VFF_S3_PREFIX must be set (S3 key prefix for this workspace)")

backend = MirageBackend(
    resource=S3Resource(S3Config(bucket=BUCKET, region=REGION, key_prefix=PREFIX)),
    mount_name=MOUNT,
    name="vff",
)

_monty_stack = ExitStack()
_monty_pool = _monty_stack.enter_context(pydantic_monty.Monty())
_monty_session = _monty_stack.enter_context(_monty_pool.checkout())


@atexit.register
def _shutdown() -> None:
    try:
        _monty_stack.close()
    finally:
        backend.close()


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _pack(res: Any) -> dict[str, Any]:
    d = asdict(res)
    if d.get("error"):
        return {"error": d["error"]}
    return _clean(d)


mcp = FastMCP("vff")


@mcp.tool
def read(file_path: str, offset: int = 0, limit: int = 2000) -> dict:
    """Read a file from the S3-backed virtual workspace."""
    return _pack(backend.read(file_path, offset=offset, limit=limit))


@mcp.tool
def write(file_path: str, content: str) -> dict:
    """Overwrite a file in the S3-backed virtual workspace."""
    return _pack(backend.write(file_path, content))


@mcp.tool
def edit(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False
) -> dict:
    """Replace old_string with new_string in a file. Requires unique match unless replace_all."""
    return _pack(backend.edit(file_path, old_string, new_string, replace_all=replace_all))


@mcp.tool
def grep(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    max_count: int | None = None,
) -> dict:
    """Recursive fixed-string grep across the virtual workspace."""
    return _pack(backend.grep(pattern, path=path, glob=glob, max_count=max_count))


@mcp.tool
def glob(pattern: str, path: str | None = None) -> dict:
    """Filename glob search (e.g. '*.py')."""
    return _pack(backend.glob(pattern, path=path))


@mcp.tool
def ls(path: str = "/") -> dict:
    """List directory entries."""
    return _pack(backend.ls(path))


@mcp.tool
def delete(file_path: str) -> dict:
    """Delete a file from the virtual workspace."""
    return _pack(backend.delete(file_path))


@mcp.tool
def execute_code(code: str) -> dict:
    """Execute Python in a monty sandbox. State persists across calls in this server."""
    collector = pydantic_monty.CollectStreams()
    try:
        result = _monty_session.feed_run(code, print_callback=collector)
    except pydantic_monty.MontyError as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "output": _stream_text(collector)}
    return _clean({"result": None if result is None else repr(result), "output": _stream_text(collector)})


def _stream_text(collector: "pydantic_monty.CollectStreams") -> str:
    return "".join(text for _, text in collector.output)


if __name__ == "__main__":
    mcp.run(transport="http", host=HOST, port=PORT)
