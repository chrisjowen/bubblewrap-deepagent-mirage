"""Config loader + auth + SessionManager caching."""

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from workspace_service.auth import make_current_user_dep
from workspace_service.config import UserSpec, WorkspacesConfig, load_config
from workspace_service.workspaces import SessionManager


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

    assert TestClient(app).get("/w").status_code == 401


def test_auth_unknown_user_403():
    app = FastAPI()

    @app.get("/w")
    def _w(u: str = Depends(make_current_user_dep(_cfg()))):
        return {"u": u}

    assert TestClient(app).get("/w", headers={"X-User-Id": "bogus"}).status_code == 403


def test_auth_known_user_passes():
    app = FastAPI()

    @app.get("/w")
    def _w(u: str = Depends(make_current_user_dep(_cfg()))):
        return {"u": u}

    r = TestClient(app).get("/w", headers={"X-User-Id": "chris"})
    assert r.status_code == 200 and r.json() == {"u": "chris"}


@pytest.mark.asyncio
async def test_session_manager_lifecycle():
    with patch("workspace_service.workspaces.build_interpreter") as build:
        interp = MagicMock()
        interp.start = AsyncMock()
        interp.stop = AsyncMock()
        interp.runtime = "docker-local"
        build.return_value = interp

        mgr = SessionManager(_cfg())
        s1 = await mgr.start_session("chris")
        s2 = await mgr.start_session("chris")
        assert s1.session_id != s2.session_id
        assert set(mgr.list_sessions("chris")) == {s1.session_id, s2.session_id}

        assert mgr.get_session("chris", s1.session_id) is s1
        assert mgr.get_session("chris", "bogus") is None

        await mgr.stop_session("chris", s1.session_id)
        assert mgr.list_sessions("chris") == [s2.session_id]
        interp.stop.assert_awaited()


@pytest.mark.asyncio
async def test_session_manager_unknown_user_raises():
    mgr = SessionManager(_cfg())
    with pytest.raises(KeyError):
        await mgr.start_session("bogus")
