"""Master-side node registry: SSH control plane to slave APR instances.

Slaves stay on Unix socket only; the master runs ``ssh … -- <apr_command> …``
(BatchMode, no local shell) to list services and proxy process start/stop.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apr.domain.errors import AprError, ErrorCode
from apr.domain.ids import new_node_id
from apr.service.ssh_util import (
    SshTarget,
    split_apr_command,
    ssh_json,
    validate_apr_command,
    validate_identity_file,
    validate_ssh_host,
    validate_ssh_port,
    validate_ssh_user,
)
from apr.store.repository import Repository


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class NodeRecord:
    id: str
    name: str
    kind: str
    ssh_host: str | None
    ssh_user: str | None
    ssh_port: int | None
    identity_file: str | None
    ssh_config_managed: bool
    apr_command: str
    enabled: bool
    refresh_interval_seconds: int
    last_seen_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str

    def to_dict(self, *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "ssh_host": self.ssh_host,
            "ssh_user": self.ssh_user,
            "ssh_port": self.ssh_port,
            "identity_file": self.identity_file,
            "ssh_config_managed": self.ssh_config_managed,
            "apr_command": self.apr_command,
            "enabled": self.enabled,
            "refresh_interval_seconds": self.refresh_interval_seconds,
            "last_seen_at": self.last_seen_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if snapshot is not None:
            d["snapshot"] = snapshot
        return d


def _row_node(row: Any) -> NodeRecord:
    return NodeRecord(
        id=row["id"],
        name=row["name"],
        kind=row["kind"] or "remote",
        ssh_host=row["ssh_host"],
        ssh_user=row["ssh_user"],
        ssh_port=row["ssh_port"],
        identity_file=row["identity_file"],
        ssh_config_managed=bool(row["ssh_config_managed"]),
        apr_command=row["apr_command"] or "svcctl",
        enabled=bool(row["enabled"]),
        refresh_interval_seconds=int(row["refresh_interval_seconds"] or 30),
        last_seen_at=row["last_seen_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class NodeManager:
    def __init__(self, repo: Repository, *, ssh_timeout: float = 30.0) -> None:
        self.repo = repo
        self.ssh_timeout = ssh_timeout

    # ── CRUD ──────────────────────────────────────────────────

    def get(self, node_id: str) -> NodeRecord | None:
        row = self.repo.db.fetchone("SELECT * FROM nodes WHERE id = ?", (node_id,))
        return _row_node(row) if row else None

    def require(self, node_id: str) -> NodeRecord:
        node = self.get(node_id)
        if node is None:
            raise AprError(ErrorCode.NODE_NOT_FOUND, f"Node not found: {node_id}")
        return node

    def list_nodes(self) -> list[NodeRecord]:
        rows = self.repo.db.fetchall("SELECT * FROM nodes ORDER BY name COLLATE NOCASE")
        return [_row_node(r) for r in rows]

    def create(
        self,
        *,
        name: str,
        ssh_host: str,
        ssh_user: str | None = None,
        ssh_port: int | None = None,
        identity_file: str | None = None,
        ssh_config_managed: bool = True,
        apr_command: str = "svcctl",
        enabled: bool = True,
        refresh_interval_seconds: int = 30,
        kind: str = "remote",
    ) -> NodeRecord:
        name = (name or "").strip()
        if not name:
            raise AprError(ErrorCode.INVALID_REQUEST, "name is required")
        if len(name) > 128:
            raise AprError(ErrorCode.INVALID_REQUEST, "name too long")
        host = validate_ssh_host(ssh_host)
        user = validate_ssh_user(ssh_user)
        port = validate_ssh_port(ssh_port)
        identity = validate_identity_file(identity_file)
        cmd = validate_apr_command(apr_command)
        interval = max(5, min(3600, int(refresh_interval_seconds or 30)))
        if kind not in ("remote", "local", "forward-only"):
            raise AprError(
                ErrorCode.INVALID_REQUEST,
                "kind must be remote, local, or forward-only",
            )

        now = _utcnow()
        node_id = new_node_id()
        try:
            self.repo.db.execute(
                """
                INSERT INTO nodes (
                    id, name, kind, ssh_host, ssh_user, ssh_port, identity_file,
                    ssh_config_managed, apr_command, enabled, refresh_interval_seconds,
                    last_seen_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    node_id,
                    name,
                    kind,
                    host,
                    user,
                    port,
                    identity,
                    1 if ssh_config_managed else 0,
                    cmd,
                    1 if enabled else 0,
                    interval,
                    now,
                    now,
                ),
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "unique" in msg:
                raise AprError(
                    ErrorCode.INVALID_REQUEST, f"Node name already exists: {name}"
                ) from exc
            raise
        return self.require(node_id)

    def update(self, node_id: str, **fields: Any) -> NodeRecord:
        node = self.require(node_id)
        updates: dict[str, Any] = {}
        if "name" in fields:
            name = str(fields["name"] or "").strip()
            if not name:
                raise AprError(ErrorCode.INVALID_REQUEST, "name is required")
            updates["name"] = name
        if "ssh_host" in fields:
            updates["ssh_host"] = validate_ssh_host(str(fields["ssh_host"] or ""))
        if "ssh_user" in fields:
            updates["ssh_user"] = validate_ssh_user(fields["ssh_user"])
        if "ssh_port" in fields:
            updates["ssh_port"] = validate_ssh_port(fields["ssh_port"])
        if "identity_file" in fields:
            updates["identity_file"] = validate_identity_file(fields["identity_file"])
        if "ssh_config_managed" in fields:
            updates["ssh_config_managed"] = 1 if fields["ssh_config_managed"] else 0
        if "apr_command" in fields:
            updates["apr_command"] = validate_apr_command(str(fields["apr_command"] or "svcctl"))
        if "enabled" in fields:
            updates["enabled"] = 1 if fields["enabled"] else 0
        if "refresh_interval_seconds" in fields:
            updates["refresh_interval_seconds"] = max(
                5, min(3600, int(fields["refresh_interval_seconds"] or 30))
            )
        if "kind" in fields:
            kind = fields["kind"]
            if kind not in ("remote", "local", "forward-only"):
                raise AprError(
                    ErrorCode.INVALID_REQUEST,
                    "kind must be remote, local, or forward-only",
                )
            updates["kind"] = kind

        if updates.get("kind") == "forward-only":
            # A tunnel-only node is not expected to run svcctl. Drop any stale
            # failed snapshot produced before the node was classified correctly.
            self.repo.db.execute(
                "DELETE FROM node_snapshots WHERE node_id = ?", (node_id,)
            )
            updates["last_seen_at"] = None
            updates["last_error"] = None

        if not updates:
            return node
        updates["updated_at"] = _utcnow()
        sets = ", ".join(f"{k} = ?" for k in updates)
        try:
            self.repo.db.execute(
                f"UPDATE nodes SET {sets} WHERE id = ?",
                (*updates.values(), node_id),
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise AprError(
                    ErrorCode.INVALID_REQUEST,
                    f"Node name already exists: {updates.get('name')}",
                ) from exc
            raise
        return self.require(node_id)

    def delete(self, node_id: str) -> dict[str, Any]:
        self.require(node_id)
        self.repo.db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        return {"node_id": node_id, "deleted": True}

    # ── SSH target / remote ───────────────────────────────────

    def target_for(self, node: NodeRecord) -> SshTarget:
        if not node.ssh_host:
            raise AprError(
                ErrorCode.INVALID_REQUEST,
                f"Node {node.id} has no ssh_host",
            )
        if node.ssh_config_managed:
            return SshTarget(host=node.ssh_host)
        return SshTarget(
            host=node.ssh_host,
            user=node.ssh_user,
            port=node.ssh_port,
            identity_file=node.identity_file,
        )

    def _remote_apr(self, node: NodeRecord, *args: str) -> list[str]:
        return [*split_apr_command(node.apr_command), *args]

    def _raise_ssh(self, node: NodeRecord, code: int, stderr: str, stdout: str) -> None:
        detail = (stderr or stdout or "").strip()
        if len(detail) > 800:
            detail = detail[:800] + "…"
        raise AprError(
            ErrorCode.NODE_SSH_FAILED,
            f"SSH to {node.ssh_host} failed (exit {code})"
            + (f": {detail}" if detail else ""),
        )

    def remote_json(
        self,
        node: NodeRecord,
        *apr_args: str,
        timeout: float | None = None,
    ) -> Any:
        """Run ``apr_command …`` on the node and parse JSON stdout."""
        t0 = time.monotonic()
        code, out, err = ssh_json(
            self.target_for(node),
            self._remote_apr(node, *apr_args),
            timeout=timeout if timeout is not None else self.ssh_timeout,
        )
        _ = t0
        if code != 0:
            self._raise_ssh(node, code, err, out)
        text = (out or "").strip()
        if not text:
            raise AprError(
                ErrorCode.NODE_SSH_FAILED,
                f"Empty response from {node.name} ({' '.join(apr_args)})",
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AprError(
                ErrorCode.NODE_SSH_FAILED,
                f"Invalid JSON from {node.name}: {exc}; head={text[:200]!r}",
            ) from exc

    # ── Snapshots ─────────────────────────────────────────────

    def get_snapshot(self, node_id: str) -> dict[str, Any] | None:
        row = self.repo.db.fetchone(
            "SELECT * FROM node_snapshots WHERE node_id = ?", (node_id,)
        )
        if row is None:
            return None
        payload = None
        if row["payload_json"]:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = None
        return {
            "node_id": row["node_id"],
            "fetched_at": row["fetched_at"],
            "status": row["status"],
            "payload": payload,
            "error": row["error"],
            "duration_ms": row["duration_ms"],
        }

    def _write_snapshot(
        self,
        node_id: str,
        *,
        status: str,
        payload: Any | None,
        error: str | None,
        duration_ms: int,
    ) -> dict[str, Any]:
        now = _utcnow()
        payload_json = (
            json.dumps(payload, ensure_ascii=False) if payload is not None else None
        )
        self.repo.db.execute(
            """
            INSERT INTO node_snapshots (node_id, fetched_at, status, payload_json, error, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                status = excluded.status,
                payload_json = excluded.payload_json,
                error = excluded.error,
                duration_ms = excluded.duration_ms
            """,
            (node_id, now, status, payload_json, error, duration_ms),
        )
        if status == "ok":
            self.repo.db.execute(
                "UPDATE nodes SET last_seen_at = ?, last_error = NULL, updated_at = ? WHERE id = ?",
                (now, now, node_id),
            )
        else:
            self.repo.db.execute(
                "UPDATE nodes SET last_error = ?, updated_at = ? WHERE id = ?",
                (error, now, node_id),
            )
        return self.get_snapshot(node_id)  # type: ignore[return-value]

    def refresh(self, node_id: str) -> dict[str, Any]:
        """Pull ``list --json`` over SSH and store snapshot."""
        node = self.require(node_id)
        if node.kind != "remote":
            return {"node": node.to_dict(snapshot=None), "snapshot": None}
        t0 = time.monotonic()
        try:
            payload = self.remote_json(node, "list", "--json")
            duration_ms = int((time.monotonic() - t0) * 1000)
            snap = self._write_snapshot(
                node_id,
                status="ok",
                payload=payload,
                error=None,
                duration_ms=duration_ms,
            )
            return {"node": self.require(node_id).to_dict(snapshot=snap), "snapshot": snap}
        except AprError as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            snap = self._write_snapshot(
                node_id,
                status="error",
                payload=None,
                error=exc.message,
                duration_ms=duration_ms,
            )
            # Surface as structured body rather than hard-failing the refresh endpoint.
            return {
                "node": self.require(node_id).to_dict(snapshot=snap),
                "snapshot": snap,
            }

    def refresh_enabled(self) -> list[dict[str, Any]]:
        results = []
        for node in self.list_nodes():
            if not node.enabled or node.kind != "remote":
                continue
            results.append(self.refresh(node.id))
        return results

    def list_with_snapshots(self) -> list[dict[str, Any]]:
        out = []
        for node in self.list_nodes():
            out.append(node.to_dict(snapshot=self.get_snapshot(node.id)))
        return out

    def detail_with_snapshot(self, node_id: str) -> dict[str, Any]:
        node = self.require(node_id)
        return node.to_dict(snapshot=self.get_snapshot(node_id))

    # ── Remote service ops (live SSH, not only snapshot) ──────

    def list_services_live(self, node_id: str) -> Any:
        node = self.require(node_id)
        return self.remote_json(node, "list", "--json")

    def get_service_live(self, node_id: str, service_id: str) -> Any:
        node = self.require(node_id)
        # Reuse inspect-service CLI (JSON on stdout).
        return self.remote_json(node, "inspect-service", service_id)

    def start_service(self, node_id: str, service_id: str) -> Any:
        node = self.require(node_id)
        return self.remote_json(node, "process", "start", service_id)

    def stop_service(self, node_id: str, service_id: str) -> Any:
        node = self.require(node_id)
        return self.remote_json(node, "process", "stop", service_id)

    def service_logs(self, node_id: str, service_id: str, *, tail: int = 200) -> Any:
        node = self.require(node_id)
        tail = max(1, min(5000, int(tail)))
        return self.remote_json(node, "process", "logs", service_id, "--tail", str(tail))
