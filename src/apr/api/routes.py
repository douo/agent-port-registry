"""HTTP routes for APR Registry (PRD §10)."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

_T = TypeVar("_T")

from apr import __version__
from apr.domain.errors import AprError, ErrorCode
from apr.domain.identity import ServiceIdentity, require_local_device_id
from apr.domain.models import (
    AllocationState,
    DeleteRequest,
    EnsureRequest,
    ReleaseRequest,
    ServiceCreateRequest,
    ServiceUpdateRequest,
)
from apr.listener.probe import probe_listeners
from apr.service.ensure import EnsureService, check_allocation_ports
from apr.service.forwards import ForwardManager
from apr.service.nodes import NodeManager
from apr.service.process import ProcessManager


def _state(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "apr", {}) or {}


def _repo(request: Request):
    repo = _state(request).get("repo")
    if repo is None:
        raise AprError(ErrorCode.INTERNAL_ERROR, "Repository not initialized")
    return repo


def _config(request: Request):
    return _state(request).get("config")


def _ensure_svc(request: Request) -> EnsureService:
    svc = _state(request).get("ensure")
    if svc is None:
        cfg = _config(request)
        svc = EnsureService(_repo(request), config=cfg)
        _state(request)["ensure"] = svc
    return svc


def _process_mgr(request: Request) -> ProcessManager:
    mgr = _state(request).get("process_manager")
    if mgr is None:
        cfg = _config(request)
        if cfg is None:
            from apr.config import default_config

            cfg = default_config()
        mgr = ProcessManager(_repo(request), cfg)
        _state(request)["process_manager"] = mgr
    return mgr


def _node_mgr(request: Request) -> NodeManager:
    mgr = _state(request).get("node_manager")
    if mgr is None:
        mgr = NodeManager(_repo(request))
        _state(request)["node_manager"] = mgr
    return mgr


def _forward_mgr(request: Request) -> ForwardManager:
    mgr = _state(request).get("forward_manager")
    if mgr is None:
        cfg = _config(request)
        if cfg is None:
            from apr.config import default_config

            cfg = default_config()
        mgr = ForwardManager(_repo(request), cfg, _node_mgr(request))
        _state(request)["forward_manager"] = mgr
    return mgr


async def _to_thread(fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """Run blocking work off the event loop.

    Critical for SSH control plane: a sync ``ssh … svcctl list`` against the
    *same* APR process would otherwise deadlock the single-threaded loop.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


