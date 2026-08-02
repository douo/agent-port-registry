"""SSH helpers for node control plane (list/start/stop) — no local shell."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence

from apr.domain.errors import AprError, ErrorCode

# Hostnames / IPs / user / path fragments safe for argv (not shell).
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PATH_RE = re.compile(r"^[A-Za-z0-9._/+\-@~]+$")
# apr_command is split with shlex; forbid newlines and shell metacharacters abuse.
_CMD_FORBIDDEN = re.compile(r"[\n\r;&|`$<>]")


@dataclass(frozen=True, slots=True)
class SshTarget:
    host: str
    user: str | None = None
    port: int | None = None
    identity_file: str | None = None
    connect_timeout: int = 10


def validate_ssh_host(host: str) -> str:
    host = host.strip()
    if not host or not _HOST_RE.match(host):
        raise AprError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid ssh_host (hostname/IP only): {host!r}",
        )
    return host


def validate_ssh_user(user: str | None) -> str | None:
    if user is None or user == "":
        return None
    user = user.strip()
    if not _USER_RE.match(user):
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid ssh_user: {user!r}")
    return user


def validate_ssh_port(port: int | None) -> int | None:
    if port is None:
        return None
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid ssh_port: {port}")
    return port


def validate_identity_file(path: str | None) -> str | None:
    if path is None or path == "":
        return None
    path = path.strip()
    # Expand ~ for personal convenience (ssh -i does not).
    if path.startswith("~"):
        from pathlib import Path

        path = str(Path(path).expanduser())
    if not _PATH_RE.match(path):
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid identity_file: {path!r}")
    return path


def validate_apr_command(cmd: str) -> str:
    cmd = (cmd or "svcctl").strip()
    if not cmd or _CMD_FORBIDDEN.search(cmd):
        raise AprError(
            ErrorCode.INVALID_REQUEST,
            "apr_command must be a simple command (no shell metacharacters)",
        )
    if len(cmd) > 512:
        raise AprError(ErrorCode.INVALID_REQUEST, "apr_command too long")
    # Must be parseable into argv tokens.
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"apr_command parse error: {exc}") from exc
    if not parts:
        raise AprError(ErrorCode.INVALID_REQUEST, "apr_command is empty")
    return cmd


def split_apr_command(cmd: str) -> list[str]:
    return shlex.split(validate_apr_command(cmd))


def build_ssh_argv(target: SshTarget, remote_argv: Sequence[str]) -> list[str]:
    """Build ``ssh [opts] [user@]host -- remote argv…`` (no local shell)."""
    if not remote_argv:
        raise AprError(ErrorCode.INVALID_REQUEST, "remote command is empty")
    host = validate_ssh_host(target.host)
    user = validate_ssh_user(target.user)
    port = validate_ssh_port(target.port)
    identity = validate_identity_file(target.identity_file)

    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={max(1, int(target.connect_timeout))}",
    ]
    if port is not None:
        argv.extend(["-p", str(port)])
    if identity is not None:
        argv.extend(["-i", identity])
    dest = f"{user}@{host}" if user else host
    argv.append(dest)
    argv.append("--")
    argv.extend(remote_argv)
    return argv


def run_ssh(
    target: SshTarget,
    remote_argv: Sequence[str],
    *,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("ssh") is None:
        raise AprError(ErrorCode.NODE_SSH_FAILED, "ssh binary not found on PATH")
    argv = build_ssh_argv(target, remote_argv)
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AprError(
            ErrorCode.NODE_SSH_FAILED,
            f"SSH timed out after {timeout}s to {target.host}",
        ) from exc
    except OSError as exc:
        raise AprError(ErrorCode.NODE_SSH_FAILED, f"SSH failed to start: {exc}") from exc


def ssh_json(
    target: SshTarget,
    remote_argv: Sequence[str],
    *,
    timeout: float = 30.0,
) -> tuple[int, str, str]:
    """Run remote command; return (returncode, stdout, stderr)."""
    proc = run_ssh(target, remote_argv, timeout=timeout)
    return proc.returncode, proc.stdout or "", proc.stderr or ""
