"""Port forwards API — autossh, heavily mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from apr.api.app import create_app
from apr.allocator.pool import PortPool
from apr.config import default_config
from apr.service.ensure import EnsureService
from apr.service.forwards import ForwardManager
from apr.service.nodes import NodeManager
from apr.store.db import Database
from apr.store.repository import Repository


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=33000, end=33050, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.use_unix_socket = False
    cfg.port_pool.start = 33000
    cfg.port_pool.end = 33050
    app = create_app(
        state={
            "config": cfg,
            "db": db,
            "repo": repo,
            "ensure": ensure,
            "db_path": str(db_path),
        }
    )
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path):
    with _client(tmp_path) as c:
        yield c


def _add_node(client: TestClient) -> str:
    r = client.post(
        "/v1/nodes",
        json={"name": "fwd-box", "ssh_host": "127.0.0.1", "ssh_user": "tiou"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_create_and_stop_forward(client: TestClient) -> None:
    nid = _add_node(client)

    fake_proc = MagicMock()
    fake_proc.pid = 424242
    fake_proc.stderr = None

    # pick_local_port sees empty listeners; post-spawn probe sees 33040 bound.
    probe_calls: list[dict] = []

    def _probe() -> dict[int, MagicMock]:
        if not probe_calls:
            probe_calls.append({})
            return {}
        return {33040: MagicMock(port=33040)}

    with (
        patch("apr.service.forwards.shutil.which", return_value="/usr/bin/autossh"),
        patch("apr.service.forwards.subprocess.Popen", return_value=fake_proc) as popen,
        patch("apr.service.forwards._pid_alive", return_value=True),
        patch("apr.service.forwards.probe_listeners", side_effect=_probe),
        patch("apr.service.forwards.time.sleep"),
    ):
        r = client.post(
            f"/v1/nodes/{nid}/forwards",
            json={
                "remote_port": 20010,
                "local_port": 33040,
                "label": "remote-api http",
                "auto_start": False,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["remote_port"] == 20010
        assert body["local_port"] == 33040
        assert body["state"] == "active"
        assert body["auto_start"] is False
        assert body["pid"] == 424242
        assert "127.0.0.1" in body["local_url"]
        fwd_id = body["id"]

        argv = popen.call_args[0][0]
        assert argv[0] == "autossh"
        assert "-M" in argv and "0" in argv
        assert "-N" in argv
        assert "33040:127.0.0.1:20010" in argv
        # ssh_config_managed is the default: preserve the alias and let
        # ~/.ssh/config own user/port/identity/route switching.
        assert argv[-1] == "127.0.0.1"

    with patch("apr.service.forwards._pid_alive", return_value=False), patch(
        "apr.service.forwards.os.kill"
    ):
        r = client.post(f"/v1/forwards/{fwd_id}/stop")
        assert r.status_code == 200
        assert r.json()["state"] == "stopped"
        assert r.json()["auto_start"] is False

    r = client.patch(f"/v1/forwards/{fwd_id}", json={"auto_start": True})
    assert r.status_code == 200
    assert r.json()["state"] == "stopped"
    assert r.json()["auto_start"] is True

    r = client.patch(f"/v1/forwards/{fwd_id}", json={"auto_start": False})
    assert r.status_code == 200
    assert r.json()["state"] == "stopped"
    assert r.json()["auto_start"] is False

    r = client.get("/v1/forwards")
    assert r.status_code == 200
    assert len(r.json()["forwards"]) == 1

    r = client.delete(f"/v1/forwards/{fwd_id}")
    assert r.status_code == 200
    assert r.json() == {"id": fwd_id, "deleted": True}
    assert client.get("/v1/forwards").json()["forwards"] == []


def test_forward_requires_autossh(client: TestClient) -> None:
    nid = _add_node(client)
    with patch("apr.service.forwards.shutil.which", return_value=None):
        r = client.post(
            f"/v1/nodes/{nid}/forwards",
            json={"remote_port": 8080},
        )
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "FORWARD_START_FAILED"


def test_forward_auto_start_requires_boolean(client: TestClient) -> None:
    nid = _add_node(client)
    response = client.post(
        f"/v1/nodes/{nid}/forwards",
        json={"remote_port": 8080, "auto_start": "false"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_maintenance_restores_manually_started_rule_when_parent_dies(
    client: TestClient,
) -> None:
    nid = _add_node(client)
    repo = client.app.state.apr["repo"]
    cfg = client.app.state.apr["config"]
    repo.db.execute(
        """
        INSERT INTO port_forwards (
            id, node_id, remote_port, remote_host, local_port, label,
            pid, state, last_error, auto_reconnect, auto_start,
            created_at, started_at, stopped_at
        ) VALUES (
            'FWD_RESTORE', ?, 8080, '127.0.0.1', 33040, 'restore me',
            111111, 'active', NULL, 1, 0,
            '2026-08-03T00:00:00Z', '2026-08-03T00:00:01Z', NULL
        )
        """,
        (nid,),
    )
    manager = ForwardManager(repo, cfg, NodeManager(repo))
    fake_proc = MagicMock(pid=424242, stderr=None)
    probes = iter(({}, {}, {33040: MagicMock(port=33040)}))

    with (
        patch("apr.service.forwards.shutil.which", return_value="/usr/bin/autossh"),
        patch("apr.service.forwards.subprocess.Popen", return_value=fake_proc),
        patch("apr.service.forwards._pid_alive", side_effect=lambda pid: pid == 424242),
        patch("apr.service.forwards.probe_listeners", side_effect=lambda: next(probes)),
        patch("apr.service.forwards.time.sleep"),
    ):
        results = manager.maintain_rules()

    assert results == [{"id": "FWD_RESTORE", "status": "restarted", "state": "active"}]
    restored = manager.require("FWD_RESTORE")
    assert restored.local_port == 33040
    assert restored.remote_port == 8080
    assert restored.state == "active"


def test_maintenance_does_not_restart_stopped_rule(client: TestClient) -> None:
    nid = _add_node(client)
    repo = client.app.state.apr["repo"]
    cfg = client.app.state.apr["config"]
    repo.db.execute(
        """
        INSERT INTO port_forwards (
            id, node_id, remote_port, remote_host, local_port, label,
            pid, state, last_error, auto_reconnect,
            created_at, started_at, stopped_at
        ) VALUES (
            'FWD_STOPPED', ?, 8080, '127.0.0.1', 33040, 'disabled',
            NULL, 'stopped', NULL, 1,
            '2026-08-03T00:00:00Z', NULL, '2026-08-03T00:00:01Z'
        )
        """,
        (nid,),
    )
    manager = ForwardManager(repo, cfg, NodeManager(repo))

    with patch("apr.service.forwards.subprocess.Popen") as popen:
        assert manager.maintain_rules() == [{"id": "FWD_STOPPED", "status": "stopped"}]
    popen.assert_not_called()


def test_lifespan_starts_stopped_auto_start_forward_rule(tmp_path: Path) -> None:
    client = _client(tmp_path)
    repo = client.app.state.apr["repo"]
    node = NodeManager(repo).create(name="restore", ssh_host="restore-host")
    repo.db.execute(
        """
        INSERT INTO port_forwards (
            id, node_id, remote_port, remote_host, local_port, label,
            pid, state, last_error, auto_reconnect, auto_start,
            created_at, started_at, stopped_at
        ) VALUES (
            'FWD_BOOT', ?, 9000, '127.0.0.1', 33041, 'boot restore',
            NULL, 'stopped', NULL, 1, 1,
            '2026-08-03T00:00:00Z', NULL, '2026-08-03T00:00:01Z'
        )
        """,
        (node.id,),
    )
    fake_proc = MagicMock(pid=424243, stderr=None)
    probes = iter(({}, {33041: MagicMock(port=33041)}))

    with (
        patch("apr.service.forwards.shutil.which", return_value="/usr/bin/autossh"),
        patch("apr.service.forwards.subprocess.Popen", return_value=fake_proc),
        patch("apr.service.forwards._pid_alive", side_effect=lambda pid: pid == 424243),
        patch("apr.service.forwards.probe_listeners", side_effect=lambda: next(probes)),
        patch("apr.service.forwards.time.sleep"),
        client,
    ):
        restored = ForwardManager(repo, client.app.state.apr["config"], NodeManager(repo)).require(
            "FWD_BOOT"
        )
        assert restored.state == "active"
        assert restored.auto_start is True


def test_lifespan_does_not_start_disabled_forward_rule(tmp_path: Path) -> None:
    client = _client(tmp_path)
    repo = client.app.state.apr["repo"]
    node = NodeManager(repo).create(name="disabled", ssh_host="disabled-host")
    repo.db.execute(
        """
        INSERT INTO port_forwards (
            id, node_id, remote_port, remote_host, local_port, label,
            pid, state, last_error, auto_reconnect, auto_start,
            created_at, started_at, stopped_at
        ) VALUES (
            'FWD_NO_BOOT', ?, 9000, '127.0.0.1', 33042, 'do not restore',
            NULL, 'failed', 'machine restarted', 1, 0,
            '2026-08-03T00:00:00Z', NULL, '2026-08-03T00:00:01Z'
        )
        """,
        (node.id,),
    )

    with patch("apr.service.forwards.subprocess.Popen") as popen, client:
        current = ForwardManager(
            repo,
            client.app.state.apr["config"],
            NodeManager(repo),
        ).require("FWD_NO_BOOT")

    popen.assert_not_called()
    assert current.state == "stopped"
    assert current.auto_start is False
