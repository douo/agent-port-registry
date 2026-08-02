"""Probe local TCP listeners (Linux)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ListenerInfo:
    port: int
    pid: int | None = None
    command: str | None = None
    inode: int | None = None


_HEX_IP_PORT = re.compile(r"^([0-9A-Fa-f]+):([0-9A-Fa-f]+)$")


def _parse_proc_net_tcp(path: Path) -> list[tuple[int, int]]:
    """Return list of (port, inode) for listening sockets.

    TCP listen state is 0A (TCP_LISTEN).
    """
    if not path.is_file():
        return []
    results: list[tuple[int, int]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if not lines:
        return []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 10:
            continue
        # local_address, state, inode
        local = parts[1]
        state = parts[3]
        inode_s = parts[9]
        if state.upper() != "0A":
            continue
        m = _HEX_IP_PORT.match(local)
        if not m:
            continue
        port = int(m.group(2), 16)
        try:
            inode = int(inode_s)
        except ValueError:
            inode = -1
        results.append((port, inode))
    return results


def _build_inode_to_pid() -> dict[int, int]:
    """Map socket inode -> pid by scanning /proc/*/fd."""
    mapping: dict[int, int] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return mapping
    socket_re = re.compile(r"^socket:\[(\d+)\]$")
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return mapping
    for pdir in pids:
        fd_dir = pdir / "fd"
        try:
            pid = int(pdir.name)
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                m = socket_re.match(target)
                if m:
                    mapping[int(m.group(1))] = pid
        except OSError:
            continue
    return mapping


def _cmdline(pid: int) -> str | None:
    path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]
    return " ".join(parts) if parts else None


def probe_listeners(
    *,
    proc_net_paths: Iterable[Path] | None = None,
    resolve_pid: bool = True,
) -> dict[int, ListenerInfo]:
    """Return map port -> ListenerInfo for currently listening TCP ports.

    Note: multiple processes may share a port with SO_REUSEPORT; we keep one.
    """
    paths = list(proc_net_paths) if proc_net_paths is not None else [
        Path("/proc/net/tcp"),
        Path("/proc/net/tcp6"),
    ]
    port_inodes: dict[int, int] = {}
    for path in paths:
        for port, inode in _parse_proc_net_tcp(path):
            # Prefer first seen
            port_inodes.setdefault(port, inode)

    inode_to_pid: dict[int, int] = {}
    if resolve_pid and port_inodes:
        inode_to_pid = _build_inode_to_pid()

    out: dict[int, ListenerInfo] = {}
    for port, inode in port_inodes.items():
        pid = inode_to_pid.get(inode) if inode >= 0 else None
        cmd = _cmdline(pid) if pid is not None else None
        out[port] = ListenerInfo(port=port, pid=pid, command=cmd, inode=inode)
    return out


def listening_ports(**kwargs) -> set[int]:
    return set(probe_listeners(**kwargs).keys())


def availability_for_ports(
    ports: Iterable[int],
    listeners: dict[int, ListenerInfo] | None = None,
) -> dict[int, dict]:
    """Build availability map for named response fields."""
    if listeners is None:
        listeners = probe_listeners()
    result: dict[int, dict] = {}
    for port in ports:
        info = listeners.get(port)
        if info is None:
            result[port] = {"state": "free"}
        else:
            entry: dict = {"state": "occupied"}
            if info.pid is not None:
                entry["pid"] = info.pid
            if info.command:
                entry["command"] = info.command
            result[port] = entry
    return result
