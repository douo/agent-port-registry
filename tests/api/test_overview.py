"""Read-only aggregate endpoints backing the Web UI dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apr.allocator.pool import PortPool
from apr.api.app import create_app
from apr.api.routes import _compress_ranges
from apr.config import default_config
from apr.service.ensure import EnsureService
from apr.store.db import Database
from apr.store.repository import Repository

POOL_START = 32000
POOL_END = 32100


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=POOL_START, end=POOL_END, excluded={32050, 32051, 32052})
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
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


def _ensure(client: TestClient, key: str, *, project: str = "proj") -> dict:
    resp = client.post(
        "/v1/allocations/ensure",
        json={
            "agent": {"type": "codex", "project_id": project},
            "service": {"key": key, "instance": "main", "name": key.title()},
            "resources": [{"name": "http", "type": "single"}],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_compress_ranges() -> None:
    assert _compress_ranges([]) == []
    assert _compress_ranges([5]) == [[5, 5]]
    assert _compress_ranges([20000, 20001, 20003]) == [[20000, 20001], [20003, 20003]]
    # Unsorted input is normalised.
    assert _compress_ranges([3, 1, 2]) == [[1, 3]]


def test_overview_on_empty_registry(client: TestClient) -> None:
    body = client.get("/v1/overview").json()

    assert body["services"]["total"] == 0
    assert body["allocations"] == {"reserved": 0, "released": 0}
    assert body["ports"]["claimed"] == 0
    assert body["pool"]["start"] == POOL_START
    assert body["pool"]["end"] == POOL_END
    # 101 ports in range minus 3 excluded.
    assert body["pool"]["usable"] == 98
    assert body["pool"]["utilization"] == 0.0
    # v2 panels answer from day one, before nodes/forwards exist.
    assert body["nodes"] == {"total": 0, "snapshots": 0}
    assert body["forwards"] == {"active": 0}
    assert body["hostname"]
    assert body["version"]


def test_overview_counts_services_and_ports(client: TestClient) -> None:
    _ensure(client, "alpha", project="proj-a")
    _ensure(client, "beta", project="proj-a")
    _ensure(client, "gamma", project="proj-b")

    body = client.get("/v1/overview").json()

    assert body["services"]["total"] == 3
    assert body["services"]["by_agent"] == {"codex": 3}
    assert body["services"]["by_project"] == {"proj-a": 2, "proj-b": 1}
    assert body["allocations"]["reserved"] == 3
    assert body["ports"]["claimed"] == 3
    # Nothing is actually listening on these freshly allocated ports.
    assert body["ports"]["idle"] == 3
    assert body["ports"]["live"] == 0
    assert len(body["ports"]["idle_ports"]) == 3
    assert body["pool"]["free"] == 95
    # The endpoint rounds to 6 decimals, so compare with matching tolerance.
    assert body["pool"]["utilization"] == pytest.approx(3 / 98, abs=1e-6)


def test_overview_reflects_release(client: TestClient) -> None:
    created = _ensure(client, "alpha")
    resp = client.post(f"/v1/allocations/{created['allocation_id']}/release", json={})
    assert resp.status_code == 200, resp.text

    body = client.get("/v1/overview").json()
    assert body["allocations"] == {"reserved": 0, "released": 1}
    assert body["ports"]["claimed"] == 0
    assert body["services"]["total"] == 1


def test_pool_endpoint(client: TestClient) -> None:
    created = _ensure(client, "alpha")
    allocated_port = created["ports"]["http"]

    body = client.get("/v1/pool").json()

    assert body["start"] == POOL_START
    assert body["end"] == POOL_END
    assert body["total"] == 101
    assert body["usable"] == 98
    assert body["excluded_count"] == 3
    assert body["excluded_ranges"] == [[32050, 32052]]
    assert body["claimed"] == [allocated_port]
    assert body["claimed_ranges"] == [[allocated_port, allocated_port]]
    assert body["free"] == 97


def test_listeners_endpoint(client: TestClient) -> None:
    body = client.get("/v1/listeners").json()

    assert body["count"] == len(body["listeners"])
    for item in body["listeners"]:
        assert set(item) == {"port", "pid", "command"}
        assert 1 <= item["port"] <= 65535

    # The test pool is a narrow window; filtering must not widen the result.
    scoped = client.get("/v1/listeners", params={"in_pool": "1"}).json()
    assert scoped["count"] <= body["count"]
    assert all(POOL_START <= i["port"] <= POOL_END for i in scoped["listeners"])
