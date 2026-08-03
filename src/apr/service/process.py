"""Managed process lifecycle for services.start_command.

Safety: the whole feature is gated by ``process_management.enabled`` (default
false). When enabled the registry can spawn arbitrary shell commands that were
stored as ``start_command`` — only suitable for trusted loopback use.

By default commands run under the user's login+interactive shell
(``$SHELL -lic``) so PATH and other profile settings match a normal terminal.
"""

from __future__ import annotations

import os
import pwd
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apr.config import Config
from apr.domain.errors import AprError, ErrorCode
from apr.domain.ids import new_process_id
from apr.domain.models import AllocationState
from apr.store.repository import Repository

# Matches the frontend preview in ServiceDetail.tsx:renderCommand.
_PORT_PLACEHOLDER = re.compile(r"\{\{\s*ports\.([A-Za-z0-9_-]+)\s*\}\}")

LIVE_STATES = frozenset({"starting", "running"})

# How long after spawn we wait to catch "command not found" / immediate crash.
_STARTUP_PROBE_SECONDS = 0.5


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def render_command(command: str, ports: dict[str, int]) -> str:
    """Substitute ``{{ports.NAME}}`` placeholders. Unresolved names raise."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in ports:
            raise AprError(
                ErrorCode.INVALID_REQUEST,
                f"start_command references unknown port placeholder: {{{{ports.{name}}}}}; "
                f"available: {', '.join(sorted(ports)) or '(none)'}",
            )
        return str(ports[name])

    return _PORT_PLACEHOLDER.sub(_sub, command)


def port_map_for_service(repo: Repository, service_id: str) -> dict[str, int]:
    """Build name→port map from reserved allocations (same shape as ensure)."""
    ports: dict[str, int] = {}
    for alloc in repo.list_allocations_for_service(service_id):
        if alloc.state != AllocationState.RESERVED:
            continue
        by_res: dict[str, list] = {}
        for p in alloc.ports:
            by_res.setdefault(p.resource_name, []).append(p)
        for res_name, items in by_res.items():
            items_sorted = sorted(items, key=lambda x: x.ordinal)
            if all(i.port_name for i in items_sorted):
                for i in items_sorted:
                    ports[str(i.port_name)] = i.port
            elif len(items_sorted) == 1:
                key = items_sorted[0].port_name or res_name
                ports[str(key)] = items_sorted[0].port
            else:
                # Contiguous block: expose start / end aliases and the resource name
                # as the first port so simple templates still work.
                ports[res_name] = items_sorted[0].port
                ports[f"{res_name}.start"] = items_sorted[0].port
                ports[f"{res_name}.end"] = items_sorted[-1].port
    return ports


def resolve_user_shell() -> str:
    """Prefer passwd shell, then $SHELL, then /bin/sh."""
    try:
        shell = pwd.getpwuid(os.getuid()).pw_shell
        if shell and Path(shell).is_file():
            return shell
    except (KeyError, OSError):
        pass
    env_shell = os.environ.get("SHELL")
    if env_shell and Path(env_shell).is_file():
        return env_shell
    return "/bin/sh"


def _exit_code_from_status(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    return status


def _try_reap(pid: int) -> int | None:
    """If *pid* is our child and has exited (incl. zombie), reap and return code."""
    try:
        waited, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return None
    except OSError:
        return None
    if waited == 0:
        return None
    if waited == pid:
        return _exit_code_from_status(status)
    return None


def _proc_state_letter(pid: int) -> str | None:
    """Return the single-letter State from /proc/pid/status, or None if gone."""
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    for line in text.splitlines():
        if line.startswith("State:"):
            parts = line.split()
            return parts[1] if len(parts) >= 2 else None
    return None


def _pid_alive(pid: int | None) -> bool:
    """True only for a still-running process (zombies count as dead)."""
    if pid is None or pid <= 0:
        return False

    # Reap our own zombies first — os.kill(pid, 0) succeeds on zombies.
    if _try_reap(pid) is not None:
        return False

    state = _proc_state_letter(pid)
    if state == "Z":
        # Zombie we are not the parent of (or reap failed); treat as dead.
        return False

    # Linux /proc gives us the state above. macOS and other Unix platforms do
    # not expose /proc, so fall through to the portable signal-0 probe. A
    # missing pid is still distinguished by ProcessLookupError.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class ManagedProcess:
    id: str
    service_id: str
    allocation_id: str | None
    command: str
    working_directory: str | None
    pid: int | None
    state: str
    exit_code: int | None
    log_path: str | None
    last_error: str | None
    created_at: str
    started_at: str | None
    stopped_at: str | None

    def to_dict(self) -> dict[str, Any]:
        live = self.state in LIVE_STATES
        return {
            "id": self.id,
            "service_id": self.service_id,
            "allocation_id": self.allocation_id,
            "command": self.command,
            "working_directory": self.working_directory,
            "pid": self.pid,
            "state": self.state,
            "exit_code": self.exit_code,
            "log_path": self.log_path,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "alive": _pid_alive(self.pid) if live else False,
        }


def _row_process(row: Any) -> ManagedProcess:
    return ManagedProcess(
        id=row["id"],
        service_id=row["service_id"],
        allocation_id=row["allocation_id"],
        command=row["command"],
        working_directory=row["working_directory"],
        pid=row["pid"],
        state=row["state"],
        exit_code=row["exit_code"],
        log_path=row["log_path"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        stopped_at=row["stopped_at"],
    )


class ProcessManager:
    def __init__(self, repo: Repository, config: Config) -> None:
        self.repo = repo
        self.config = config

    def _require_enabled(self) -> None:
        if not self.config.process_management_enabled:
            raise AprError(
                ErrorCode.PROCESS_MANAGEMENT_DISABLED,
                "Process management is disabled. Set process_management.enabled: true "
                "in config.yaml (or APR_PROCESS_MANAGEMENT=1) and restart the registry.",
            )

    def get_live(self, service_id: str) -> ManagedProcess | None:
        row = self.repo.db.fetchone(
            """
            SELECT * FROM managed_processes
            WHERE service_id = ? AND state IN ('starting', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (service_id,),
        )
        return _row_process(row) if row else None

    def get_latest(self, service_id: str) -> ManagedProcess | None:
        row = self.repo.db.fetchone(
            """
            SELECT * FROM managed_processes
            WHERE service_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (service_id,),
        )
        return _row_process(row) if row else None

    def reconcile(self, service_id: str) -> ManagedProcess | None:
        """If a 'live' row's pid is gone/zombie, mark it exited and free the slot."""
        live = self.get_live(service_id)
        if live is None:
            return None
        if _pid_alive(live.pid):
            return live
        exit_code = self._try_wait_exit(live.pid)
        self._mark(
            live.id,
            state="exited",
            exit_code=exit_code,
            last_error="process no longer running (reconciled on access)",
            stopped=True,
        )
        return None

    def _try_wait_exit(self, pid: int | None) -> int | None:
        if pid is None:
            return None
        code = _try_reap(pid)
        if code is not None:
            return code
        # Not our child or already reaped — no exit code available.
        return None

    def _mark(
        self,
        process_id: str,
        *,
        state: str | None = None,
        pid: int | None = None,
        exit_code: int | None = None,
        last_error: str | None = None,
        log_path: str | None = None,
        started: bool = False,
        stopped: bool = False,
    ) -> ManagedProcess:
        fields: dict[str, Any] = {}
        if state is not None:
            fields["state"] = state
        if pid is not None:
            fields["pid"] = pid
        if exit_code is not None:
            fields["exit_code"] = exit_code
        if last_error is not None:
            fields["last_error"] = last_error
        if log_path is not None:
            fields["log_path"] = log_path
        if started:
            fields["started_at"] = _utcnow()
        if stopped:
            fields["stopped_at"] = _utcnow()
        if not fields:
            row = self.repo.db.fetchone(
                "SELECT * FROM managed_processes WHERE id = ?", (process_id,)
            )
            assert row is not None
            return _row_process(row)
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.repo.db.execute(
            f"UPDATE managed_processes SET {sets} WHERE id = ?",
            (*fields.values(), process_id),
        )
        row = self.repo.db.fetchone(
            "SELECT * FROM managed_processes WHERE id = ?", (process_id,)
        )
        assert row is not None
        return _row_process(row)

    def _spawn(self, command: str, *, cwd: str | None, log_f: Any) -> subprocess.Popen:
        """Spawn *command* under the user shell when configured."""
        use_user_shell = getattr(self.config, "process_user_shell_env", True)
        if use_user_shell:
            shell = resolve_user_shell()
            # -l: login (profile / .zprofile), -i: interactive (.zshrc) so PATH
            # matches a normal terminal. argv form — never go through /bin/sh -c.
            # TERM=dumb: .zshrc often calls tput/zle; without a TTY that only
            # pollutes the service log.
            child_env = os.environ.copy()
            child_env.setdefault("TERM", "dumb")
            log_f.write(f"--- shell: {shell} -lic ---\n")
            log_f.flush()
            return subprocess.Popen(
                [shell, "-lic", command],
                cwd=cwd,
                env=child_env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        # Optional non-login-shell mode for tightly controlled daemon environments.
        return subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    def start(self, service_id: str) -> ManagedProcess:
        self._require_enabled()
        svc = self.repo.get_service(service_id)
        if svc is None:
            raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")
        if not svc.start_command or not str(svc.start_command).strip():
            raise AprError(
                ErrorCode.NO_START_COMMAND,
                f"Service {service_id} has no start_command; set one before starting.",
            )

        # Reconcile orphans from a previous daemon lifetime / immediate crash.
        existing = self.reconcile(service_id)
        if existing is not None:
            raise AprError(
                ErrorCode.PROCESS_ALREADY_RUNNING,
                f"Service already has a managed process (pid={existing.pid}, "
                f"id={existing.id}). Stop it first.",
            )

        ports = port_map_for_service(self.repo, service_id)
        command = render_command(str(svc.start_command).strip(), ports)
        cwd = svc.working_directory
        if cwd:
            cwd_path = Path(cwd).expanduser()
            if not cwd_path.is_dir():
                raise AprError(
                    ErrorCode.INVALID_REQUEST,
                    f"working_directory does not exist: {cwd_path}",
                )
            cwd = str(cwd_path)
        else:
            cwd = None

        log_dir = Path(self.config.state_dir) / "logs"
        log_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        log_path = log_dir / f"{service_id}.log"

        now = _utcnow()
        process_id = new_process_id()
        # Prefer the first reserved allocation as a soft link for UI context.
        allocation_id = None
        for alloc in self.repo.list_allocations_for_service(service_id):
            if alloc.state == AllocationState.RESERVED:
                allocation_id = alloc.id
                break

        self.repo.db.execute(
            """
            INSERT INTO managed_processes (
                id, service_id, allocation_id, command, working_directory,
                pid, state, exit_code, log_path, last_error,
                created_at, started_at, stopped_at
            ) VALUES (?, ?, ?, ?, ?, NULL, 'starting', NULL, ?, NULL, ?, NULL, NULL)
            """,
            (
                process_id,
                service_id,
                allocation_id,
                command,
                cwd,
                str(log_path),
                now,
            ),
        )

        try:
            # Append mode so restarts keep history; line-buffered for near-live tail.
            log_f = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            log_f.write(f"\n--- apr start {now} pid pending ---\n$ {command}\n")
            log_f.flush()

            proc = self._spawn(command, cwd=cwd, log_f=log_f)
            log_f.write(f"--- spawned pid={proc.pid} ---\n")
            log_f.flush()
        except OSError as exc:
            self._mark(
                process_id,
                state="failed",
                last_error=str(exc),
                stopped=True,
            )
            raise AprError(
                ErrorCode.PROCESS_START_FAILED,
                f"Failed to spawn process: {exc}",
            ) from exc

        # Catch immediate exits (command not found, one-shot scripts, …) so the
        # UI never shows a zombie / dead pid as "running".
        exit_code = self._wait_startup(proc)
        if exit_code is not None:
            if exit_code == 0:
                # Short-lived success (e.g. one-shot scripts): not an error,
                # but free the live slot so another start can happen.
                return self._mark(
                    process_id,
                    state="exited",
                    pid=proc.pid,
                    exit_code=0,
                    started=True,
                    stopped=True,
                )
            self._mark(
                process_id,
                state="failed",
                pid=proc.pid,
                exit_code=exit_code,
                last_error=f"process exited immediately with code {exit_code}",
                started=True,
                stopped=True,
            )
            raise AprError(
                ErrorCode.PROCESS_START_FAILED,
                f"start_command exited immediately (code={exit_code}); "
                f"see log {log_path}",
            )

        return self._mark(
            process_id,
            state="running",
            pid=proc.pid,
            started=True,
        )

    def _wait_startup(self, proc: subprocess.Popen) -> int | None:
        """Return exit code if the process dies within the startup probe window."""
        deadline = time.monotonic() + _STARTUP_PROBE_SECONDS
        while time.monotonic() < deadline:
            code = proc.poll()
            if code is not None:
                return int(code)
            time.sleep(0.05)
        # One last check — still running is success for this probe.
        code = proc.poll()
        return int(code) if code is not None else None

    def stop(self, service_id: str) -> ManagedProcess:
        self._require_enabled()
        svc = self.repo.get_service(service_id)
        if svc is None:
            raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")

        live = self.reconcile(service_id)
        if live is None or live.pid is None:
            raise AprError(
                ErrorCode.PROCESS_NOT_RUNNING,
                f"No running managed process for service {service_id}",
            )

        timeout = max(1, int(self.config.process_stop_timeout_seconds))
        pid = live.pid
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return self._mark(
                live.id,
                state="exited",
                exit_code=self._try_wait_exit(pid),
                last_error="process already gone when stop requested",
                stopped=True,
            )
        except PermissionError as exc:
            self._mark(live.id, last_error=f"SIGTERM failed: {exc}")
            raise AprError(
                ErrorCode.INTERNAL_ERROR,
                f"Cannot signal process group {pid}: {exc}",
            ) from exc

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return self._mark(
                    live.id,
                    state="stopped",
                    exit_code=self._try_wait_exit(pid),
                    stopped=True,
                )
            time.sleep(0.05)

        # Still alive → escalate.
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            self._mark(live.id, last_error=f"SIGKILL failed: {exc}")
            raise AprError(
                ErrorCode.INTERNAL_ERROR,
                f"Cannot SIGKILL process group {pid}: {exc}",
            ) from exc

        # Brief grace for the kernel to reap.
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.05)

        return self._mark(
            live.id,
            state="stopped",
            exit_code=self._try_wait_exit(pid),
            last_error=f"SIGKILL after {timeout}s SIGTERM timeout",
            stopped=True,
        )

    def logs(self, service_id: str, *, tail: int = 200) -> dict[str, Any]:
        """Return the last ``tail`` lines of the service log file."""
        if tail < 1:
            raise AprError(ErrorCode.INVALID_REQUEST, "tail must be >= 1")
        if tail > 10_000:
            raise AprError(ErrorCode.INVALID_REQUEST, "tail must be <= 10000")

        svc = self.repo.get_service(service_id)
        if svc is None:
            raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")

        # Reconcile so a dead "running" row is not still advertised in the payload.
        self.reconcile(service_id)
        proc = self.get_live(service_id) or self.get_latest(service_id)
        if proc and proc.log_path:
            path = Path(proc.log_path)
        else:
            path = Path(self.config.state_dir) / "logs" / f"{service_id}.log"

        if not path.is_file():
            return {
                "service_id": service_id,
                "log_path": str(path),
                "tail": tail,
                "lines": [],
                "process": proc.to_dict() if proc else None,
            }

        lines = _tail_file(path, tail)
        return {
            "service_id": service_id,
            "log_path": str(path),
            "tail": tail,
            "lines": lines,
            "process": proc.to_dict() if proc else None,
        }


def _tail_file(path: Path, n: int) -> list[str]:
    """Efficient-ish tail for small log files (typical APR use)."""
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not data:
        return []
    # Keep trailing empty line behaviour predictable: splitlines drops final ''
    # only when the file ends with \n; that's fine for display.
    parts = data.splitlines()
    return parts[-n:]
