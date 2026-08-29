"""REST smoke — file browse via Mirage-backed IO (MirageIO mocked)."""

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


CFG = textwrap.dedent("""
    users:
      chris:
        s3_bucket: b
        s3_region: r
        s3_prefix: p
        runtime: docker-local
""").strip()


class FakeMirageIO:
    def __init__(self):
        self.files: dict[str, bytes] = {"hello.txt": b"hello"}
        self.mount = "/disk"

    def virtual_path(self, mirage: str) -> str:
        return mirage[len(self.mount):] if mirage.startswith(self.mount) else mirage

    async def readdir(self, path="/"):
        return [f"/disk/{name}" for name in self.files]

    async def stat(self, path):
        st = MagicMock()
        st.type = "FILE"
        st.size = len(self.files.get(path.lstrip("/"), b""))
        return st

    async def cat(self, path):
        data = self.files.get(path.lstrip("/"))
        if data is None:
            return (1, b"", b"not found")
        return (0, data, b"")

    async def tee(self, path, data):
        self.files[path.lstrip("/")] = data
        return (0, b"", b"")

    async def rm(self, path):
        self.files.pop(path.lstrip("/"), None)
        return (0, b"", b"")


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    (tmp_path / "workspaces.yaml").write_text(CFG)
    monkeypatch.setenv("WORKSPACES_YAML", str(tmp_path / "workspaces.yaml"))

    fake_io = FakeMirageIO()
    from workspace_service import workspaces as ws_mod
    monkeypatch.setattr(ws_mod.SessionManager, "file_io", lambda self, uid: fake_io)

    from workspace_service.main import create_app
    with TestClient(create_app()) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_workspaces(client):
    r = client.get("/workspaces", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    assert r.json() == [{"id": "chris", "runtime": "docker-local"}]


def test_tree(client):
    r = client.get("/workspaces/chris/tree", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    assert any(e["path"].endswith("hello.txt") for e in r.json()["entries"])


def test_read_file(client):
    r = client.get("/workspaces/chris/files/hello.txt", headers={"X-User-Id": "chris"})
    assert r.status_code == 200 and r.text == "hello"


def test_write_then_read(client):
    r = client.put("/workspaces/chris/files/new.txt", content=b"world",
                   headers={"X-User-Id": "chris"})
    assert r.status_code == 204
    r2 = client.get("/workspaces/chris/files/new.txt", headers={"X-User-Id": "chris"})
    assert r2.text == "world"


def test_delete(client):
    client.put("/workspaces/chris/files/gone.txt", content=b"x",
               headers={"X-User-Id": "chris"})
    r = client.delete("/workspaces/chris/files/gone.txt",
                      headers={"X-User-Id": "chris"})
    assert r.status_code == 204
