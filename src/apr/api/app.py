"""Starlette application factory."""

from __future__ import annotations

import asyncio
import logging
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

_log = logging.getLogger("apr.runtime")


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "apr",
            "version": __version__,
        }
    )


async def _node_refresh_loop(apr_state: dict[str, Any]) -> None:
    """Periodically refresh enabled SSH nodes."""
    # Stagger first tick so serve startup stays snappy.
    await asyncio.sleep(5)
    while True:
        try:
            repo = apr_state.get("repo")
            if repo is not None:
                from apr.service.nodes import NodeManager

                nm = apr_state.get("node_manager")
                if nm is None:
                    nm = NodeManager(repo)
                    apr_state["node_manager"] = nm
                # Refresh runs in a worker thread — SSH is blocking.
                await asyncio.to_thread(nm.refresh_enabled)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("background node refresh failed")
        await asyncio.sleep(30)


def _forward_manager(apr_state: dict[str, Any]) -> Any | None:
    """Build the master-local forward manager without touching remote services."""
    repo = apr_state.get("repo")
    cfg = apr_state.get("config")
    if repo is None or cfg is None:
        return None

    from apr.service.forwards import ForwardManager
    from apr.service.nodes import NodeManager

    nm = apr_state.get("node_manager")
    if nm is None:
        nm = NodeManager(repo)
        apr_state["node_manager"] = nm
    fm = apr_state.get("forward_manager")
    if fm is None:
        fm = ForwardManager(repo, cfg, nm)
        apr_state["forward_manager"] = fm
    return fm


def _forward_operation_lock(apr_state: dict[str, Any]) -> asyncio.Lock:
    lock = apr_state.get("forward_operation_lock")
    if lock is None:
        lock = asyncio.Lock()
        apr_state["forward_operation_lock"] = lock
    return lock


async def _maintain_forward_rules(apr_state: dict[str, Any]) -> None:
    fm = _forward_manager(apr_state)
    if fm is None:
        return
    async with _forward_operation_lock(apr_state):
        results = await asyncio.to_thread(fm.maintain_rules)
    apr_state["forward_maintenance_results"] = results
    for result in results:
        if result["status"] == "failed":
            _log.warning("forward maintenance: %s", result)


async def _restore_forward_rules(apr_state: dict[str, Any]) -> None:
    fm = _forward_manager(apr_state)
    if fm is None:
        return
    async with _forward_operation_lock(apr_state):
        results = await asyncio.to_thread(fm.restore_startup_rules)
    apr_state["forward_startup_results"] = results
    for result in results:
        log = _log.warning if result["status"] == "failed" else _log.info
        log("forward startup: %s", result)


async def _forward_maintenance_loop(apr_state: dict[str, Any]) -> None:
    """Supervise current forwarding rules independently of node snapshots."""

    while True:
        await asyncio.sleep(30)
        try:
            await _maintain_forward_rules(apr_state)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("forward maintenance pass failed")


async def _auto_start_services(apr_state: dict[str, Any]) -> None:
    """Run the one-shot local service auto-start pass during APR startup."""
    repo = apr_state.get("repo")
    cfg = apr_state.get("config")
    if repo is None or cfg is None:
        return

    from apr.service.process import ProcessManager

    manager = apr_state.get("process_manager")
    if manager is None:
        manager = ProcessManager(repo, cfg)
        apr_state["process_manager"] = manager
    try:
        results = await asyncio.to_thread(manager.auto_start_configured)
    except Exception:
        _log.exception("service auto-start pass failed")
        return

    apr_state["auto_start_results"] = results
    for result in results:
        log = _log.info if result["status"] in {"started", "skipped"} else _log.error
        log("service auto-start: %s", result)


async def _auto_start_once(apr_state: dict[str, Any]) -> None:
    """Share one auto-start pass across UDS and TCP server lifespans."""
    task = apr_state.get("auto_start_task")
    if task is None:
        task = asyncio.create_task(
            _auto_start_services(apr_state), name="apr-service-auto-start"
        )
        apr_state["auto_start_task"] = task
    await asyncio.shield(task)


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
        await _auto_start_once(apr_state)
        try:
            await _restore_forward_rules(apr_state)
        except Exception:
            _log.exception("forward startup pass failed")
        refresh_task = asyncio.create_task(
            _node_refresh_loop(apr_state), name="apr-node-refresh"
        )
        forward_task = asyncio.create_task(
            _forward_maintenance_loop(apr_state), name="apr-forward-maintenance"
        )
        try:
            yield
        finally:
            refresh_task.cancel()
            forward_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
            try:
                await forward_task
            except asyncio.CancelledError:
                pass
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
