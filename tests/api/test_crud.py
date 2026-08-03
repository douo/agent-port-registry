"""Service / allocation CRUD tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apr.api.app import create_app
from apr.allocator.pool import PortPool
from apr.config import default_config
from apr.service.ensure import EnsureService
from apr.store.db import Database
from apr.store.repository import Repository


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=32000, end=32100, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    app = create_app(
        state={"config": cfg, "db": db, "repo": repo, "ensure": ensure, "db_path": str(db_path)}
    )
    with TestClient(app) as c:
        yield c


def test_service_crud(client: TestClient) -> None:
    # Create (no ports)
    r = client.post(
        "/v1/services",
        json={
            "agent": {"type": "codex"},
            "service": {
                "key": "demo",
                "instance": "main",
                "project_id": "p",
                "name": "Demo",
                "description": "d1",
                "auto_start": True,
            },
        },
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["allocations"] == []
    assert r.json()["auto_start"] is True

    # Conflict on same identity
    r2 = client.post(
        "/v1/services",
        json={
            "agent": {"type": "claude-code"},
            "service": {
                "key": "demo",
                "instance": "main",
                "project_id": "p",
                "name": "X",
            },
        },
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "SERVICE_IDENTITY_CONFLICT"

    # Read
    g = client.get(f"/v1/services/{sid}")
    assert g.status_code == 200
    assert g.json()["name"] == "Demo"

    # Update
    u = client.patch(
        f"/v1/services/{sid}",
        json={"description": "d2", "name": "Demo2", "auto_start": False},
    )
    assert u.status_code == 200
    assert u.json()["description"] == "d2"
    assert u.json()["name"] == "Demo2"
    assert u.json()["auto_start"] is False

    # List
    lst = client.get("/v1/services")
    assert any(s["id"] == sid for s in lst.json()["services"])

    # Delete
    d = client.request("DELETE", f"/v1/services/{sid}", json={"reason": "gone"})
    assert d.status_code == 200
    assert d.json()["deleted"] is True
    assert client.get(f"/v1/services/{sid}").status_code == 404


def test_master_cannot_create_service_for_remote_node(client: TestClient) -> None:
    node = client.post(
        "/v1/nodes",
        json={"name": "remote", "ssh_host": "remote-alias"},
    ).json()
    response = client.post(
        "/v1/services",
        json={
            "device_id": node["id"],
            "agent": {"type": "codex"},
            "service": {"key": "remote-service", "name": "Remote Service"},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "target node" in response.json()["error"]["message"].lower()
    assert client.get("/v1/services").json()["services"] == []


def test_allocation_crud_and_service_cascade(client: TestClient) -> None:
    body = {
        "agent": {"type": "human"},
        "service": {"key": "web", "name": "Web"},
        "resources": [{"name": "http", "type": "single"}],
    }
    ens = client.post("/v1/allocations/ensure", json=body).json()
    sid = ens["service_id"]
    aid = ens["allocation_id"]
    port = ens["ports"]["http"]

    # Get allocation
    g = client.get(f"/v1/allocations/{aid}")
    assert g.status_code == 200
    assert g.json()["ports"][0]["port"] == port
    assert g.json()["service"]["id"] == sid

    # Release keeps history
    rel = client.post(f"/v1/allocations/{aid}/release", json={"reason": "stop"})
    assert rel.status_code == 200
    assert rel.json()["state"] == "released"
    assert client.get(f"/v1/allocations/{aid}").status_code == 200
    assert client.get(f"/v1/ports/{port}").json()["active"] is False

    # Hard delete allocation
    # Re-ensure to get another alloc, then delete reserved with force
    ens2 = client.post("/v1/allocations/ensure", json=body).json()
    aid2 = ens2["allocation_id"]
    port2 = ens2["ports"]["http"]
    dd = client.request(
        "DELETE", f"/v1/allocations/{aid2}", params={"force": "true"}, json={}
    )
    assert dd.status_code == 200
    assert dd.json()["deleted"] is True
    assert port2 in dd.json()["ports_freed"]
    assert client.get(f"/v1/allocations/{aid2}").status_code == 404

    # Cascade delete service removes remaining history (released aid)
    d = client.request("DELETE", f"/v1/services/{sid}", json={"reason": "purge"})
    assert d.status_code == 200
    assert sid == d.json()["service_id"]
    assert client.get(f"/v1/services/{sid}").status_code == 404
    assert client.get(f"/v1/allocations/{aid}").status_code == 404
