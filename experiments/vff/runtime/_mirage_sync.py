"""Bidirectional mirror between a mirage workspace and a local sandbox dir."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from runtime._mirage_io import MirageIO
from runtime._mirage_util import AsyncLoop

MTIME_TOLERANCE = 2.0

Meta = tuple[int, float | None]


@dataclass
class Summary:
    label: str
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def log(self) -> None:
        counts = f"+{len(self.added)} ~{len(self.updated)} -{len(self.removed)}"
        detail = " ".join(
            f"{k}={_short(v)}"
            for k, v in (("added", self.added), ("updated", self.updated), ("removed", self.removed))
            if v
        )
        print(f"[{self.label}] {counts}" + (f" {detail}" if detail else ""), file=sys.stderr)


def _short(items: list[str], n: int = 5) -> str:
    return ",".join(items[:n]) + ("…" if len(items) > n else "")


def walk_local(root: Path) -> dict[str, tuple[int, float]]:
    out: dict[str, tuple[int, float]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            abs_ = Path(dirpath) / name
            try:
                st = abs_.stat()
                out[str(abs_.relative_to(root))] = (st.st_size, st.st_mtime)
            except FileNotFoundError:
                continue
    return out


def same(local: tuple[int, float] | None, mirage: Meta | None) -> bool:
    if local is None or mirage is None:
        return False
    if local[0] != mirage[0]:
        return False
    if mirage[1] is None:
        return True
    return abs(local[1] - mirage[1]) <= MTIME_TOLERANCE


def prune_empty_dirs(root: Path) -> None:
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        if dirpath == str(root):
            continue
        p = Path(dirpath)
        if not any(p.iterdir()):
            try:
                p.rmdir()
            except OSError:
                pass


def _touch(path: Path, mtime: float | None) -> None:
    if mtime is None:
        return
    try:
        os.utime(path, (mtime, mtime))
    except FileNotFoundError:
        pass


def pull(io: MirageIO, loop: AsyncLoop, sandbox: Path) -> Summary:
    summary = Summary("pull mirage→sandbox")
    mirage_files = loop.submit(io.walk("/"))
    local_files = walk_local(sandbox)

    for rel, m_meta in mirage_files.items():
        l_meta = local_files.get(rel)
        if same(l_meta, m_meta):
            continue
        rc, data, err = loop.submit(io.cat(io.mount_path("/" + rel)))
        if rc != 0:
            print(f"[pull error] {rel}: {err.strip()}", file=sys.stderr)
            continue
        dst = sandbox / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        _touch(dst, m_meta[1])
        (summary.added if l_meta is None else summary.updated).append(rel)

    for rel in local_files.keys() - mirage_files.keys():
        try:
            (sandbox / rel).unlink()
            summary.removed.append(rel)
        except FileNotFoundError:
            pass
    prune_empty_dirs(sandbox)
    summary.log()
    return summary


def push(io: MirageIO, loop: AsyncLoop, sandbox: Path) -> Summary:
    summary = Summary("push sandbox→mirage")
    local_files = walk_local(sandbox)
    mirage_files = loop.submit(io.walk("/"))

    for rel, l_meta in local_files.items():
        if same(l_meta, mirage_files.get(rel)):
            continue
        data = (sandbox / rel).read_bytes()
        rc, _, err = loop.submit(io.tee(io.mount_path("/" + rel), data))
        if rc != 0:
            print(f"[push error] {rel}: {err.strip()}", file=sys.stderr)
            continue
        (summary.added if rel not in mirage_files else summary.updated).append(rel)

    for rel in mirage_files.keys() - local_files.keys():
        rc, _, err = loop.submit(io.rm(io.mount_path("/" + rel)))
        if rc == 0:
            summary.removed.append(rel)
        else:
            print(f"[push delete error] {rel}: {err.strip()}", file=sys.stderr)

    if summary.added or summary.updated:
        refreshed = loop.submit(io.walk("/"))
        for rel in summary.added + summary.updated:
            _touch(sandbox / rel, refreshed.get(rel, (0, None))[1])

    summary.log()
    return summary
