"""Nodes API — SSH control plane, mocked remote."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apr.api.app import create_app
from apr.config import default_config
from apr.store.db import Database
from apr.store.repository import Repository
from apr.service.ensure import EnsureService
from apr.allocator.pool import PortPool


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=32000, end=32100, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.use_unix_socket = False
    cfg.port_pool.start = 32000
    cfg.port_pool.end = 32100
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


def test_node_crud(client: TestClient) -> None:
    r = client.post(
        "/v1/nodes",
        json={
            "name": "lab-box",
            "ssh_host": "192.168.1.50",
            "ssh_user": "tiou",
            "ssh_port": 22,
            "apr_command": "svcctl",
        },
    )
    assert r.status_code == 201, r.text
    node = r.json()
    assert node["name"] == "lab-box"
    assert node["ssh_host"] == "192.168.1.50"
    assert node["enabled"] is True
    nid = node["id"]

    r = client.get("/v1/nodes")
    assert r.status_code == 200
    assert len(r.json()["nodes"]) == 2

    r = client.patch(f"/v1/nodes/{nid}", json={"enabled": False, "ssh_port": 2222})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["ssh_port"] == 2222

    r = client.delete(f"/v1/nodes/{nid}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert [n["id"] for n in client.get("/v1/nodes").json()["nodes"]] == [
        "NODE_LOCAL"
    ]


def test_node_rejects_bad_host(client: TestClient) -> None:
    r = client.post(
        "/v1/nodes",
        json={"name": "x", "ssh_host": "evil;rm -rf /"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_refresh_and_services_snapshot(client: TestClient) -> None:
    r = client.post(
        "/v1/nodes",
        json={"name": "self", "ssh_host": "localhost", "apr_command": "svcctl"},
    )
    nid = r.json()["id"]

    fake_list = {
        "services": [
            {
                "id": "SVC_REMOTE1",
                "name": "remote-api",
                "service_key": "remote-api",
                "instance_key": "main",
                "device_id": nid,
                "project_key": "lab",
                "registered_by_agent": None,
                "allocations": [
                    {
                        "id": "ALLOC_1",
                        "allocation_name": "default",
                        "state": "reserved",
                        "ports": [
                            {
                                "resource_name": "http",
                                "port_name": "http",
                                "port": 20010,
                                "ordinal": 0,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with patch("apr.service.nodes.ssh_json") as mock_ssh:
        mock_ssh.return_value = (0, json.dumps(fake_list), "")
        r = client.post(f"/v1/nodes/{nid}/refresh")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["snapshot"]["status"] == "ok"
        assert body["snapshot"]["payload"]["services"][0]["name"] == "remote-api"

    r = client.get(f"/v1/nodes/{nid}/services")
    assert r.status_code == 200
    services = r.json()["services"]
    assert len(services) == 1
    assert services[0]["id"] == "SVC_REMOTE1"


def test_refresh_ssh_failure_recorded(client: TestClient) -> None:
    r = client.post(
        "/v1/nodes",
        json={"name": "down", "ssh_host": "no-such-host.invalid"},
    )
    nid = r.json()["id"]
    with patch("apr.service.nodes.ssh_json") as mock_ssh:
        mock_ssh.return_value = (255, "", "ssh: connect failed")
        r = client.post(f"/v1/nodes/{nid}/refresh")
        assert r.status_code == 200
        assert r.json()["snapshot"]["status"] == "error"
        assert "connect failed" in (r.json()["snapshot"]["error"] or "")


def test_remote_start_stop_uses_process_cli(client: TestClient) -> None:
    r = client.post(
        "/v1/nodes",
        json={"name": "pm", "ssh_host": "localhost"},
    )
    nid = r.json()["id"]
    with patch("apr.service.nodes.ssh_json") as mock_ssh:
        mock_ssh.return_value = (
            0,
            json.dumps({"id": "PROC_1", "state": "running", "service_id": "SVC_X"}),
            "",
        )
        r = client.post(f"/v1/nodes/{nid}/services/SVC_X/start")
        assert r.status_code == 201
        args = mock_ssh.call_args[0][1]
        assert args[-3:] == ["process", "start", "SVC_X"]

        mock_ssh.return_value = (
            0,
            json.dumps({"id": "PROC_1", "state": "stopped", "service_id": "SVC_X"}),
            "",
        )
        r = client.post(f"/v1/nodes/{nid}/services/SVC_X/stop")
        assert r.status_code == 200
        args = mock_ssh.call_args[0][1]
        assert args[-3:] == ["process", "stop", "SVC_X"]
