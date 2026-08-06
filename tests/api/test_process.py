"""Process management API."""

from __future__ import annotations

import time
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apr.api.app import create_app
from apr.allocator.pool import PortPool
from apr.config import default_config
from apr.domain.errors import AprError
from apr.domain.models import EnsureRequest
from apr.listener.probe import ListenerInfo
from apr.service.ensure import EnsureService
from apr.service.process import render_command
from apr.store.db import Database
from apr.store.repository import Repository


def _make_client(tmp_path: Path, *, enabled: bool) -> tuple[TestClient, object]:
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=31000, end=31100, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.use_unix_socket = False
    cfg.process_management_enabled = enabled
    cfg.process_stop_timeout_seconds = 2
    app = create_app(
        state={
            "config": cfg,
            "db": db,
            "repo": repo,
            "ensure": ensure,
            "db_path": str(db_path),
        }
    )
    return TestClient(app), cfg


@pytest.fixture
def client_pm(tmp_path: Path):
    client, cfg = _make_client(tmp_path, enabled=True)
    with client:
        yield client, cfg


@pytest.fixture
def client_off(tmp_path: Path):
    client, _ = _make_client(tmp_path, enabled=False)
    with client:
        yield client


def _ensure(
    client: TestClient,
    *,
    key: str = "echo-svc",
    start_command: str | None = (
        f"{sys.executable} -c \"print('hello-from-apr'); import time; time.sleep(30)\""
    ),
    working_directory: str | None = None,
) -> dict:
    body = {
        "agent": {"type": "test"},
        "service": {
            "key": key,
            "instance": "main",
            "project_id": "pm",
            "name": key,
            "start_command": start_command,
            "working_directory": working_directory,
        },
        "allocation_name": "default",
        "resources": [{"name": "http", "type": "single"}],
    }
    resp = client.post("/v1/allocations/ensure", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_render_command_substitutes_and_rejects_unknown() -> None:
    assert render_command("x --port {{ports.http}}", {"http": 20001}) == "x --port 20001"
    assert render_command("a {{ ports.a }} b {{ports.b}}", {"a": 1, "b": 2}) == "a 1 b 2"
    with pytest.raises(AprError) as ei:
        render_command("{{ports.missing}}", {"http": 1})
    assert ei.value.code.value == "INVALID_REQUEST"


def test_start_disabled_returns_403(client_off: TestClient) -> None:
    created = _ensure(client_off)
    resp = client_off.post(f"/v1/services/{created['service_id']}/start")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PROCESS_MANAGEMENT_DISABLED"


def test_overview_features_flag(client_pm, client_off: TestClient) -> None:
    c_on, _ = client_pm
    assert c_on.get("/v1/overview").json()["features"]["process_management"] is True
    assert client_off.get("/v1/overview").json()["features"]["process_management"] is False


def test_start_stop_logs_roundtrip(client_pm) -> None:
    client, _cfg = client_pm
    created = _ensure(client)
    sid = created["service_id"]

    start = client.post(f"/v1/services/{sid}/start")
    assert start.status_code == 201, start.text
    body = start.json()
    assert body["state"] == "running"
    assert body["pid"] and body["pid"] > 0
    assert body["alive"] is True

    detail = client.get(f"/v1/services/{sid}").json()
    assert detail["process"]["id"] == body["id"]
    assert detail["process"]["state"] == "running"

    again = client.post(f"/v1/services/{sid}/start")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "PROCESS_ALREADY_RUNNING"

    time.sleep(0.3)
    logs = client.get(f"/v1/services/{sid}/logs", params={"tail": 50})
    assert logs.status_code == 200, logs.text
    log_body = logs.json()
    assert "hello-from-apr" in "\n".join(log_body["lines"])
    assert Path(log_body["log_path"]).is_file()

    clear = client.post(f"/v1/services/{sid}/logs/clear")
    assert clear.status_code == 200, clear.text
    clear_body = clear.json()
    assert clear_body["cleared"] is True
    assert clear_body["log_path"] == log_body["log_path"]
    assert clear_body["process"]["state"] == "running"
    cleared_logs = client.get(f"/v1/services/{sid}/logs", params={"tail": 50})
    assert cleared_logs.status_code == 200, cleared_logs.text
    assert cleared_logs.json()["lines"] == []

    stop = client.post(f"/v1/services/{sid}/stop")
    assert stop.status_code == 200, stop.text
    assert stop.json()["state"] == "stopped"
    assert stop.json()["stopped_at"]

    no_run = client.post(f"/v1/services/{sid}/stop")
    assert no_run.status_code == 409
    assert no_run.json()["error"]["code"] == "PROCESS_NOT_RUNNING"


def test_external_listener_is_observed_and_blocks_duplicate_start(client_pm) -> None:
    client, _cfg = client_pm
    created = _ensure(client, key="external-svc")
    sid = created["service_id"]
    port = created["ports"]["http"]

    observed = {port: ListenerInfo(port=port, pid=4242, command="manual-server")}
    with patch("apr.service.process.probe_listeners", return_value=observed):
        detail = client.get(f"/v1/services/{sid}").json()
        assert detail["runtime"]["state"] == "running"
        assert detail["runtime"]["source"] == "external"
        assert detail["runtime"]["listeners"][0]["port"] == port
        assert detail["process"] is None

        start = client.post(f"/v1/services/{sid}/start")
        assert start.status_code == 409
        assert start.json()["error"]["code"] == "PROCESS_ALREADY_RUNNING"
        assert "outside APR" in start.json()["error"]["message"]

        assert client.patch(
            f"/v1/services/{sid}", json={"auto_start": True}
        ).status_code == 200
        manager = client.app.state.apr["process_manager"]
        result = manager.auto_start_configured()
        assert result[0]["status"] == "skipped"
        assert result[0]["reason"] == "PROCESS_ALREADY_RUNNING"
        assert manager.get_latest(sid) is None


def test_lifespan_auto_starts_configured_service(tmp_path: Path) -> None:
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=31200, end=31220, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.use_unix_socket = False
    cfg.process_management_enabled = True
    cfg.process_stop_timeout_seconds = 2

    created = ensure.ensure(
        EnsureRequest.model_validate(
            {
                "agent": {"type": "test"},
                "service": {
                    "key": "boot-svc",
                    "project_id": "pm",
                    "name": "boot-svc",
                    "start_command": (
                        f'{sys.executable} -c "import time; time.sleep(30)"'
                    ),
                    "auto_start": True,
                },
                "resources": [{"name": "http", "type": "single"}],
            }
        )
    )
    app = create_app(
        state={
            "config": cfg,
            "db": db,
            "repo": repo,
            "ensure": ensure,
            "db_path": str(db_path),
        }
    )

    with TestClient(app) as client:
        status = client.get(f"/v1/services/{created.service_id}/process").json()
        assert status["process"]["state"] == "running"
        assert status["runtime"]["source"] == "managed"
        assert client.post(f"/v1/services/{created.service_id}/stop").status_code == 200


def test_auto_start_skips_service_without_observable_tcp_port(client_pm) -> None:
    client, _cfg = client_pm
    response = client.post(
        "/v1/services",
        json={
            "service": {
                "key": "worker",
                "name": "worker",
                "start_command": f'{sys.executable} -c "import time; time.sleep(30)"',
                "auto_start": True,
            }
        },
    )
    assert response.status_code == 201
    sid = response.json()["id"]

    manager = client.app.state.apr["process_manager"]
    result = manager.auto_start_configured()
    assert result == [
        {
            "service_id": sid,
            "status": "skipped",
            "reason": "runtime_unobservable",
        }
    ]
    assert manager.get_latest(sid) is None


def test_no_start_command(client_pm) -> None:
    client, _ = client_pm
    created = _ensure(client, key="no-cmd", start_command=None)
    sid = created["service_id"]
    # Ensure may leave start_command null; also cover empty string.
    client.patch(f"/v1/services/{sid}", json={"start_command": ""})
    resp = client.post(f"/v1/services/{sid}/start")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "NO_START_COMMAND"


def test_immediate_failure_not_left_running(client_pm) -> None:
    """command-not-found must mark failed and free the live slot — never 'running'."""
    client, _ = client_pm
    created = _ensure(
        client,
        key="missing-bin",
        start_command="this-binary-definitely-does-not-exist-xyz serve",
    )
    sid = created["service_id"]

    start = client.post(f"/v1/services/{sid}/start")
    assert start.status_code == 500, start.text
    assert start.json()["error"]["code"] == "PROCESS_START_FAILED"

    status = client.get(f"/v1/services/{sid}/process").json()
    proc = status["process"]
    assert proc is not None
    assert proc["state"] == "failed"
    assert proc["alive"] is False
    assert proc["exit_code"] not in (None, 0)

    detail = client.get(f"/v1/services/{sid}").json()
    assert detail["process"]["state"] == "failed"
    # Live slot free → can start again (will fail again, but not ALREADY_RUNNING)
    again = client.post(f"/v1/services/{sid}/start")
    assert again.status_code == 500
    assert again.json()["error"]["code"] == "PROCESS_START_FAILED"


def test_port_placeholder_rendered(client_pm) -> None:
    client, cfg = client_pm
    out = Path(cfg.state_dir) / "port-out.txt"
    # After render, the command becomes write('<port number>').
    # f-string {{{{ports.http}}}} → literal {{ports.http}} in the stored command.
    cmd = f'{sys.executable} -c "open(r\'{out}\',\'w\').write(\'{{{{ports.http}}}}\')"'
    created = _ensure(client, key="port-echo", start_command=cmd)
    sid = created["service_id"]
    port = created["ports"]["http"]

    start = client.post(f"/v1/services/{sid}/start")
    assert start.status_code == 201, start.text
    body = start.json()
    assert body["command"] == (
        f'{sys.executable} -c "open(r\'{out}\',\'w\').write(\'{port}\')"'
    )
    # One-shot success: exited immediately with 0, not left "running".
    assert body["state"] == "exited"
    assert body["exit_code"] == 0
    assert body["alive"] is False

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not out.is_file():
        time.sleep(0.05)
    assert out.is_file(), "process did not write output file"
    assert out.read_text() == str(port)

    status = client.get(f"/v1/services/{sid}/process").json()
    assert status["process"]["state"] == "exited"
