"""Schema migration framework: v1 -> v2 upgrade, idempotency, new constraints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apr.store.db import (
    BASELINE_SCHEMA_VERSION,
    CURRENT_SCHEMA_VERSION,
    SCHEMA_PATH,
    Database,
    discover_migrations,
)

V2_TABLES = ["nodes", "node_snapshots", "port_forwards", "managed_processes"]


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def _schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()[0])


def _make_v1_db(path: Path) -> None:
    """Build a database exactly as Local v1 left it: schema.sql + version 1 + data."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_version(version) VALUES (1)")
    conn.execute(
        """
        INSERT INTO services (
            id, agent_type, agent_project_id, agent_type_key, agent_project_key,
            service_key, instance_key, name, description,
            code_path, working_directory, start_command, created_at, updated_at
        ) VALUES (
            'SVC_LEGACY', 'human', 'comfy-tools', 'human', 'comfy-tools',
            'model-manager', 'main', 'Model Manager', 'legacy row',
            NULL, NULL, NULL, '2026-07-31T00:00:00Z', '2026-07-31T00:00:00Z'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO allocations (
            id, service_id, allocation_name, request_spec_json,
            state, sticky, created_at
        ) VALUES (
            'ALLOC_LEGACY', 'SVC_LEGACY', 'default', '[]',
            'reserved', 1, '2026-07-31T00:00:00Z'
        )
        """
    )
    conn.execute(
        "INSERT INTO allocated_ports (allocation_id, resource_name, port_name, port, ordinal)"
        " VALUES ('ALLOC_LEGACY', 'http', 'http', 20003, 0)"
    )
    conn.execute(
        "INSERT INTO active_port_claims (port, allocation_id, resource_name, ordinal)"
        " VALUES (20003, 'ALLOC_LEGACY', 'http', 0)"
    )
    conn.commit()
    conn.close()


def test_discovers_bundled_migrations() -> None:
    migrations = discover_migrations()
    assert migrations, "expected at least the 002 migration to ship"
    versions = [v for v, _ in migrations]
    assert versions == sorted(versions)
    assert all(v > BASELINE_SCHEMA_VERSION for v in versions)
    assert CURRENT_SCHEMA_VERSION == versions[-1]


def test_fresh_database_lands_on_current_version(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.db")
    with db.connection() as conn:
        assert _schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert set(V2_TABLES).issubset(_table_names(conn))
    db.close()


def test_v1_database_upgrades_without_losing_data(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _make_v1_db(path)

    # Precondition: a genuine v1 database with no v2 tables.
    probe = sqlite3.connect(str(path))
    assert _schema_version(probe) == 1
    assert not set(V2_TABLES) & _table_names(probe)
    probe.close()

    db = Database(path)
    with db.connection() as conn:
        assert _schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert set(V2_TABLES).issubset(_table_names(conn))

        # v1 rows survive untouched.
        svc = conn.execute(
            "SELECT name, service_key FROM services WHERE id = 'SVC_LEGACY'"
        ).fetchone()
        assert svc["name"] == "Model Manager"
        assert svc["service_key"] == "model-manager"
        claim = conn.execute(
            "SELECT allocation_id FROM active_port_claims WHERE port = 20003"
        ).fetchone()
        assert claim["allocation_id"] == "ALLOC_LEGACY"
    db.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "repeat.db"
    _make_v1_db(path)

    for _ in range(3):
        db = Database(path)
        db.migrate()  # explicit second pass on an already-current database
        with db.connection() as conn:
            assert _schema_version(conn) == CURRENT_SCHEMA_VERSION
            assert (
                conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
            )
            assert conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 1
        db.close()


def _seed_node(db: Database, node_id: str = "NODE_1") -> str:
    db.execute(
        "INSERT INTO nodes (id, name, kind, ssh_host, apr_command, created_at, updated_at)"
        " VALUES (?, ?, 'remote', 'box', 'svcctl', '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z')",
        (node_id, f"name-{node_id}"),
    )
    return node_id


def test_only_one_live_forward_per_local_port(tmp_path: Path) -> None:
    db = Database(tmp_path / "fwd.db")
    node_id = _seed_node(db)

    def insert(fwd_id: str, state: str) -> None:
        db.execute(
            "INSERT INTO port_forwards (id, node_id, remote_port, local_port, state, created_at)"
            " VALUES (?, ?, 20006, 30006, ?, '2026-08-02T00:00:00Z')",
            (fwd_id, node_id, state),
        )

    insert("FWD_1", "active")
    with pytest.raises(sqlite3.IntegrityError):
        insert("FWD_2", "starting")

    # Stopped rows are history and may pile up on the same local port.
    insert("FWD_3", "stopped")
    insert("FWD_4", "stopped")
    db.close()


def test_only_one_live_process_per_service(tmp_path: Path) -> None:
    db = Database(tmp_path / "proc.db")
    db.execute(
        """
        INSERT INTO services (
            id, agent_type_key, agent_project_key, service_key, instance_key,
            name, created_at, updated_at
        ) VALUES (
            'SVC_1', 'human', 'p', 'k', 'main', 'S',
            '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z'
        )
        """
    )

    def insert(proc_id: str, state: str) -> None:
        db.execute(
            "INSERT INTO managed_processes (id, service_id, command, state, created_at)"
            " VALUES (?, 'SVC_1', 'run', ?, '2026-08-02T00:00:00Z')",
            (proc_id, state),
        )

    insert("PROC_1", "running")
    with pytest.raises(sqlite3.IntegrityError):
        insert("PROC_2", "starting")

    insert("PROC_3", "exited")
    db.close()


def test_node_delete_cascades_to_snapshots_and_forwards(tmp_path: Path) -> None:
    db = Database(tmp_path / "cascade.db")
    node_id = _seed_node(db)
    db.execute(
        "INSERT INTO node_snapshots (node_id, fetched_at, status, payload_json)"
        " VALUES (?, '2026-08-02T00:00:00Z', 'ok', '{}')",
        (node_id,),
    )
    db.execute(
        "INSERT INTO port_forwards (id, node_id, remote_port, local_port, state, created_at)"
        " VALUES ('FWD_C', ?, 20006, 30006, 'active', '2026-08-02T00:00:00Z')",
        (node_id,),
    )

    db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

    assert db.fetchone("SELECT COUNT(*) AS c FROM node_snapshots")["c"] == 0
    assert db.fetchone("SELECT COUNT(*) AS c FROM port_forwards")["c"] == 0
    db.close()


def test_service_delete_cascades_to_managed_processes(tmp_path: Path) -> None:
    db = Database(tmp_path / "svc_cascade.db")
    db.execute(
        """
        INSERT INTO services (
            id, agent_type_key, agent_project_key, service_key, instance_key,
            name, created_at, updated_at
        ) VALUES (
            'SVC_D', 'human', 'p', 'k', 'main', 'S',
            '2026-08-02T00:00:00Z', '2026-08-02T00:00:00Z'
        )
        """
    )
    db.execute(
        "INSERT INTO managed_processes (id, service_id, command, state, created_at)"
        " VALUES ('PROC_D', 'SVC_D', 'run', 'exited', '2026-08-02T00:00:00Z')"
    )

    db.execute("DELETE FROM services WHERE id = 'SVC_D'")

    assert db.fetchone("SELECT COUNT(*) AS c FROM managed_processes")["c"] == 0
    db.close()