async def ensure_allocation(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid JSON body: {exc}") from exc
    try:
        req = EnsureRequest.model_validate(body)
    except ValidationError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    result = _ensure_svc(request).ensure(req)
    return JSONResponse(result.model_dump(mode="json"), status_code=200)


def _service_detail(repo, svc, *, process_manager: ProcessManager | None = None) -> dict[str, Any]:
    allocs = repo.list_allocations_for_service(svc.id)
    process = None
    if process_manager is not None:
        # Reconcile orphans so the UI never shows a zombie "running" badge.
        live = process_manager.reconcile(svc.id)
        latest = live or process_manager.get_latest(svc.id)
        if latest is not None:
            process = latest.to_dict()
    return {
        **svc.model_dump(mode="json"),
        "allocations": [
            {
                "id": a.id,
                "allocation_name": a.allocation_name,
                "state": a.state.value,
                "sticky": a.sticky,
                "created_at": a.created_at,
                "released_at": a.released_at,
                "release_reason": a.release_reason,
                "request_spec": (
                    json.loads(a.request_spec_json) if a.request_spec_json else None
                ),
                "ports": [
                    {
                        "resource_name": p.resource_name,
                        "port_name": p.port_name,
                        "port": p.port,
                        "transport": p.transport,
                        "ordinal": p.ordinal,
                    }
                    for p in a.ports
                ],
            }
            for a in allocs
        ],
        "process": process,
    }


async def create_service(request: Request) -> JSONResponse:
    """Create a service index entry without allocating ports (C in CRUD)."""
    repo = _repo(request)
    try:
        body = await request.json()
        req = ServiceCreateRequest.model_validate(body)
    except ValidationError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid JSON: {exc}") from exc

    agent = req.agent
    identity = ServiceIdentity.from_raw(
        device_id=require_local_device_id(req.device_id),
        project_id=req.service.project_id,
        service_key=req.service.key,
        instance=req.service.instance,
    )
    existing = repo.find_service_by_identity(identity)
    if existing is not None:
        raise AprError(
            ErrorCode.SERVICE_IDENTITY_CONFLICT,
            f"Service already exists: {existing.id} ({identity.display_key()})",
        )
    svc = repo.create_service(
        identity,
        name=req.service.name or req.service.key,
        description=req.service.description,
        code_path=req.service.code_path,
        working_directory=req.service.working_directory,
        start_command=req.service.start_command,
        stop_command=req.service.stop_command,
        health_check=req.service.health_check,
        configuration=req.service.configuration,
        project_origin=req.service.project_origin,
        registered_by_agent=agent.type if agent else None,
    )
    return JSONResponse(
        _service_detail(repo, svc, process_manager=_process_mgr(request)),
        status_code=201,
    )


async def list_services(request: Request) -> JSONResponse:
    repo = _repo(request)
    q = request.query_params.get("query")
    registered_by_agent = request.query_params.get("agent")
    project_id = request.query_params.get("project_id")
    device_id = request.query_params.get("device_id")
    services = repo.list_services(
        query=q,
        registered_by_agent=registered_by_agent,
        project_id=project_id,
        device_id=device_id,
    )
    mgr = _process_mgr(request)
    items = [_service_detail(repo, s, process_manager=mgr) for s in services]
    return JSONResponse({"services": items})


async def get_service(request: Request) -> JSONResponse:
    repo = _repo(request)
    service_id = request.path_params["service_id"]
    svc = repo.get_service(service_id)
    if svc is None:
        raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")
    return JSONResponse(_service_detail(repo, svc, process_manager=_process_mgr(request)))


async def delete_service(request: Request) -> JSONResponse:
    """Hard-delete service + all allocations and port claims."""
    repo = _repo(request)
    service_id = request.path_params["service_id"]
    reason = None
    try:
        if request.headers.get("content-length") not in (None, "0"):
            body = await request.json()
            req = DeleteRequest.model_validate(body or {})
            reason = req.reason
    except ValidationError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception:
        reason = None
    result = repo.delete_service(service_id, reason=reason)
    return JSONResponse(result)


async def patch_service(request: Request) -> JSONResponse:
    repo = _repo(request)
    service_id = request.path_params["service_id"]
    try:
        body = await request.json()
        req = ServiceUpdateRequest.model_validate(body)
    except ValidationError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid JSON: {exc}") from exc

    updated = repo.update_service_metadata(
        service_id,
        name=req.name,
        description=req.description,
        code_path=req.code_path,
        working_directory=req.working_directory,
        start_command=req.start_command,
        stop_command=req.stop_command,
        health_check=req.health_check,
        configuration=req.configuration,
        project_origin=req.project_origin,
    )
    return JSONResponse(updated.model_dump(mode="json"))


async def get_port(request: Request) -> JSONResponse:
    repo = _repo(request)
    try:
        port = int(request.path_params["port"])
    except ValueError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, "port must be an integer") from exc
    found = repo.find_by_port(
        port,
        device_id=request.query_params.get("device_id") or "NODE_LOCAL",
        transport=request.query_params.get("transport") or "tcp",
    )
    if found is None:
        raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"No service owns port {port}")
    svc = found["service"]
    alloc = found["allocation"]
    return JSONResponse(
        {
            "port": port,
            "active": found["active"],
            "resource_name": found["resource_name"],
            "port_name": found.get("port_name"),
            "service": svc.model_dump(mode="json") if svc else None,
            "allocation": {
                "id": alloc.id,
                "allocation_name": alloc.allocation_name,
                "state": alloc.state.value,
            }
            if alloc
            else None,
        }
    )


