"""API-level ensure / list / release tests (acceptance-oriented)."""

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
    pool = PortPool(start=30000, end=30100, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    cfg.use_unix_socket = False
    app = create_app(
        state={
            "config": cfg,
            "db": db,
            "repo": repo,
            "ensure": ensure,
            "db_path": str(db_path),
        }
    )
    with TestClient(app) as c:
        yield c


def _ensure_body(**overrides):
    body = {
        "agent": {"type": "codex"},
        "service": {
            "key": "model-api",
            "instance": "main",
            "project_id": "proj-1",
            "project_origin": "self-built",
            "name": "Model API",
            "description": "本地模型接口",
            "code_path": "/tmp/model",
            "working_directory": "/tmp/model/api",
            "start_command": "uv run python -m api --port {{ports.http}}",
        },
        "allocation_name": "default",
        "resources": [{"name": "http", "type": "single"}],
    }
    body.update(overrides)
    return body


def test_ac001_single_port(client: TestClient) -> None:
    resp = client.post("/v1/allocations/ensure", json=_ensure_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["existing"] is False
    assert "http" in data["ports"]
    assert 30000 <= data["ports"]["http"] <= 30100
    assert data["availability"]["http"]["state"] == "free"


def test_service_allocation_avoids_persistent_forward_rule(client: TestClient) -> None:
    node = client.post(
        "/v1/nodes",
        json={"name": "forward-target", "ssh_host": "forward-target"},
    ).json()
    repo = client.app.state.apr["repo"]
    repo.db.execute(
        """
        INSERT INTO port_forwards (
            id, node_id, remote_port, remote_host, local_port, label,
            pid, state, last_error, auto_reconnect, auto_start,
            created_at, started_at, stopped_at
        ) VALUES (
            'FWD_RESERVED', ?, 8080, '127.0.0.1', 30000, 'reserved rule',
            NULL, 'stopped', NULL, 1, 1,
            '2026-08-03T00:00:00Z', NULL, '2026-08-03T00:00:01Z'
        )
        """,
        (node["id"],),
    )

    body = _ensure_body(
        resources=[
            {
                "name": "http",
                "type": "single",
                "preferred_port": 30000,
                "strict_preferred": True,
            }
        ]
    )
    response = client.post("/v1/allocations/ensure", json=body)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PREFERRED_PORT_UNAVAILABLE"


def test_ac002_idempotent(client: TestClient) -> None:
    ports = set()
    body = _ensure_body()
    for _ in range(20):
        resp = client.post("/v1/allocations/ensure", json=body)
        assert resp.status_code == 200
        data = resp.json()
        ports.add(data["ports"]["http"])
        assert data["existing"] is True or len(ports) == 1
    assert len(ports) == 1
    # subsequent must be existing
    resp = client.post("/v1/allocations/ensure", json=body)
    assert resp.json()["existing"] is True


def test_ac003_block(client: TestClient) -> None:
    body = _ensure_body(
        service={"key": "workers", "instance": "main", "name": "Workers"},
        resources=[{"name": "workers", "type": "block", "size": 8}],
    )
    resp = client.post("/v1/allocations/ensure", json=body)
    assert resp.status_code == 200, resp.text
    block = resp.json()["blocks"]["workers"]
    assert block["size"] == 8
    assert block["end"] - block["start"] + 1 == 8


def test_ac004_count(client: TestClient) -> None:
    body = _ensure_body(
        service={"key": "multi", "name": "Multi"},
        resources=[
            {
                "name": "service-ports",
                "type": "count",
                "count": 5,
                "contiguous": False,
                "port_names": ["p0", "p1", "p2", "p3", "p4"],
            }
        ],
    )
    resp = client.post("/v1/allocations/ensure", json=body)
    assert resp.status_code == 200, resp.text
    ports = resp.json()["ports"]
    assert len(ports) == 5
    assert len(set(ports.values())) == 5


def test_ac005_named_ports_persist(client: TestClient) -> None:
    body = _ensure_body(
        resources=[
            {
                "name": "service-ports",
                "type": "count",
                "count": 3,
                "port_names": ["http", "metrics", "debug"],
            }
        ]
    )
    resp = client.post("/v1/allocations/ensure", json=body)
    data = resp.json()
    sid = data["service_id"]
    ports = data["ports"]
    detail = client.get(f"/v1/services/{sid}").json()
    stored = {
        p["port_name"]: p["port"]
        for a in detail["allocations"]
        for p in a["ports"]
        if p["port_name"]
    }
    assert stored == ports


def test_ac006_atomic_multi_resource_failure(client: TestClient, tmp_path: Path) -> None:
    # Tiny pool: 2 ports — request single + block of 8 must fail fully.
    db = Database(tmp_path / "tiny.db")
    repo = Repository(db)
    pool = PortPool(start=31000, end=31001, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    app = create_app(state={"repo": repo, "ensure": ensure, "db": db})
    with TestClient(app) as c:
        body = _ensure_body(
            service={"key": "atomic", "name": "Atomic"},
            resources=[
                {"name": "http", "type": "single"},
                {"name": "workers", "type": "block", "size": 8},
            ],
        )
        resp = c.post("/v1/allocations/ensure", json=body)
        assert resp.status_code == 507
        assert resp.json()["error"]["code"] == "PORT_CAPACITY_EXHAUSTED"
        # No services with claims
        assert repo.active_claimed_ports() == set()


def test_ac007_unique_claims(client: TestClient) -> None:
    r1 = client.post("/v1/allocations/ensure", json=_ensure_body()).json()
    r2 = client.post(
        "/v1/allocations/ensure",
        json=_ensure_body(service={"key": "other", "name": "Other"}),
    ).json()
    assert r1["ports"]["http"] != r2["ports"]["http"]


def test_ac016_spec_mismatch(client: TestClient) -> None:
    client.post("/v1/allocations/ensure", json=_ensure_body())
    body = _ensure_body(
        resources=[
            {
                "name": "http",
                "type": "count",
                "count": 3,
                "port_names": ["a", "b", "c"],
            }
        ]
    )
    # same service+allocation but different shape
    resp = client.post("/v1/allocations/ensure", json=body)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALLOCATION_SPEC_MISMATCH"


def test_ac017_release_and_reallocate(client: TestClient) -> None:
    data = client.post("/v1/allocations/ensure", json=_ensure_body()).json()
    alloc_id = data["allocation_id"]
    rel = client.post(
        f"/v1/allocations/{alloc_id}/release",
        json={"reason": "gone"},
    )
    assert rel.status_code == 200
    assert rel.json()["state"] == "released"

    # Same service can ensure again (new allocation)
    data2 = client.post("/v1/allocations/ensure", json=_ensure_body()).json()
    assert data2["existing"] is False
    # Other service can take old port
    other = client.post(
        "/v1/allocations/ensure",
        json=_ensure_body(service={"key": "taker", "name": "Taker"}),
    ).json()
    # either new or old port free for taker
    assert "http" in other["ports"]


def test_ac018_port_lookup(client: TestClient) -> None:
    data = client.post("/v1/allocations/ensure", json=_ensure_body()).json()
    port = data["ports"]["http"]
    resp = client.get(f"/v1/ports/{port}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"]["service_key"] == "model-api"
    assert body["active"] is True


def test_ac019_metadata_update_keeps_ports(client: TestClient) -> None:
    data = client.post("/v1/allocations/ensure", json=_ensure_body()).json()
    port = data["ports"]["http"]
    sid = data["service_id"]
    patch = client.patch(
        f"/v1/services/{sid}",
        json={"description": "新的服务说明", "start_command": "run {{ports.http}}"},
    )
    assert patch.status_code == 200
    assert patch.json()["description"] == "新的服务说明"
    again = client.post("/v1/allocations/ensure", json=_ensure_body()).json()
    assert again["ports"]["http"] == port


def test_list_and_search(client: TestClient) -> None:
    client.post("/v1/allocations/ensure", json=_ensure_body())
    resp = client.get("/v1/services", params={"query": "Model"})
    assert resp.status_code == 200
    assert len(resp.json()["services"]) >= 1
    resp2 = client.get("/v1/services", params={"agent": "codex"})
    assert len(resp2.json()["services"]) >= 1


def test_ac012_human_no_agent(client: TestClient) -> None:
    body = {
        "agent": None,
        "service": {"key": "local-dashboard", "name": "Dashboard"},
        "resources": [{"name": "http", "type": "single"}],
    }
    resp = client.post("/v1/allocations/ensure", json=body)
    assert resp.status_code == 200
    sid = resp.json()["service_id"]
    detail = client.get(f"/v1/services/{sid}").json()
    assert detail["registered_by_agent"] is None
    assert detail["project_key"] == "-"


def test_agent_is_actor_not_service_identity(client: TestClient) -> None:
    body = _ensure_body()
    first = client.post("/v1/allocations/ensure", json=body).json()
    body["agent"] = {"type": "claude-code"}
    second = client.post("/v1/allocations/ensure", json=body).json()
    assert second["service_id"] == first["service_id"]
    detail = client.get(f"/v1/services/{first['service_id']}").json()
    assert detail["registered_by_agent"] == "claude-code"


def test_master_cannot_ensure_for_remote_node(client: TestClient) -> None:
    node = client.post(
        "/v1/nodes",
        json={"name": "remote", "ssh_host": "remote-alias"},
    ).json()
    remote_body = {**_ensure_body(), "device_id": node["id"]}
    response = client.post("/v1/allocations/ensure", json=remote_body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "target node" in response.json()["error"]["message"].lower()
    assert client.get("/v1/services").json()["services"] == []


def test_ac015_multi_allocation(client: TestClient) -> None:
    body = _ensure_body()
    r1 = client.post("/v1/allocations/ensure", json=body).json()
    body2 = _ensure_body(
        allocation_name="workers",
        resources=[{"name": "workers", "type": "block", "size": 4}],
    )
    r2 = client.post("/v1/allocations/ensure", json=body2).json()
    assert r1["service_id"] == r2["service_id"]
    assert r1["allocation_id"] != r2["allocation_id"]
