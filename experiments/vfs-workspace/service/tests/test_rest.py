"""REST smoke — file browse via direct S3 (S3IO mocked)."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

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


class FakeS3IO:
    def __init__(self):
        self.files: dict[str, bytes] = {"hello.txt": b"hello"}

    def read(self, path):
        data = self.files.get(path.lstrip("/"))
        if data is None:
            return None, "not found"
        return data, None

    def write(self, path, data):
        self.files[path.lstrip("/")] = data
        return None

    def delete(self, path):
        self.files.pop(path.lstrip("/"), None)
        return None

    def ls(self, path="/"):
        from code_interpreter.protocol import ExecResult  # dummy import to keep types loaded
        _ = ExecResult
        for name in self.files:
            yield MagicMock(path="/" + name, is_dir=False, size=len(self.files[name]))


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    (tmp_path / "workspaces.yaml").write_text(CFG)
    monkeypatch.setenv("WORKSPACES_YAML", str(tmp_path / "workspaces.yaml"))

    from workspace_service import workspaces as ws_mod
    fake_io = FakeS3IO()
    monkeypatch.setattr(ws_mod.SessionManager, "s3io", lambda self, uid: fake_io)

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
