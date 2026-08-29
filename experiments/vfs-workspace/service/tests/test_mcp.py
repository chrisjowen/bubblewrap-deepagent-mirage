"""MCP smoke — auth middleware + tools/list."""

import textwrap
from pathlib import Path

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


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    (tmp_path / "workspaces.yaml").write_text(CFG)
    monkeypatch.setenv("WORKSPACES_YAML", str(tmp_path / "workspaces.yaml"))

    from workspace_service.main import create_app
    with TestClient(create_app()) as c:
        yield c


def test_mcp_requires_auth(client):
    r = client.post("/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 401


def test_mcp_unknown_user_403(client):
    r = client.post("/mcp",
                    headers={"X-User-Id": "bogus"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 403


def test_mcp_tools_list(client):
    headers = {"X-User-Id": "chris", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    init = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "t", "version": "1"}}},
    )
    assert init.status_code == 200
    sid = init.headers.get("mcp-session-id")

    tools = client.post(
        "/mcp",
        headers={**headers, **({"mcp-session-id": sid} if sid else {})},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert tools.status_code == 200
    body = tools.text
    for expected in (
        "read", "write", "delete", "ls",
        "start_session", "stop_session", "list_sessions",
        "execute_code", "execute_command",
        "start_command_execution", "get_task", "stop_task",
    ):
        assert expected in body, f"missing tool: {expected}"
