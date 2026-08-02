"""Starlette application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from apr import __version__
from apr.api.errors import apr_error_handler, unhandled_error_handler
from apr.api.routes import api_routes
from apr.domain.errors import AprError
from apr.webui import webui_routes


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "apr",
            "version": __version__,
        }
    )


def create_app(*, state: dict[str, Any] | None = None) -> Starlette:
    """Create the APR Registry ASGI app."""
    apr_state: dict[str, Any] = dict(state or {})

    # Lazily init store if db_path provided and repo not set.
    if "repo" not in apr_state and apr_state.get("db_path"):
        from apr.store.db import Database
        from apr.store.repository import Repository
        from apr.service.ensure import EnsureService

        db = Database(apr_state["db_path"])
        repo = Repository(db)
        apr_state["db"] = db
        apr_state["repo"] = repo
        apr_state["ensure"] = EnsureService(repo, config=apr_state.get("config"))

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        cfg = apr_state.get("config")
        if cfg is not None and getattr(cfg, "use_unix_socket", False):
            sock = Path(cfg.socket_path)
            if sock.exists():
                try:
                    os.chmod(sock, 0o600)
                except OSError:
                    pass
        yield
        db = apr_state.get("db")
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        *api_routes(),
        # Catch-all for the SPA: must stay last so it never shadows the API.
        *webui_routes(),
    ]
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={
            AprError: apr_error_handler,
            Exception: unhandled_error_handler,
        },
    )
    app.state.apr = apr_state
    return app
