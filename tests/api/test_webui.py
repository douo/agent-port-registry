"""Web UI hosting: SPA fallback must not swallow API routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apr import webui
from apr.api.app import create_app
from apr.config import default_config
from apr.store.db import Database
from apr.store.repository import Repository

built_only = pytest.mark.skipif(
    not webui.is_built(),
    reason="UI bundle not built (cd web && npm run build)",
)


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "apr.db"
    db = Database(db_path)
    repo = Repository(db)
    cfg = default_config()
    cfg.data_dir = tmp_path
    cfg.db_path = db_path
    app = create_app(
        state={"config": cfg, "db": db, "repo": repo, "db_path": str(db_path)}
    )
    with TestClient(app) as c:
        yield c


@built_only
def test_index_is_served(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


@built_only
def test_client_side_route_falls_back_to_index(client: TestClient) -> None:
    # A hard refresh on a React Router path has no file behind it.
    resp = client.get("/services/SVC_DOES_NOT_EXIST")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


@built_only
def test_unknown_api_path_stays_json_404(client: TestClient) -> None:
    """The catch-all must never answer 200 text/html for a /v1 typo."""
    resp = client.get("/v1/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["error"]["code"]


@built_only
def test_api_routes_still_win_over_static(client: TestClient) -> None:
    assert client.get("/healthz").json()["service"] == "apr"
    assert client.get("/v1/services").json() == {"services": []}
    assert client.get("/v1/overview").json()["services"]["total"] == 0


def test_routes_absent_without_a_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source checkout with no built UI still serves the API."""
    monkeypatch.setattr(webui, "INDEX_FILE", Path("/nonexistent/index.html"))
    assert webui.is_built() is False
    assert webui.webui_routes() == []