async def check_allocation(request: Request) -> JSONResponse:
    repo = _repo(request)
    allocation_id = request.path_params["allocation_id"]
    result = check_allocation_ports(repo, allocation_id)
    return JSONResponse(result)


async def get_allocation(request: Request) -> JSONResponse:
    repo = _repo(request)
    allocation_id = request.path_params["allocation_id"]
    alloc = repo.get_allocation(allocation_id)
    if alloc is None:
        raise AprError(
            ErrorCode.ALLOCATION_NOT_FOUND,
            f"Allocation not found: {allocation_id}",
        )
    svc = repo.get_service(alloc.service_id)
    return JSONResponse(
        {
            "id": alloc.id,
            "service_id": alloc.service_id,
            "allocation_name": alloc.allocation_name,
            "state": alloc.state.value,
            "sticky": alloc.sticky,
            "created_at": alloc.created_at,
            "released_at": alloc.released_at,
            "release_reason": alloc.release_reason,
            "request_spec": (
                json.loads(alloc.request_spec_json) if alloc.request_spec_json else None
            ),
            "ports": [
                {
                    "resource_name": p.resource_name,
                    "port_name": p.port_name,
                    "port": p.port,
                    "transport": p.transport,
                    "ordinal": p.ordinal,
                }
                for p in alloc.ports
            ],
            "service": svc.model_dump(mode="json") if svc else None,
        }
    )


async def release_allocation(request: Request) -> JSONResponse:
    repo = _repo(request)
    allocation_id = request.path_params["allocation_id"]
    reason = None
    try:
        if request.headers.get("content-length") not in (None, "0"):
            body = await request.json()
            req = ReleaseRequest.model_validate(body or {})
            reason = req.reason
    except ValidationError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception:
        reason = None

    released = repo.release_allocation(allocation_id, reason=reason)
    return JSONResponse(
        {
            "allocation_id": released.id,
            "state": released.state.value,
            "released_at": released.released_at,
            "release_reason": released.release_reason,
            "ports_history": [
                {
                    "resource_name": p.resource_name,
                    "port_name": p.port_name,
                    "port": p.port,
                    "transport": p.transport,
                    "ordinal": p.ordinal,
                }
                for p in released.ports
            ],
        }
    )


async def delete_allocation(request: Request) -> JSONResponse:
    """Hard-delete allocation history and free claims if still reserved."""
    repo = _repo(request)
    allocation_id = request.path_params["allocation_id"]
    force = request.query_params.get("force", "true").lower() not in (
        "0",
        "false",
        "no",
    )
    reason = None
    try:
        if request.headers.get("content-length") not in (None, "0"):
            body = await request.json()
            req = DeleteRequest.model_validate(body or {})
            reason = req.reason
    except ValidationError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except Exception:
        reason = None
    result = repo.delete_allocation(allocation_id, reason=reason, force=force)
    return JSONResponse(result)


def _compress_ranges(ports: list[int]) -> list[list[int]]:
    """[20000, 20001, 20003] -> [[20000, 20001], [20003, 20003]].

    Keeps the payload small when a config excludes wide ranges, and gives the UI
    heat strip something it can draw directly.
    """
    out: list[list[int]] = []
    for port in sorted(ports):
        if out and port == out[-1][1] + 1:
            out[-1][1] = port
        else:
            out.append([port, port])
    return out


def _pool_of(request: Request):
    """Effective port pool (respects a pool injected into app state by tests)."""
    return _ensure_svc(request).pool


def _table_count(repo, table: str) -> int:
    row = repo.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")  # noqa: S608
    return int(row["c"]) if row else 0


