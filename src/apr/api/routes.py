"""HTTP routes for APR Registry (PRD §10)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from apr.domain.errors import AprError, ErrorCode
from apr.domain.identity import ServiceIdentity
from apr.domain.models import (
    DeleteRequest,
    EnsureRequest,
    ReleaseRequest,
    ServiceCreateRequest,
    ServiceUpdateRequest,
)
from apr.service.ensure import EnsureService, check_allocation_ports


def _state(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "apr", {}) or {}


def _repo(request: Request):
    repo = _state(request).get("repo")
    if repo is None:
        raise AprError(ErrorCode.INTERNAL_ERROR, "Repository not initialized")
    return repo


def _ensure_svc(request: Request) -> EnsureService:
    svc = _state(request).get("ensure")
    if svc is None:
        cfg = _state(request).get("config")
        svc = EnsureService(_repo(request), config=cfg)
        _state(request)["ensure"] = svc
    return svc


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


def _service_detail(repo, svc) -> dict[str, Any]:
    allocs = repo.list_allocations_for_service(svc.id)
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
                        "ordinal": p.ordinal,
                    }
                    for p in a.ports
                ],
            }
            for a in allocs
        ],
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
        agent_type=agent.type if agent else None,
        agent_project_id=agent.project_id if agent else None,
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
    )
    return JSONResponse(_service_detail(repo, svc), status_code=201)


async def list_services(request: Request) -> JSONResponse:
    repo = _repo(request)
    q = request.query_params.get("query")
    agent_type = request.query_params.get("agent_type")
    agent_project_id = request.query_params.get("agent_project_id")
    services = repo.list_services(
        query=q,
        agent_type=agent_type,
        agent_project_id=agent_project_id,
    )
    items = [_service_detail(repo, s) for s in services]
    return JSONResponse({"services": items})


async def get_service(request: Request) -> JSONResponse:
    repo = _repo(request)
    service_id = request.path_params["service_id"]
    svc = repo.get_service(service_id)
    if svc is None:
        raise AprError(ErrorCode.SERVICE_NOT_FOUND, f"Service not found: {service_id}")
    return JSONResponse(_service_detail(repo, svc))


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
    )
    return JSONResponse(updated.model_dump(mode="json"))


async def get_port(request: Request) -> JSONResponse:
    repo = _repo(request)
    try:
        port = int(request.path_params["port"])
    except ValueError as exc:
        raise AprError(ErrorCode.INVALID_REQUEST, "port must be an integer") from exc
    found = repo.find_by_port(port)
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


def api_routes() -> list[Route]:
    return [
        Route("/v1/allocations/ensure", ensure_allocation, methods=["POST"]),
        Route("/v1/services", create_service, methods=["POST"]),
        Route("/v1/services", list_services, methods=["GET"]),
        Route("/v1/services/{service_id}", get_service, methods=["GET"]),
        Route("/v1/services/{service_id}", patch_service, methods=["PATCH"]),
        Route("/v1/services/{service_id}", delete_service, methods=["DELETE"]),
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
