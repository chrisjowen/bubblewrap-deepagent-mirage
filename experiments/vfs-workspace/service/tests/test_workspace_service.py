"""Minimal tests for config loader + auth + WorkspaceManager caching."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from workspace_service.auth import make_current_user_dep
from workspace_service.config import UserSpec, WorkspacesConfig, load_config
from workspace_service.workspaces import WorkspaceManager


CFG_YAML = textwrap.dedent("""
    users:
      chris:
        s3_bucket: b
        s3_region: r
        s3_prefix: p
        runtime: docker-local
""").strip()


def test_load_config(tmp_path: Path):
    (tmp_path / "workspaces.yaml").write_text(CFG_YAML)
    cfg = load_config(tmp_path / "workspaces.yaml")
    assert cfg.users["chris"].runtime == "docker-local"


def test_load_config_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def _cfg() -> WorkspacesConfig:
    return WorkspacesConfig(users={
        "chris": UserSpec(s3_bucket="b", s3_region="r", s3_prefix="p", runtime="docker-local"),
    })


def test_auth_missing_header_401():
    app = FastAPI()

    @app.get("/w")
    def _w(u: str = Depends(make_current_user_dep(_cfg()))):
        return {"u": u}

    r = TestClient(app).get("/w")
    assert r.status_code == 401


def test_auth_unknown_user_403():
    app = FastAPI()

    @app.get("/w")
    def _w(u: str = Depends(make_current_user_dep(_cfg()))):
        return {"u": u}

    r = TestClient(app).get("/w", headers={"X-User-Id": "bogus"})
    assert r.status_code == 403


def test_auth_known_user_passes():
    app = FastAPI()

    @app.get("/w")
    def _w(u: str = Depends(make_current_user_dep(_cfg()))):
        return {"u": u}

    r = TestClient(app).get("/w", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    assert r.json() == {"u": "chris"}


def test_workspace_manager_caches():
    with patch("workspace_service.workspaces._build_workspace") as build:
        build.return_value = MagicMock()
        mgr = WorkspaceManager(_cfg())
        w1 = mgr.get_or_open("chris")
        w2 = mgr.get_or_open("chris")
        assert w1 is w2
        assert build.call_count == 1


def test_workspace_manager_close_evicts():
    with patch("workspace_service.workspaces._build_workspace") as build:
        ws = MagicMock()
        build.return_value = ws
        mgr = WorkspaceManager(_cfg())
        mgr.get_or_open("chris")
        mgr.close("chris")
        ws.close.assert_called_once()
        mgr.get_or_open("chris")
        assert build.call_count == 2


def test_workspace_manager_unknown_user_raises():
    mgr = WorkspaceManager(_cfg())
    with pytest.raises(KeyError):
        mgr.get_or_open("bogus")