async def list_listeners(request: Request) -> JSONResponse:
    """TCP ports currently being listened on locally (ground truth, not registry)."""
    pool = _pool_of(request)
    in_pool_only = request.query_params.get("in_pool") in ("1", "true", "yes")
    listeners = probe_listeners()
    items = [
        {"port": info.port, "pid": info.pid, "command": info.command}
        for info in sorted(listeners.values(), key=lambda i: i.port)
        if not in_pool_only or pool.start <= info.port <= pool.end
    ]
    return JSONResponse({"listeners": items, "count": len(items)})


async def get_pool(request: Request) -> JSONResponse:
    """Port pool shape and occupancy, for the utilization strip."""
    repo = _repo(request)
    pool = _pool_of(request)

    total = max(0, pool.end - pool.start + 1)
    excluded = [p for p in pool.excluded if pool.start <= p <= pool.end]
    usable = total - len(excluded)
    all_claimed = repo.active_claimed_ports()
    claimed = sorted(p for p in all_claimed if pool.start <= p <= pool.end)
    managed_outside_pool = sorted(
        p for p in all_claimed if not (pool.start <= p <= pool.end)
    )
    listening_in_pool = sorted(
        p for p in probe_listeners() if pool.start <= p <= pool.end
    )

    return JSONResponse(
        {
            "start": pool.start,
            "end": pool.end,
            "total": total,
            "usable": usable,
            "excluded_count": len(excluded),
            "excluded_ranges": _compress_ranges(excluded),
            "claimed": claimed,
            "claimed_count": len(claimed),
            "claimed_ranges": _compress_ranges(claimed),
            "managed_outside_pool": managed_outside_pool,
            "listening_in_pool": listening_in_pool,
            "free": max(0, usable - len(claimed)),
            "utilization": round(len(claimed) / usable, 6) if usable else 0.0,
        }
    )


async def get_overview(request: Request) -> JSONResponse:
    """Aggregate dashboard payload: one request, everything the KPI row needs."""
    repo = _repo(request)
    pool = _pool_of(request)
    services = repo.list_services()
    listeners = probe_listeners()

    by_agent: dict[str, int] = {}
    by_project: dict[str, int] = {}
    reserved = 0
    released = 0
    claimed_ports: list[int] = []

    for svc in services:
        actor = svc.registered_by_agent or "human"
        by_agent[actor] = by_agent.get(actor, 0) + 1
        by_project[svc.project_key] = by_project.get(svc.project_key, 0) + 1
        for alloc in repo.list_allocations_for_service(svc.id):
            if alloc.state == AllocationState.RESERVED:
                reserved += 1
                claimed_ports.extend(p.port for p in alloc.ports)
            else:
                released += 1

    live_ports = [p for p in claimed_ports if p in listeners]
    # Claimed but nothing is listening: registered yet not actually running.
    idle_ports = [p for p in claimed_ports if p not in listeners]

    total = max(0, pool.end - pool.start + 1)
    excluded_in_range = sum(1 for p in pool.excluded if pool.start <= p <= pool.end)
    usable = total - excluded_in_range
    claimed_in_pool = [p for p in claimed_ports if pool.start <= p <= pool.end]

    return JSONResponse(
        {
            "version": __version__,
            "hostname": socket.gethostname(),
            "services": {
                "total": len(services),
                "by_agent": by_agent,
                "by_project": by_project,
            },
            "allocations": {"reserved": reserved, "released": released},
            "ports": {
                "claimed": len(claimed_ports),
                "live": len(live_ports),
                "idle": len(idle_ports),
                "idle_ports": sorted(idle_ports),
            },
            "pool": {
                "start": pool.start,
                "end": pool.end,
                "usable": usable,
                "free": max(0, usable - len(claimed_in_pool)),
                "utilization": round(len(claimed_in_pool) / usable, 6) if usable else 0.0,
            },
            "nodes": {
                "total": _table_count(repo, "nodes"),
                "snapshots": _table_count(repo, "node_snapshots"),
            },
            "forwards": {
                "active": int(
                    (
                        repo.db.fetchone(
                            "SELECT COUNT(*) AS c FROM port_forwards"
                            " WHERE state IN ('starting', 'active', 'reconnecting')"
                        )
                        or {"c": 0}
                    )["c"]
                ),
            },
            "features": {
                "process_management": bool(
                    getattr(_config(request), "process_management_enabled", False)
                ),
            },
        }
    )


