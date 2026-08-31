"""Runtime adapter registry.

Ports/adapters wiring. The port is `CodeInterpreterSession` (protocol.py).
Adapters register themselves at import time via `register(name, builder)`.
The service layer calls `build(name, storage, runtime_spec)` — a runtime
kind name, a StorageBinding (bucket/region/prefix + mount info), and the
runtimes.<name> config block.

Adapters do NOT import from workspace_service. They receive pure dicts
and a `StorageBinding` dataclass that has no service-layer types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from code_interpreter.protocol import CodeInterpreterSession


@dataclass(frozen=True, slots=True)
class StorageBinding:
    """Runtime-agnostic view of a workspace's S3 storage."""

    bucket: str
    region: str
    prefix: str
    mount_name: str


Builder = Callable[[StorageBinding, Mapping[str, object]], CodeInterpreterSession]

_builders: dict[str, Builder] = {}


def register(name: str, builder: Builder) -> None:
    _builders[name] = builder


def known() -> list[str]:
    return sorted(_builders)


def build(
    name: str,
    storage: StorageBinding,
    runtime_spec: Mapping[str, object],
) -> CodeInterpreterSession:
    if name not in _builders:
        raise ValueError(
            f"unknown runtime: {name!r}. registered: {known()}"
        )
    return _builders[name](storage, runtime_spec)
