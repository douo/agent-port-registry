"""Step 1: healthz and status smoke tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apr.api.app import create_app
from apr.config import MAX_UNIX_SOCKET_PATH_BYTES, load_config
from apr.cli.client import health_check, is_registry_up


def test_healthz_via_asgi() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "apr"
    assert "version" in body


def test_load_config_respects_data_dir(tmp_path: Path) -> None:
    cfg = load_config(data_dir=tmp_path / "apr-data")
    assert cfg.data_dir == tmp_path / "apr-data"
    assert cfg.db_path == tmp_path / "apr-data" / "apr.db"
    assert cfg.socket_path.name.endswith(".sock")
    assert len(os.fsencode(cfg.socket_path)) <= MAX_UNIX_SOCKET_PATH_BYTES


def test_load_config_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "env-data"
    monkeypatch.setenv("APR_DATA_DIR", str(data))
    monkeypatch.setenv("APR_USE_TCP", "1")
    monkeypatch.setenv("APR_HTTP_PORT", "19001")
    monkeypatch.setenv("APR_AUTO_START", "0")
    cfg = load_config(env=os.environ)
    assert cfg.data_dir == data
    assert cfg.use_unix_socket is False
    assert cfg.http_port == 19001
    assert cfg.auto_start is False


def test_health_check_down_when_no_server(tmp_path: Path) -> None:
    cfg = load_config(data_dir=tmp_path / "down")
    cfg.use_unix_socket = True
    # Socket does not exist → down
    assert is_registry_up(cfg) is False
    assert health_check(cfg) is None