async def start_service_process(request: Request) -> JSONResponse:
    """Spawn services.start_command (gated by process_management.enabled)."""
    service_id = request.path_params["service_id"]
    proc = _process_mgr(request).start(service_id)
    return JSONResponse(proc.to_dict(), status_code=201)


async def stop_service_process(request: Request) -> JSONResponse:
    service_id = request.path_params["service_id"]
    proc = _process_mgr(request).stop(service_id)
    return JSONResponse(proc.to_dict())


async def get_service_logs(request: Request) -> JSONResponse:
    service_id = request.path_params["service_id"]
    try:
        tail = int(request.query_params.get("tail", "200"))
    except ValueError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, "tail must be an integer") from exc
    payload = _process_mgr(request).logs(service_id, tail=tail)
    return JSONResponse(payload)


async def get_service_process(request: Request) -> JSONResponse:
    """Latest (or live) managed process for a service, after reconciliation."""
    service_id = request.path_params["service_id"]
    mgr = _process_mgr(request)
    if mgr.repo.get_service(service_id) is None:
        raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")
    live = mgr.reconcile(service_id)
    latest = live or mgr.get_latest(service_id)
    return JSONResponse(
        {
            "service_id": service_id,
            "process": latest.to_dict() if latest else None,
        }
    )


# ── Nodes (SSH control plane) ─────────────────────────────────


async def list_nodes(request: Request) -> JSONResponse:
    mgr = _node_mgr(request)
    fm = _forward_mgr(request)

    def _work() -> list[dict[str, Any]]:
        fm.reconcile()
        return mgr.list_with_snapshots()

    nodes = await _to_thread(_work)
    return JSONResponse({"nodes": nodes})


