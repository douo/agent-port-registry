"""Listener probe tests with synthetic /proc/net/tcp."""

from __future__ import annotations

from pathlib import Path

from apr.listener.probe import _parse_proc_net_tcp, probe_listeners


def test_parse_proc_net_tcp_listen(tmp_path: Path) -> None:
    # Minimal /proc/net/tcp style content.
    # local 0.0.0.0:4E20 (20000), state 0A, inode 12345
    content = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:4E20 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0
   1: 0100007F:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 99999 1 0000000000000000 100 0 0 10 0
   2: 00000000:1F90 00000000:0000 01 00000000:00000000 00:00000000 00000000     0        0 11111 1 0000000000000000 100 0 0 10 0
"""
    path = tmp_path / "tcp"
    path.write_text(content)
    parsed = _parse_proc_net_tcp(path)
    ports = {p for p, _ in parsed}
    assert 20000 in ports  # 0x4E20
    assert 80 in ports  # 0x0050
    # state 01 is ESTABLISHED — not included
    assert 8080 not in ports  # 0x1F90 would be 8080 but state 01


def test_probe_listeners_from_files(tmp_path: Path) -> None:
    content = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:4E21 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 42 1 0000000000000000 100 0 0 10 0
"""
    path = tmp_path / "tcp"
    path.write_text(content)
    listeners = probe_listeners(proc_net_paths=[path], resolve_pid=False)
    assert 20001 in listeners
    assert listeners[20001].inode == 42
    assert listeners[20001].pid is None
