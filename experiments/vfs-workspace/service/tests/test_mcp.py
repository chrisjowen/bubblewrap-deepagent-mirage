"""Minimal MCP endpoint smoke — verify auth + tools/list."""

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

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

    fake_ws = MagicMock()
    from workspace_service import workspaces as ws_mod
    monkeypatch.setattr(ws_mod, "_build_workspace", lambda user, specs: fake_ws)

    from workspace_service.main import create_app
    with TestClient(create_app()) as client:
        yield client


def test_mcp_requires_auth(client):
    r = client.post("/mcp/workspaces/chris/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 401


def test_mcp_forbids_cross_user(client):
    r = client.post("/mcp/workspaces/other/mcp",
                    headers={"X-User-Id": "chris"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 403


def test_mcp_tools_list_returns_expected_names(client):
    # First initialize + then tools/list per MCP protocol
    headers = {"X-User-Id": "chris", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    init = client.post(
        "/mcp/workspaces/chris/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        },
    )
    assert init.status_code == 200
    # session id in headers
    session_id = init.headers.get("mcp-session-id")

    tools = client.post(
        "/mcp/workspaces/chris/mcp",
        headers={**headers, **({"mcp-session-id": session_id} if session_id else {})},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert tools.status_code == 200
    # Response may be JSON or SSE; parse either
    body = tools.text
    for expected in ("read", "write", "delete", "ls", "execute"):
        assert expected in body
