"""SQLite store and repository tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from apr.domain.errors import AprError, ErrorCode
from apr.domain.identity import ServiceIdentity
from apr.store.db import Database
from apr.store.repository import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    db = Database(tmp_path / "test.db")
    return Repository(db)


def _ident(key: str = "model-api", instance: str = "main") -> ServiceIdentity:
    return ServiceIdentity.from_raw(
        device_id="NODE_LOCAL",
        project_id="proj-1",
        service_key=key,
        instance=instance,
    )


def test_create_and_get_service(repo: Repository) -> None:
    svc = repo.create_service(_ident(), name="Model API", description="desc")
    got = repo.get_service(svc.id)
    assert got is not None
    assert got.name == "Model API"
    assert got.service_key == "model-api"
    assert got.device_id == "NODE_LOCAL"
    assert got.project_key == "proj-1"

    by_id = repo.find_service_by_identity(_ident())
    assert by_id is not None
    assert by_id.id == svc.id


def test_unique_service_identity(repo: Repository) -> None:
    repo.create_service(_ident(), name="A")
    with pytest.raises(Exception):
        repo.create_service(_ident(), name="B")


def test_allocation_claims_and_release(repo: Repository) -> None:
    svc = repo.create_service(_ident(), name="Model API")
    with repo.db.transaction() as conn:
        alloc = repo.create_allocation_with_ports(
            conn,
            service_id=svc.id,
            device_id=svc.device_id,
            allocation_name="default",
            request_spec=[{"name": "http", "type": "single"}],
            port_rows=[
                {
                    "resource_name": "http",
                    "port_name": "http",
                    "port": 20104,
                    "ordinal": 0,
                }
            ],
        )
    assert alloc.state.value == "reserved"
    assert 20104 in repo.active_claimed_ports()

    lookup = repo.find_by_port(20104)
    assert lookup is not None
    assert lookup["active"] is True
    assert lookup["service"].id == svc.id

    released = repo.release_allocation(alloc.id, reason="test")
    assert released.state.value == "released"
    assert 20104 not in repo.active_claimed_ports()

    # History retained
    hist = repo.get_allocation(alloc.id)
    assert hist is not None
    assert len(hist.ports) == 1
    assert hist.ports[0].port == 20104

    # Port can be claimed again by another allocation
    svc2 = repo.create_service(_ident("other"), name="Other")
    with repo.db.transaction() as conn:
        repo.create_allocation_with_ports(
            conn,
            service_id=svc2.id,
            device_id=svc2.device_id,
            allocation_name="default",
            request_spec=[{"name": "http", "type": "single"}],
            port_rows=[
                {
                    "resource_name": "http",
                    "port_name": "http",
                    "port": 20104,
                    "ordinal": 0,
                }
            ],
        )
    assert 20104 in repo.active_claimed_ports()


def test_release_unknown_raises(repo: Repository) -> None:
    with pytest.raises(AprError) as ei:
        repo.release_allocation("alloc_missing")
    assert ei.value.code == ErrorCode.ALLOCATION_NOT_FOUND


def test_double_release_raises(repo: Repository) -> None:
    svc = repo.create_service(_ident(), name="S")
    with repo.db.transaction() as conn:
        alloc = repo.create_allocation_with_ports(
            conn,
            service_id=svc.id,
            device_id=svc.device_id,
            allocation_name="default",
            request_spec=[],
            port_rows=[{"resource_name": "p", "port": 21000, "ordinal": 0}],
        )
    repo.release_allocation(alloc.id)
    with pytest.raises(AprError) as ei:
        repo.release_allocation(alloc.id)
    assert ei.value.code == ErrorCode.ALLOCATION_RELEASED


def test_update_metadata(repo: Repository) -> None:
    svc = repo.create_service(_ident(), name="Old")
    updated = repo.update_service_metadata(
        svc.id,
        description="new desc",
        start_command="run {{ports.http}}",
        auto_start=True,
    )
    assert updated.description == "new desc"
    assert updated.start_command == "run {{ports.http}}"
    assert updated.auto_start is True
    assert updated.name == "Old"


def test_list_and_search(repo: Repository) -> None:
    repo.create_service(_ident("model-api"), name="Model API", description="推理接口")
    repo.create_service(
        ServiceIdentity.from_raw(
            device_id="NODE_LOCAL",
            project_id="p2",
            service_key="frontend",
            instance="dev",
        ),
        name="Frontend",
    )
    all_svcs = repo.list_services()
    assert len(all_svcs) == 2
    found = repo.list_services(query="模型")
    # description has 推理接口 not 模型 — use Model
    found = repo.list_services(query="Model")
    assert len(found) == 1
    by_project = repo.list_services(project_id="proj-1")
    assert len(by_project) == 1


def test_claim_unique_constraint(repo: Repository) -> None:
    s1 = repo.create_service(_ident("a"), name="A")
    s2 = repo.create_service(_ident("b"), name="B")
    with repo.db.transaction() as conn:
        repo.create_allocation_with_ports(
            conn,
            service_id=s1.id,
            device_id=s1.device_id,
            allocation_name="default",
            request_spec=[],
            port_rows=[{"resource_name": "p", "port": 22000, "ordinal": 0}],
        )
    with pytest.raises(Exception):
        with repo.db.transaction() as conn:
            repo.create_allocation_with_ports(
                conn,
                service_id=s2.id,
                device_id=s2.device_id,
                allocation_name="default",
                request_spec=[],
                port_rows=[{"resource_name": "p", "port": 22000, "ordinal": 0}],
            )


def test_tombstone_released_name_allows_reuse(repo: Repository) -> None:
    svc = repo.create_service(_ident(), name="S")
    with repo.db.transaction() as conn:
        alloc = repo.create_allocation_with_ports(
            conn,
            service_id=svc.id,
            device_id=svc.device_id,
            allocation_name="default",
            request_spec=[],
            port_rows=[{"resource_name": "p", "port": 23000, "ordinal": 0}],
        )
    repo.release_allocation(alloc.id)
    with repo.db.transaction() as conn:
        repo.delete_released_allocation_for_reuse(conn, svc.id, "default")
        alloc2 = repo.create_allocation_with_ports(
            conn,
            service_id=svc.id,
            device_id=svc.device_id,
            allocation_name="default",
            request_spec=[],
            port_rows=[{"resource_name": "p", "port": 23001, "ordinal": 0}],
        )
    assert alloc2.id != alloc.id
    # Old history still by id
    old = repo.get_allocation(alloc.id)
    assert old is not None
    assert old.state.value == "released"
