"""Config loader + auth + SessionManager."""

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from workspace_service.auth import make_current_user_dep
from workspace_service.config import (
    StorageSpec,
    UserSpec,
    WorkspaceSpec,
    WorkspacesConfig,
    load_config,
)
from workspace_service.session_manager import SessionManager
from workspace_service.workspace_registry import WorkspaceRegistry


CFG_YAML = textwrap.dedent("""
    users:
      chris: {}
    workspaces:
      docs:
        owner: chris
        label: Docs
        runtime: docker-local
        mount_name: docs
        storage: {bucket: b, region: r, prefix: p}
    runtimes:
      docker-local: {}
""").strip()


def test_load_config(tmp_path: Path):
    (tmp_path / "workspaces.yaml").write_text(CFG_YAML)
    cfg = load_config(tmp_path / "workspaces.yaml")
    assert cfg.workspaces["docs"].runtime == "docker-local"
    assert cfg.workspaces["docs"].owner == "chris"


def test_load_config_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_workspace_owner_not_in_users_rejected():
    with pytest.raises(ValueError, match="owner"):
        WorkspacesConfig(
            users={"chris": UserSpec()},
            workspaces={
                "x": WorkspaceSpec(
                    owner="ghost",
                    label="X",
                    runtime="docker-local",
                    storage=StorageSpec(bucket="b", region="r", prefix="p"),
                )
            },
            runtimes={"docker-local": {}},
        )


def test_workspace_runtime_not_declared_rejected():
    with pytest.raises(ValueError, match="runtime"):
        WorkspacesConfig(
            users={"chris": UserSpec()},
            workspaces={
                "x": WorkspaceSpec(
                    owner="chris",
                    label="X",
                    runtime="unknown-runtime",
                    storage=StorageSpec(bucket="b", region="r", prefix="p"),
                )
            },
            runtimes={"docker-local": {}},
        )


def _cfg() -> WorkspacesConfig:
    return WorkspacesConfig(
        users={"chris": UserSpec()},
        workspaces={
            "docs": WorkspaceSpec(
                owner="chris",
                label="Docs",
                runtime="docker-local",
                mount_name="docs",
                storage=StorageSpec(bucket="b", region="r", prefix="p"),
            ),
        },
        runtimes={"docker-local": {}},
    )


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
    with patch("workspace_service.session_manager.build_interpreter") as build:
        interp = MagicMock()
        interp.start = AsyncMock()
        interp.stop = AsyncMock()
        interp.runtime = "docker-local"
        build.return_value = interp

        registry = WorkspaceRegistry(_cfg())
        mgr = SessionManager(registry)
        s1 = await mgr.start_session("docs")
        s2 = await mgr.start_session("docs")
        assert s1.session_id != s2.session_id
        assert set(mgr.list_sessions("docs")) == {s1.session_id, s2.session_id}

        assert mgr.get_session("docs", s1.session_id) is s1
        assert mgr.get_session("docs", "bogus") is None

        await mgr.stop_session("docs", s1.session_id)
        assert mgr.list_sessions("docs") == [s2.session_id]
        interp.stop.assert_awaited()


@pytest.mark.asyncio
async def test_session_manager_unknown_workspace_raises():
    registry = WorkspaceRegistry(_cfg())
    mgr = SessionManager(registry)
    with pytest.raises(KeyError):
        await mgr.start_session("bogus")


def test_registry_list_for_user():
    cfg = _cfg()
    registry = WorkspaceRegistry(cfg)
    views = registry.list_for_user("chris")
    assert [v.workspace_id for v in views] == ["docs"]
    assert views[0].label == "Docs"
    assert views[0].runtime == "docker-local"
    assert registry.owner_of("docs") == "chris"
