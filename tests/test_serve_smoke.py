"""Integration smoke: serve daemon + status against isolated data dir."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from apr.config import load_config
from apr.cli.client import health_check, is_registry_up


def test_serve_daemon_and_healthz(tmp_path: Path) -> None:
    data_dir = tmp_path / "apr"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apr",
            "--data-dir",
            str(data_dir),
            "serve",
            "--daemon",
            # Isolate from ~/.config/apr/config.yaml web.enabled (live registry
            # may already own 127.0.0.1:17989).
            "--no-web",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Parent exits after double-fork; wait briefly for socket.
    proc.wait(timeout=5)

    cfg = load_config(data_dir=data_dir)
    cfg.state_dir = data_dir / "state"
    cfg.pid_path = cfg.state_dir / "apr.pid"
    cfg.log_path = cfg.state_dir / "apr.log"

    deadline = time.monotonic() + 3.0
    up = False
    while time.monotonic() < deadline:
        if is_registry_up(cfg):
            up = True
            break
        time.sleep(0.05)

    try:
        assert up, f"registry did not come up; log={cfg.log_path.read_text() if cfg.log_path.exists() else None}"
        health = health_check(cfg)
        assert health is not None
        assert health["status"] == "ok"

        transport = httpx.HTTPTransport(uds=str(cfg.socket_path))
        with httpx.Client(transport=transport, base_url="http://apr", timeout=2.0) as client:
            resp = client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json()["service"] == "apr"
    finally:
        if cfg.pid_path.exists():
            pid = int(cfg.pid_path.read_text().strip())
            try:
                import os
                import signal

                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
