"""Port forwards API — autossh, heavily mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from apr.api.app import create_app
from apr.allocator.pool import PortPool
from apr.config import default_config
from apr.service.ensure import EnsureService
from apr.store.db import Database
from apr.store.repository import Repository


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    pool = PortPool(start=33000, end=33050, excluded=set())
    ensure = EnsureService(repo, port_pool=pool)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    cfg.state_dir = tmp_path / "state"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.use_unix_socket = False
    cfg.port_pool.start = 33000
    cfg.port_pool.end = 33050
    app = create_app(
        state={
            "config": cfg,
            "db": db,
            "repo": repo,
            "ensure": ensure,
            "db_path": str(db_path),
        }
    )
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path):
    with _client(tmp_path) as c:
        yield c


def _add_node(client: TestClient) -> str:
    r = client.post(
        "/v1/nodes",
        json={"name": "fwd-box", "ssh_host": "127.0.0.1", "ssh_user": "tiou"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_create_and_stop_forward(client: TestClient) -> None:
    nid = _add_node(client)

    fake_proc = MagicMock()
    fake_proc.pid = 424242
    fake_proc.stderr = None

    # pick_local_port sees empty listeners; post-spawn probe sees 33040 bound.
    probe_calls: list[dict] = []

    def _probe() -> dict[int, MagicMock]:
        if not probe_calls:
            probe_calls.append({})
            return {}
        return {33040: MagicMock(port=33040)}

    with (
        patch("apr.service.forwards.shutil.which", return_value="/usr/bin/autossh"),
        patch("apr.service.forwards.subprocess.Popen", return_value=fake_proc) as popen,
        patch("apr.service.forwards._pid_alive", return_value=True),
        patch("apr.service.forwards.probe_listeners", side_effect=_probe),
        patch("apr.service.forwards.time.sleep"),
    ):
        r = client.post(
            f"/v1/nodes/{nid}/forwards",
            json={
                "remote_port": 20010,
                "local_port": 33040,
                "label": "remote-api http",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["remote_port"] == 20010
        assert body["local_port"] == 33040
        assert body["state"] == "active"
        assert body["pid"] == 424242
        assert "127.0.0.1" in body["local_url"]
        fwd_id = body["id"]

        argv = popen.call_args[0][0]
        assert argv[0] == "autossh"
        assert "-M" in argv and "0" in argv
        assert "-N" in argv
        assert "33040:127.0.0.1:20010" in argv
        # ssh_config_managed is the default: preserve the alias and let
        # ~/.ssh/config own user/port/identity/route switching.
        assert argv[-1] == "127.0.0.1"

    with patch("apr.service.forwards._pid_alive", return_value=False), patch(
        "apr.service.forwards.os.kill"
    ):
        r = client.delete(f"/v1/forwards/{fwd_id}")
        assert r.status_code == 200
        assert r.json()["state"] == "stopped"

    r = client.get("/v1/forwards")
    assert r.status_code == 200
    assert len(r.json()["forwards"]) == 1


def test_forward_requires_autossh(client: TestClient) -> None:
    nid = _add_node(client)
    with patch("apr.service.forwards.shutil.which", return_value=None):
        r = client.post(
            f"/v1/nodes/{nid}/forwards",
            json={"remote_port": 8080},
        )
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "FORWARD_START_FAILED"
