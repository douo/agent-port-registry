"""Current schema and database constraints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apr.store.db import Database


CURRENT_TABLES = {
    "nodes",
    "services",
    "allocations",
    "allocated_ports",
    "active_port_claims",
    "node_snapshots",
    "port_forwards",
    "managed_processes",
}


def _seed_service(db: Database, service_id: str = "SVC_1") -> str:
    db.execute(
        """
        INSERT INTO services (
            id, device_id, project_key, service_key, instance_key,
            name, created_at, updated_at
        ) VALUES (?, 'NODE_LOCAL', 'p', 'k', 'main', 'S',
                  '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z')
        """,
        (service_id,),
    )
    return service_id


def _seed_node(db: Database, node_id: str = "NODE_1") -> str:
    db.execute(
        """
        INSERT INTO nodes (
            id, name, kind, ssh_host, apr_command, created_at, updated_at
        ) VALUES (?, ?, 'remote', 'box', 'svcctl',
                  '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z')
        """,
        (node_id, f"name-{node_id}"),
    )
    return node_id


def test_fresh_database_has_current_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.db")
    with db.connection() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert CURRENT_TABLES <= tables
        assert conn.execute(
            "SELECT name FROM nodes WHERE id = 'NODE_LOCAL'"
        ).fetchone()[0] == "本机"
    db.close()


def test_port_claim_is_unique_per_device(tmp_path: Path) -> None:
    db = Database(tmp_path / "claim.db")
    _seed_node(db, "NODE_REMOTE")
    _seed_service(db, "SVC_LOCAL")
    db.execute(
        """
        INSERT INTO services (
            id, device_id, project_key, service_key, instance_key,
            name, created_at, updated_at
        ) VALUES ('SVC_REMOTE', 'NODE_REMOTE', 'p', 'k', 'main', 'R',
                  '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z')
        """
    )
    for alloc_id, svc_id in (("A1", "SVC_LOCAL"), ("A2", "SVC_REMOTE")):
        db.execute(
            "INSERT INTO allocations (id, service_id, request_spec_json, created_at) VALUES (?, ?, '[]', 'now')",
            (alloc_id, svc_id),
        )
    db.execute(
        "INSERT INTO active_port_claims VALUES ('NODE_LOCAL', 'tcp', 41000, 'A1', 'http', 0)"
    )
    db.execute(
        "INSERT INTO active_port_claims VALUES ('NODE_REMOTE', 'tcp', 41000, 'A2', 'http', 0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO active_port_claims VALUES ('NODE_LOCAL', 'tcp', 41000, 'A2', 'http', 0)"
        )
    db.close()


def test_only_one_live_forward_per_local_port(tmp_path: Path) -> None:
    db = Database(tmp_path / "fwd.db")
    node_id = _seed_node(db)

    def insert(fwd_id: str, state: str) -> None:
        db.execute(
            "INSERT INTO port_forwards (id, node_id, remote_port, local_port, state, created_at) VALUES (?, ?, 20006, 30006, ?, 'now')",
            (fwd_id, node_id, state),
        )

    insert("FWD_1", "reconnecting")
    with pytest.raises(sqlite3.IntegrityError):
        insert("FWD_2", "starting")
    insert("FWD_3", "stopped")
    db.close()


def test_process_constraint_and_cascade(tmp_path: Path) -> None:
    db = Database(tmp_path / "proc.db")
    _seed_service(db)
    db.execute(
        "INSERT INTO managed_processes (id, service_id, command, state, created_at) VALUES ('P1', 'SVC_1', 'run', 'running', 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO managed_processes (id, service_id, command, state, created_at) VALUES ('P2', 'SVC_1', 'run', 'starting', 'now')"
        )
    db.execute("DELETE FROM services WHERE id = 'SVC_1'")
    assert db.fetchone("SELECT COUNT(*) AS c FROM managed_processes")["c"] == 0
    db.close()
