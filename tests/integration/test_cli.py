"""CLI integration tests against a live daemon."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "apr", *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def daemon(tmp_path: Path):
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
            # Don't inherit live config's web.enabled (port 17989 may be taken).
            "--no-web",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait(timeout=5)
    # wait for up
    for _ in range(60):
        st = _run(["--data-dir", str(data_dir), "status", "--json"])
        if st.returncode == 0:
            break
        time.sleep(0.05)
    else:
        log = data_dir / "state" / "apr.log"
        raise RuntimeError(f"daemon failed: {log.read_text() if log.exists() else 'no log'}")

    yield data_dir

    pid_path = data_dir / "state" / "apr.pid"
    if pid_path.exists():
        import os
        import signal

        try:
            os.kill(int(pid_path.read_text().strip()), signal.SIGTERM)
        except OSError:
            pass


def test_cli_ensure_json_stdin(daemon: Path) -> None:
    body = {
        "agent": {"type": "codex"},
        "service": {
            "key": "model-api",
            "instance": "main",
            "project_id": "p1",
            "name": "Model API",
            "description": "test",
        },
        "resources": [{"name": "http", "type": "single"}],
    }
    r = _run(
        ["--data-dir", str(daemon), "ensure", "--json", "-"],
        input_text=json.dumps(body),
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "ports" in data and "http" in data["ports"]
    port = data["ports"]["http"]
    alloc_id = data["allocation_id"]

    # idempotent
    r2 = _run(
        ["--data-dir", str(daemon), "ensure", "--json", "-"],
        input_text=json.dumps(body),
    )
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["ports"]["http"] == port
    assert json.loads(r2.stdout)["existing"] is True

    # list
    r3 = _run(["--data-dir", str(daemon), "list", "--json"])
    assert r3.returncode == 0
    assert len(json.loads(r3.stdout)["services"]) >= 1

    # inspect-port
    r4 = _run(["--data-dir", str(daemon), "inspect-port", str(port)])
    assert r4.returncode == 0
    assert json.loads(r4.stdout)["service"]["service_key"] == "model-api"

    # release
    r5 = _run(["--data-dir", str(daemon), "release", alloc_id, "--yes", "--reason", "done"])
    assert r5.returncode == 0
    assert json.loads(r5.stdout)["state"] == "released"


def test_cli_ensure_flags(daemon: Path) -> None:
    r = _run(
        [
            "--data-dir",
            str(daemon),
            "ensure",
            "--service",
            "frontend",
            "--instance",
            "dev",
            "--name",
            "Frontend Dev",
            "--ports",
            "http,hmr",
            "--agent",
            "grok-build",
            "--auto-start",
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert set(data["ports"]) == {"http", "hmr"}

    listed = _run(["--data-dir", str(daemon), "list", "--json"])
    service = next(
        item
        for item in json.loads(listed.stdout)["services"]
        if item["service_key"] == "frontend"
    )
    assert service["auto_start"] is True
