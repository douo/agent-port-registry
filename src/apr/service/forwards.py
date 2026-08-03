"""Port forwards via autossh (master → slave localhost ports)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apr.config import Config
from apr.domain.errors import AprError, ErrorCode
from apr.domain.ids import new_forward_id
from apr.listener.probe import probe_listeners
from apr.service.nodes import NodeManager, NodeRecord
from apr.service.process import _pid_alive  # reuse robust liveness
from apr.service.ssh_util import (
    validate_identity_file,
    validate_ssh_host,
    validate_ssh_port,
    validate_ssh_user,
)
from apr.store.repository import Repository

LIVE_FORWARD_STATES = frozenset({"starting", "active", "reconnecting"})


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ForwardRecord:
    id: str
    node_id: str
    remote_port: int
    remote_host: str
    local_port: int
    label: str | None
    pid: int | None
    state: str
    last_error: str | None
    auto_reconnect: bool
    created_at: str
    started_at: str | None
    stopped_at: str | None

    def to_dict(self, *, alive: bool | None = None) -> dict[str, Any]:
        is_live = self.state in LIVE_FORWARD_STATES
        if alive is None:
            alive = _pid_alive(self.pid) if is_live else False
        return {
            "id": self.id,
            "node_id": self.node_id,
            "remote_port": self.remote_port,
            "remote_host": self.remote_host,
            "local_port": self.local_port,
            "label": self.label,
            "pid": self.pid,
            "state": self.state,
            "last_error": self.last_error,
            "auto_reconnect": self.auto_reconnect,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "alive": bool(alive),
            "local_url": f"http://127.0.0.1:{self.local_port}",
        }


def _row_forward(row: Any) -> ForwardRecord:
    return ForwardRecord(
        id=row["id"],
        node_id=row["node_id"],
        remote_port=int(row["remote_port"]),
        remote_host=row["remote_host"] or "127.0.0.1",
        local_port=int(row["local_port"]),
        label=row["label"],
        pid=row["pid"],
        state=row["state"],
        last_error=row["last_error"],
        auto_reconnect=bool(row["auto_reconnect"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        stopped_at=row["stopped_at"],
    )


class ForwardManager:
    def __init__(self, repo: Repository, config: Config, nodes: NodeManager) -> None:
        self.repo = repo
        self.config = config
        self.nodes = nodes

    def get(self, forward_id: str) -> ForwardRecord | None:
        row = self.repo.db.fetchone(
            "SELECT * FROM port_forwards WHERE id = ?", (forward_id,)
        )
        return _row_forward(row) if row else None

    def require(self, forward_id: str) -> ForwardRecord:
        fwd = self.get(forward_id)
        if fwd is None:
            raise AprError(ErrorCode.FORWARD_NOT_FOUND, f"Forward not found: {forward_id}")
        return fwd

    def list_forwards(self, *, node_id: str | None = None) -> list[ForwardRecord]:
        if node_id:
            rows = self.repo.db.fetchall(
                "SELECT * FROM port_forwards WHERE node_id = ? ORDER BY created_at DESC",
                (node_id,),
            )
        else:
            rows = self.repo.db.fetchall(
                "SELECT * FROM port_forwards ORDER BY created_at DESC"
            )
        return [_row_forward(r) for r in rows]

    def list_live(self, *, node_id: str | None = None) -> list[ForwardRecord]:
        out = []
        for f in self.list_forwards(node_id=node_id):
            if f.state in LIVE_FORWARD_STATES:
                out.append(f)
        return out

    def _mark(
        self,
        forward_id: str,
        *,
        state: str | None = None,
        pid: int | None = None,
        last_error: str | None = None,
        started: bool = False,
        stopped: bool = False,
        clear_error: bool = False,
    ) -> ForwardRecord:
        fields: dict[str, Any] = {}
        if state is not None:
            fields["state"] = state
        if pid is not None:
            fields["pid"] = pid
        if last_error is not None:
            fields["last_error"] = last_error
        if clear_error:
            fields["last_error"] = None
        if started:
            fields["started_at"] = _utcnow()
        if stopped:
            fields["stopped_at"] = _utcnow()
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.repo.db.execute(
                f"UPDATE port_forwards SET {sets} WHERE id = ?",
                (*fields.values(), forward_id),
            )
        return self.require(forward_id)

    def reconcile(self, forward_id: str | None = None) -> None:
        """Reconcile tunnel state without interrupting AutoSSH retries."""
        items = [self.require(forward_id)] if forward_id else self.list_live()
        listening = set(probe_listeners().keys())
        for fwd in items:
            if fwd.state not in LIVE_FORWARD_STATES:
                continue
            if _pid_alive(fwd.pid) and fwd.local_port in listening:
                if fwd.state in ("starting", "reconnecting"):
                    self._mark(fwd.id, state="active", clear_error=True)
                continue
            if _pid_alive(fwd.pid) and fwd.local_port not in listening:
                if fwd.auto_reconnect:
                    self._mark(
                        fwd.id,
                        state="reconnecting",
                        last_error="SSH route unavailable; AutoSSH is retrying",
                    )
                elif fwd.state == "active":
                    self._mark(
                        fwd.id,
                        state="failed",
                        last_error="SSH process alive but local port is not listening",
                        stopped=True,
                    )
                    self._kill_pid(fwd.pid)
                continue
            # Dead
            self._mark(
                fwd.id,
                state="failed" if fwd.auto_reconnect or fwd.state == "starting" else "stopped",
                last_error="forward process no longer running",
                stopped=True,
            )

    def _busy_local_ports(self) -> set[int]:
        claimed = self.repo.active_claimed_ports()
        listening = set(probe_listeners().keys())
        live_fwd = {
            f.local_port
            for f in self.list_forwards()
            if f.state in LIVE_FORWARD_STATES
        }
        return claimed | listening | live_fwd

    def pick_local_port(self, preferred: int | None = None) -> int:
        busy = self._busy_local_ports()
        pool = self.config.port_pool
        if preferred is not None:
            if not (1 <= preferred <= 65535):
                raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid local_port: {preferred}")
            if preferred in busy:
                raise AprError(
                    ErrorCode.LOCAL_PORT_UNAVAILABLE,
                    f"Local port {preferred} is already in use",
                )
            return preferred
        # Prefer high end of pool to reduce clash with allocated services.
        start, end = pool.start, pool.end
        for port in range(end, start - 1, -1):
            if port not in busy:
                return port
        raise AprError(
            ErrorCode.PORT_CAPACITY_EXHAUSTED,
            "No free local port available for forwarding",
        )

    def _build_forward_argv(
        self,
        node: NodeRecord,
        *,
        local_port: int,
        remote_port: int,
        remote_host: str,
        auto_reconnect: bool,
    ) -> list[str]:
        executable = "autossh" if auto_reconnect else "ssh"
        if shutil.which(executable) is None:
            raise AprError(
                ErrorCode.FORWARD_START_FAILED,
                f"{executable} not found on PATH",
            )
        host = validate_ssh_host(node.ssh_host or "")
        user = None if node.ssh_config_managed else validate_ssh_user(node.ssh_user)
        port = None if node.ssh_config_managed else validate_ssh_port(node.ssh_port)
        identity = (
            None
            if node.ssh_config_managed
            else validate_identity_file(node.identity_file)
        )
        # remote_host is the host as seen FROM the slave (almost always 127.0.0.1).
        rh = remote_host.strip() or "127.0.0.1"
        if rh not in ("127.0.0.1", "localhost", "::1") and not rh.replace(".", "").isdigit():
            # Allow simple hostnames for personal use.
            validate_ssh_host(rh)

        argv = [executable]
        if auto_reconnect:
            argv.extend(["-M", "0"])
        argv.extend([
            "-N",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-L",
            f"{local_port}:{rh}:{remote_port}",
        ])
        if port is not None:
            argv.extend(["-p", str(port)])
        if identity is not None:
            argv.extend(["-i", identity])
        dest = f"{user}@{host}" if user else host
        argv.append(dest)
        return argv

    def _kill_pid(self, pid: int | None) -> None:
        if pid is None or pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def start(
        self,
        node_id: str,
        *,
        remote_port: int,
        local_port: int | None = None,
        remote_host: str = "127.0.0.1",
        label: str | None = None,
        auto_reconnect: bool = True,
        _record_id: str | None = None,
    ) -> ForwardRecord:
        node = self.nodes.require(node_id)
        if not node.ssh_host:
            raise AprError(ErrorCode.INVALID_REQUEST, "Node has no ssh_host")
        if not (1 <= int(remote_port) <= 65535):
            raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid remote_port: {remote_port}")

        # One live forward per (node, remote_port) is enough for personal use.
        for existing in self.list_live(node_id=node_id):
            if existing.remote_port == int(remote_port) and (
                existing.remote_host or "127.0.0.1"
            ) == (remote_host or "127.0.0.1"):
                self.reconcile(existing.id)
                live = self.get(existing.id)
                if live and live.state in LIVE_FORWARD_STATES and _pid_alive(live.pid):
                    return live

        chosen = self.pick_local_port(local_port)
        now = _utcnow()
        fwd_id = _record_id or new_forward_id()
        if _record_id is None:
            self.repo.db.execute(
                """
                INSERT INTO port_forwards (
                    id, node_id, remote_port, remote_host, local_port, label,
                    pid, state, last_error, auto_reconnect,
                    created_at, started_at, stopped_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'starting', NULL, ?, ?, NULL, NULL)
                """,
                (
                    fwd_id,
                    node_id,
                    int(remote_port),
                    remote_host or "127.0.0.1",
                    chosen,
                    label,
                    1 if auto_reconnect else 0,
                    now,
                ),
            )
        else:
            self.repo.db.execute(
                """
                UPDATE port_forwards
                SET pid = NULL, state = 'starting', last_error = NULL,
                    auto_reconnect = ?, started_at = NULL, stopped_at = NULL
                WHERE id = ?
                """,
                (1 if auto_reconnect else 0, fwd_id),
            )

        argv = self._build_forward_argv(
            node,
            local_port=chosen,
            remote_port=int(remote_port),
            remote_host=remote_host or "127.0.0.1",
            auto_reconnect=auto_reconnect,
        )
        env = os.environ.copy()
        if auto_reconnect:
            env.setdefault("AUTOSSH_GATETIME", "0")
        log_dir = Path(self.config.state_dir) / "forward-logs"
        log_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        log_path = log_dir / f"{fwd_id}.log"
        log_file = None
        try:
            log_file = open(log_path, "ab", buffering=0)  # noqa: SIM115
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            self._mark(
                fwd_id,
                state="failed",
                last_error=f"failed to spawn autossh: {exc}",
                stopped=True,
            )
            raise AprError(
                ErrorCode.FORWARD_START_FAILED, f"failed to spawn autossh: {exc}"
            ) from exc
        finally:
            if log_file is not None:
                log_file.close()

        self._mark(fwd_id, pid=proc.pid, started=True)

        # Brief probe: process still up and local port listening.
        time.sleep(0.4)
        if not _pid_alive(proc.pid):
            try:
                err = log_path.read_text(encoding="utf-8", errors="replace")[-500:]
            except OSError:
                err = ""
            detail = (err or "autossh exited immediately").strip()
            self._mark(fwd_id, state="failed", last_error=detail, stopped=True)
            raise AprError(ErrorCode.FORWARD_START_FAILED, detail)

        listening = set(probe_listeners().keys())
        if chosen in listening:
            return self._mark(fwd_id, state="active", clear_error=True)

        # Tunnel may still be negotiating; leave starting for reconcile.
        return self.require(fwd_id)

    def stop(self, forward_id: str) -> ForwardRecord:
        fwd = self.require(forward_id)
        self._kill_pid(fwd.pid)
        return self._mark(
            forward_id,
            state="stopped",
            last_error=None,
            stopped=True,
            clear_error=True,
        )

    def restart(self, forward_id: str) -> ForwardRecord:
        """Restart a stopped/failed forward on its original local port."""
        fwd = self.require(forward_id)
        self.reconcile(fwd.id)
        current = self.require(fwd.id)
        if current.state in LIVE_FORWARD_STATES and _pid_alive(current.pid):
            return current
        if _pid_alive(current.pid):
            self._kill_pid(current.pid)
        return self.start(
            current.node_id,
            remote_port=current.remote_port,
            local_port=current.local_port,
            remote_host=current.remote_host,
            label=current.label,
            auto_reconnect=current.auto_reconnect,
            _record_id=current.id,
        )

    def reconcile_all(self) -> list[dict[str, Any]]:
        self.reconcile()
        return [f.to_dict() for f in self.list_forwards()]