async def create_node(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise AprError(ErrorCode.INVALID_REQUEST, "Body must be an object")
    mgr = _node_mgr(request)
    node = await _to_thread(
        mgr.create,
        name=str(body.get("name") or ""),
        ssh_host=str(body.get("ssh_host") or ""),
        ssh_user=body.get("ssh_user"),
        ssh_port=body.get("ssh_port"),
        identity_file=body.get("identity_file"),
        ssh_config_managed=bool(body.get("ssh_config_managed", True)),
        apr_command=str(body.get("apr_command") or "svcctl"),
        enabled=bool(body.get("enabled", True)),
        refresh_interval_seconds=int(body.get("refresh_interval_seconds") or 30),
        kind=str(body.get("kind") or "remote"),
    )
    return JSONResponse(node.to_dict(snapshot=None), status_code=201)


async def get_node(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    payload = await _to_thread(_node_mgr(request).detail_with_snapshot, node_id)
    return JSONResponse(payload)


async def patch_node(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    try:
        body = await request.json()
    except Exception as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise AprError(ErrorCode.INVALID_REQUEST, "Body must be an object")
    # Only pass keys that are present so optional clears work with explicit null.
    fields = {
        k: body[k]
        for k in (
            "name",
            "ssh_host",
            "ssh_user",
            "ssh_port",
            "identity_file",
            "ssh_config_managed",
            "apr_command",
            "enabled",
            "refresh_interval_seconds",
            "kind",
        )
        if k in body
    }
    mgr = _node_mgr(request)

    def _work() -> dict[str, Any]:
        node = mgr.update(node_id, **fields)
        return node.to_dict(snapshot=mgr.get_snapshot(node_id))

    return JSONResponse(await _to_thread(_work))


async def delete_node(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    fm = _forward_mgr(request)
    mgr = _node_mgr(request)

    def _work() -> dict[str, Any]:
        for fwd in fm.list_live(node_id=node_id):
            try:
                fm.stop(fwd.id)
            except AprError:
                pass
        return mgr.delete(node_id)

    return JSONResponse(await _to_thread(_work))


async def refresh_node(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    result = await _to_thread(_node_mgr(request).refresh, node_id)
    return JSONResponse(result)


async def list_node_services(request: Request) -> JSONResponse:
    """Return snapshot services if present; optional ?live=1 forces SSH list."""
    node_id = request.path_params["node_id"]
    live = request.query_params.get("live") in ("1", "true", "yes")
    mgr = _node_mgr(request)

    def _work() -> dict[str, Any]:
        node = mgr.require(node_id)
        if node.kind == "forward-only":
            return {"services": [], "snapshot": None}
        if live:
            data = mgr.list_services_live(node_id)
            return data if isinstance(data, dict) else {"services": data}
        snap = mgr.get_snapshot(node_id)
        if snap is None or snap.get("status") != "ok" or not snap.get("payload"):
            result = mgr.refresh(node_id)
            snap = result.get("snapshot")
        payload = (snap or {}).get("payload") or {}
        if isinstance(payload, dict) and "services" in payload:
            return {
                "services": payload.get("services") or [],
                "snapshot": {
                    "fetched_at": (snap or {}).get("fetched_at"),
                    "status": (snap or {}).get("status"),
                    "error": (snap or {}).get("error"),
                    "duration_ms": (snap or {}).get("duration_ms"),
                },
            }
        return {"services": [], "snapshot": snap}

    return JSONResponse(await _to_thread(_work))


async def get_node_service(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    service_id = request.path_params["service_id"]
    data = await _to_thread(_node_mgr(request).get_service_live, node_id, service_id)
    return JSONResponse(data)


async def start_node_service(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    service_id = request.path_params["service_id"]
    data = await _to_thread(_node_mgr(request).start_service, node_id, service_id)
    return JSONResponse(data, status_code=201)


async def stop_node_service(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    service_id = request.path_params["service_id"]
    data = await _to_thread(_node_mgr(request).stop_service, node_id, service_id)
    return JSONResponse(data)


async def node_service_logs(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    service_id = request.path_params["service_id"]
    try:
        tail = int(request.query_params.get("tail", "200"))
    except ValueError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, "tail must be an integer") from exc
    data = await _to_thread(
        _node_mgr(request).service_logs, node_id, service_id, tail=tail
    )
    return JSONResponse(data)


# ── Port forwards (autossh) ───────────────────────────────────


async def list_forwards(request: Request) -> JSONResponse:
    fm = _forward_mgr(request)
    node_id = request.query_params.get("node_id")

    def _work() -> list[dict[str, Any]]:
        fm.reconcile()
        return [f.to_dict() for f in fm.list_forwards(node_id=node_id)]

    return JSONResponse({"forwards": await _to_thread(_work)})


async def create_forward(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    try:
        body = await request.json()
    except Exception as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, f"Invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise AprError(ErrorCode.INVALID_REQUEST, "Body must be an object")
    if body.get("remote_port") is None:
        raise AprError(ErrorCode.INVALID_REQUEST, "remote_port is required")
    fm = _forward_mgr(request)
    fwd = await _to_thread(
        fm.start,
        node_id,
        remote_port=int(body["remote_port"]),
        local_port=int(body["local_port"]) if body.get("local_port") is not None else None,
        remote_host=str(body.get("remote_host") or "127.0.0.1"),
        label=body.get("label"),
        auto_reconnect=bool(body.get("auto_reconnect", True)),
    )
    return JSONResponse(fwd.to_dict(), status_code=201)


async def stop_forward(request: Request) -> JSONResponse:
    forward_id = request.path_params["forward_id"]
    fwd = await _to_thread(_forward_mgr(request).stop, forward_id)
    return JSONResponse(fwd.to_dict())


async def start_forward(request: Request) -> JSONResponse:
    forward_id = request.path_params["forward_id"]
    fwd = await _to_thread(_forward_mgr(request).restart, forward_id)
    return JSONResponse(fwd.to_dict(), status_code=201)


async def get_forward(request: Request) -> JSONResponse:
    forward_id = request.path_params["forward_id"]
    fm = _forward_mgr(request)

    def _work() -> dict[str, Any]:
        fm.reconcile(forward_id)
        return fm.require(forward_id).to_dict()

    return JSONResponse(await _to_thread(_work))


def api_routes() -> list[Route]:
    return [
        Route("/v1/overview", get_overview, methods=["GET"]),
        Route("/v1/listeners", list_listeners, methods=["GET"]),
        Route("/v1/pool", get_pool, methods=["GET"]),
        Route("/v1/allocations/ensure", ensure_allocation, methods=["POST"]),
        Route("/v1/services", create_service, methods=["POST"]),
        Route("/v1/services", list_services, methods=["GET"]),
        Route("/v1/services/{service_id}", get_service, methods=["GET"]),
        Route("/v1/services/{service_id}", patch_service, methods=["PATCH"]),
        Route("/v1/services/{service_id}", delete_service, methods=["DELETE"]),
        Route(
            "/v1/services/{service_id}/start",
            start_service_process,
            methods=["POST"],
        ),
        Route(
            "/v1/services/{service_id}/stop",
            stop_service_process,
            methods=["POST"],
        ),
        Route(
            "/v1/services/{service_id}/logs",
            get_service_logs,
            methods=["GET"],
        ),
        Route(
            "/v1/services/{service_id}/process",
            get_service_process,
            methods=["GET"],
        ),
        # Nodes
        Route("/v1/nodes", list_nodes, methods=["GET"]),
        Route("/v1/nodes", create_node, methods=["POST"]),
        Route("/v1/nodes/{node_id}", get_node, methods=["GET"]),
        Route("/v1/nodes/{node_id}", patch_node, methods=["PATCH"]),
        Route("/v1/nodes/{node_id}", delete_node, methods=["DELETE"]),
        Route("/v1/nodes/{node_id}/refresh", refresh_node, methods=["POST"]),
        Route("/v1/nodes/{node_id}/services", list_node_services, methods=["GET"]),
        Route(
            "/v1/nodes/{node_id}/services/{service_id}",
            get_node_service,
            methods=["GET"],
        ),
        Route(
            "/v1/nodes/{node_id}/services/{service_id}/start",
            start_node_service,
            methods=["POST"],
        ),
        Route(
            "/v1/nodes/{node_id}/services/{service_id}/stop",
            stop_node_service,
            methods=["POST"],
        ),
        Route(
            "/v1/nodes/{node_id}/services/{service_id}/logs",
            node_service_logs,
            methods=["GET"],
        ),
        Route("/v1/nodes/{node_id}/forwards", create_forward, methods=["POST"]),
        # Forwards
        Route("/v1/forwards", list_forwards, methods=["GET"]),
        Route("/v1/forwards/{forward_id}", get_forward, methods=["GET"]),
        Route(
            "/v1/forwards/{forward_id}/start",
            start_forward,
            methods=["POST"],
        ),
        Route("/v1/forwards/{forward_id}", stop_forward, methods=["DELETE"]),
        Route("/v1/ports/{port}", get_port, methods=["GET"]),
        Route("/v1/allocations/{allocation_id}", get_allocation, methods=["GET"]),
        Route(
            "/v1/allocations/{allocation_id}/check",
            check_allocation,
            methods=["GET"],
        ),
        Route(
            "/v1/allocations/{allocation_id}/release",
            release_allocation,
            methods=["POST"],
        ),
        Route(
            "/v1/allocations/{allocation_id}",
            delete_allocation,
            methods=["DELETE"],
        ),
    ]
