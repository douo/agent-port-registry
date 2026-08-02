"""Repository for services, allocations, and port claims."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from apr.domain.errors import AprError, ErrorCode
from apr.domain.identity import ServiceIdentity
from apr.domain.ids import new_allocation_id, new_service_id
from apr.domain.models import (
    AllocatedPortRecord,
    AllocationRecord,
    AllocationState,
    ServiceRecord,
)
from apr.store.db import Database


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_service(row: Any) -> ServiceRecord:
    return ServiceRecord(
        id=row["id"],
        agent_type=row["agent_type"],
        agent_project_id=row["agent_project_id"],
        agent_type_key=row["agent_type_key"],
        agent_project_key=row["agent_project_key"],
        service_key=row["service_key"],
        instance_key=row["instance_key"],
        name=row["name"],
        description=row["description"],
        code_path=row["code_path"],
        working_directory=row["working_directory"],
        start_command=row["start_command"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_allocation(row: Any, ports: list[AllocatedPortRecord] | None = None) -> AllocationRecord:
    return AllocationRecord(
        id=row["id"],
        service_id=row["service_id"],
        allocation_name=row["allocation_name"],
        request_spec_json=row["request_spec_json"],
        state=AllocationState(row["state"]),
        sticky=bool(row["sticky"]),
        created_at=row["created_at"],
        released_at=row["released_at"],
        release_reason=row["release_reason"],
        ports=ports or [],
    )


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── services ──────────────────────────────────────────────

    def find_service_by_identity(self, identity: ServiceIdentity) -> ServiceRecord | None:
        row = self.db.fetchone(
            """
            SELECT * FROM services
            WHERE agent_type_key = ?
              AND agent_project_key = ?
              AND service_key = ?
              AND instance_key = ?
            """,
            (
                identity.agent_type_key,
                identity.agent_project_key,
                identity.service_key,
                identity.instance_key,
            ),
        )
        return _row_service(row) if row else None

    def get_service(self, service_id: str) -> ServiceRecord | None:
        row = self.db.fetchone("SELECT * FROM services WHERE id = ?", (service_id,))
        return _row_service(row) if row else None

    def create_service(
        self,
        identity: ServiceIdentity,
        *,
        name: str,
        description: str | None = None,
        code_path: str | None = None,
        working_directory: str | None = None,
        start_command: str | None = None,
        conn: Any = None,
    ) -> ServiceRecord:
        now = _utcnow()
        service_id = new_service_id()
        display_name = name or identity.service_key
        sql = """
            INSERT INTO services (
                id, agent_type, agent_project_id, agent_type_key, agent_project_key,
                service_key, instance_key, name, description,
                code_path, working_directory, start_command,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            service_id,
            identity.agent_type,
            identity.agent_project_id,
            identity.agent_type_key,
            identity.agent_project_key,
            identity.service_key,
            identity.instance_key,
            display_name,
            description,
            code_path,
            working_directory,
            start_command,
            now,
            now,
        )
        executor = conn if conn is not None else self.db
        executor.execute(sql, params)
        record = self.get_service_conn(executor, service_id)
        assert record is not None
        return record

    def get_service_conn(self, conn: Any, service_id: str) -> ServiceRecord | None:
        row = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
        return _row_service(row) if row else None

    def find_service_by_identity_conn(
        self, conn: Any, identity: ServiceIdentity
    ) -> ServiceRecord | None:
        row = conn.execute(
            """
            SELECT * FROM services
            WHERE agent_type_key = ?
              AND agent_project_key = ?
              AND service_key = ?
              AND instance_key = ?
            """,
            (
                identity.agent_type_key,
                identity.agent_project_key,
                identity.service_key,
                identity.instance_key,
            ),
        ).fetchone()
        return _row_service(row) if row else None

    def update_service_metadata(
        self,
        service_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        code_path: str | None = None,
        working_directory: str | None = None,
        start_command: str | None = None,
        conn: Any = None,
    ) -> ServiceRecord:
        existing = (
            self.get_service_conn(conn, service_id)
            if conn is not None
            else self.get_service(service_id)
        )
        if existing is None:
            raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")

        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if description is not None:
            fields["description"] = description
        if code_path is not None:
            fields["code_path"] = code_path
        if working_directory is not None:
            fields["working_directory"] = working_directory
        if start_command is not None:
            fields["start_command"] = start_command

        if not fields:
            return existing

        fields["updated_at"] = _utcnow()
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [service_id]
        executor = conn if conn is not None else self.db
        executor.execute(f"UPDATE services SET {sets} WHERE id = ?", params)
        record = self.get_service_conn(executor, service_id) if conn is not None else self.get_service(service_id)
        assert record is not None
        return record

    def list_services(
        self,
        *,
        query: str | None = None,
        agent_type: str | None = None,
        agent_project_id: str | None = None,
    ) -> list[ServiceRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_type is not None:
            clauses.append("agent_type_key = ?")
            params.append(agent_type if agent_type else "human")
        if agent_project_id is not None:
            clauses.append("agent_project_key = ?")
            params.append(agent_project_id if agent_project_id else "-")
        if query:
            q = f"%{query}%"
            clauses.append(
                "(name LIKE ? OR service_key LIKE ? OR IFNULL(description,'') LIKE ? "
                "OR agent_type_key LIKE ? OR agent_project_key LIKE ? "
                "OR IFNULL(code_path,'') LIKE ?)"
            )
            params.extend([q, q, q, q, q, q])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.fetchall(
            f"SELECT * FROM services {where} ORDER BY updated_at DESC",
            params,
        )
        return [_row_service(r) for r in rows]

    # ── allocations ───────────────────────────────────────────

    def find_allocation(
        self, service_id: str, allocation_name: str, *, conn: Any = None
    ) -> AllocationRecord | None:
        executor = conn if conn is not None else self.db
        if conn is not None:
            row = conn.execute(
                """
                SELECT * FROM allocations
                WHERE service_id = ? AND allocation_name = ?
                """,
                (service_id, allocation_name),
            ).fetchone()
        else:
            row = self.db.fetchone(
                """
                SELECT * FROM allocations
                WHERE service_id = ? AND allocation_name = ?
                """,
                (service_id, allocation_name),
            )
        if row is None:
            return None
        ports = self.list_allocated_ports(row["id"], conn=executor if conn is not None else None)
        return _row_allocation(row, ports)

    def get_allocation(self, allocation_id: str, *, conn: Any = None) -> AllocationRecord | None:
        if conn is not None:
            row = conn.execute(
                "SELECT * FROM allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
        else:
            row = self.db.fetchone(
                "SELECT * FROM allocations WHERE id = ?", (allocation_id,)
            )
        if row is None:
            return None
        ports = self.list_allocated_ports(
            allocation_id, conn=conn if conn is not None else None
        )
        return _row_allocation(row, ports)

    def list_allocated_ports(
        self, allocation_id: str, *, conn: Any = None
    ) -> list[AllocatedPortRecord]:
        if conn is not None:
            rows = conn.execute(
                """
                SELECT * FROM allocated_ports
                WHERE allocation_id = ?
                ORDER BY resource_name, ordinal
                """,
                (allocation_id,),
            ).fetchall()
        else:
            rows = self.db.fetchall(
                """
                SELECT * FROM allocated_ports
                WHERE allocation_id = ?
                ORDER BY resource_name, ordinal
                """,
                (allocation_id,),
            )
        return [
            AllocatedPortRecord(
                allocation_id=r["allocation_id"],
                resource_name=r["resource_name"],
                port_name=r["port_name"],
                port=r["port"],
                ordinal=r["ordinal"],
            )
            for r in rows
        ]

    def list_allocations_for_service(self, service_id: str) -> list[AllocationRecord]:
        rows = self.db.fetchall(
            "SELECT * FROM allocations WHERE service_id = ? ORDER BY created_at",
            (service_id,),
        )
        return [
            _row_allocation(r, self.list_allocated_ports(r["id"])) for r in rows
        ]

    def active_claimed_ports(self, *, conn: Any = None) -> set[int]:
        if conn is not None:
            rows = conn.execute("SELECT port FROM active_port_claims").fetchall()
        else:
            rows = self.db.fetchall("SELECT port FROM active_port_claims")
        return {int(r["port"]) for r in rows}

    def create_allocation_with_ports(
        self,
        conn: Any,
        *,
        service_id: str,
        allocation_name: str,
        request_spec: list[dict[str, Any]] | str,
        port_rows: list[dict[str, Any]],
        sticky: bool = True,
    ) -> AllocationRecord:
        """Insert allocation + allocated_ports + active_port_claims in current tx.

        port_rows items: {resource_name, port_name?, port, ordinal}
        """
        now = _utcnow()
        allocation_id = new_allocation_id()
        spec_json = (
            request_spec
            if isinstance(request_spec, str)
            else json.dumps(request_spec, ensure_ascii=False)
        )
        conn.execute(
            """
            INSERT INTO allocations (
                id, service_id, allocation_name, request_spec_json,
                state, sticky, created_at, released_at, release_reason
            ) VALUES (?, ?, ?, ?, 'reserved', ?, ?, NULL, NULL)
            """,
            (allocation_id, service_id, allocation_name, spec_json, 1 if sticky else 0, now),
        )
        for row in port_rows:
            conn.execute(
                """
                INSERT INTO allocated_ports (
                    allocation_id, resource_name, port_name, port, ordinal
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    allocation_id,
                    row["resource_name"],
                    row.get("port_name"),
                    int(row["port"]),
                    int(row.get("ordinal", 0)),
                ),
            )
            conn.execute(
                """
                INSERT INTO active_port_claims (
                    port, allocation_id, resource_name, ordinal
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    int(row["port"]),
                    allocation_id,
                    row["resource_name"],
                    int(row.get("ordinal", 0)),
                ),
            )
        record = self.get_allocation(allocation_id, conn=conn)
        assert record is not None
        return record

    def release_allocation(
        self, allocation_id: str, *, reason: str | None = None
    ) -> AllocationRecord:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
            if row is None:
                raise AprError(
                    ErrorCode.ALLOCATION_NOT_FOUND,
                    f"Allocation not found: {allocation_id}",
                )
            if row["state"] == AllocationState.RELEASED:
                raise AprError(
                    ErrorCode.ALLOCATION_RELEASED,
                    f"Allocation already released: {allocation_id}",
                )
            now = _utcnow()
            conn.execute(
                """
                UPDATE allocations
                SET state = 'released', released_at = ?, release_reason = ?
                WHERE id = ?
                """,
                (now, reason, allocation_id),
            )
            conn.execute(
                "DELETE FROM active_port_claims WHERE allocation_id = ?",
                (allocation_id,),
            )
            record = self.get_allocation(allocation_id, conn=conn)
            assert record is not None
            return record

    def find_by_port(self, port: int) -> dict[str, Any] | None:
        """Lookup active claim by port; include service + allocation."""
        claim = self.db.fetchone(
            "SELECT * FROM active_port_claims WHERE port = ?", (port,)
        )
        if claim is None:
            # Fall back to historical allocated_ports (may be released).
            hist = self.db.fetchone(
                """
                SELECT ap.*, a.state AS allocation_state, a.service_id, a.allocation_name
                FROM allocated_ports ap
                JOIN allocations a ON a.id = ap.allocation_id
                WHERE ap.port = ?
                ORDER BY CASE a.state WHEN 'reserved' THEN 0 ELSE 1 END, a.created_at DESC
                LIMIT 1
                """,
                (port,),
            )
            if hist is None:
                return None
            service = self.get_service(hist["service_id"])
            allocation = self.get_allocation(hist["allocation_id"])
            return {
                "port": port,
                "active": hist["allocation_state"] == "reserved",
                "service": service,
                "allocation": allocation,
                "resource_name": hist["resource_name"],
                "port_name": hist["port_name"],
                "ordinal": hist["ordinal"],
            }

        allocation = self.get_allocation(claim["allocation_id"])
        assert allocation is not None
        service = self.get_service(allocation.service_id)
        return {
            "port": port,
            "active": True,
            "service": service,
            "allocation": allocation,
            "resource_name": claim["resource_name"],
            "port_name": None,
            "ordinal": claim["ordinal"],
        }

    def delete_released_allocation_for_reuse(
        self, conn: Any, service_id: str, allocation_name: str
    ) -> None:
        """Remove a released allocation row so UNIQUE(service_id, name) allows re-create.

        Historical ports stay only if we keep the row; PRD says history is retained
        after release. UNIQUE(service_id, allocation_name) conflicts with re-ensure
        after release. Strategy: rename released row's allocation_name to a unique
        tombstone so history remains queryable by id.
        """
        row = conn.execute(
            """
            SELECT id, state FROM allocations
            WHERE service_id = ? AND allocation_name = ?
            """,
            (service_id, allocation_name),
        ).fetchone()
        if row is None:
            return
        if row["state"] != "released":
            return
        tombstone = f"{allocation_name}__released__{row['id']}"
        conn.execute(
            "UPDATE allocations SET allocation_name = ? WHERE id = ?",
            (tombstone, row["id"]),
        )

    def _purge_allocation_rows(self, conn: Any, allocation_id: str) -> None:
        conn.execute(
            "DELETE FROM active_port_claims WHERE allocation_id = ?",
            (allocation_id,),
        )
        conn.execute(
            "DELETE FROM allocated_ports WHERE allocation_id = ?",
            (allocation_id,),
        )
        conn.execute("DELETE FROM allocations WHERE id = ?", (allocation_id,))

    def delete_allocation(
        self,
        allocation_id: str,
        *,
        reason: str | None = None,
        force: bool = True,
    ) -> dict[str, Any]:
        """Hard-delete an allocation and free any active claims.

        If reserved, claims are dropped first (force=True, default).
        With force=False, only released allocations may be purged.
        """
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
            if row is None:
                raise AprError(
                    ErrorCode.ALLOCATION_NOT_FOUND,
                    f"Allocation not found: {allocation_id}",
                )
            state = row["state"]
            if state == AllocationState.RESERVED and not force:
                raise AprError(
                    ErrorCode.INVALID_REQUEST,
                    f"Allocation {allocation_id} is still reserved; "
                    "release it first or pass force=true to delete.",
                )
            ports = self.list_allocated_ports(allocation_id, conn=conn)
            self._purge_allocation_rows(conn, allocation_id)
            return {
                "allocation_id": allocation_id,
                "service_id": row["service_id"],
                "deleted": True,
                "was_state": state,
                "reason": reason,
                "ports_freed": [p.port for p in ports],
            }

    def delete_service(
        self,
        service_id: str,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Hard-delete a service and all of its allocations / claims / port history."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM services WHERE id = ?", (service_id,)
            ).fetchone()
            if row is None:
                raise AprError(
                    ErrorCode.SERVICE_NOT_FOUND,
                    f"Service not found: {service_id}",
                )
            alloc_rows = conn.execute(
                "SELECT id, state FROM allocations WHERE service_id = ?",
                (service_id,),
            ).fetchall()
            deleted_allocs: list[str] = []
            ports_freed: list[int] = []
            for a in alloc_rows:
                ports = self.list_allocated_ports(a["id"], conn=conn)
                ports_freed.extend(p.port for p in ports)
                self._purge_allocation_rows(conn, a["id"])
                deleted_allocs.append(a["id"])
            conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
            return {
                "service_id": service_id,
                "deleted": True,
                "reason": reason,
                "allocations_deleted": deleted_allocs,
                "ports_freed": sorted(set(ports_freed)),
                "service_key": row["service_key"],
                "instance_key": row["instance_key"],
            }
