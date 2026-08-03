"""Ensure allocation use-case (PRD §15.4)."""

from __future__ import annotations

from typing import Any

from apr.allocator.engine import Allocator
from apr.allocator.pool import PortPool
from apr.config import Config, PortPoolConfig
from apr.domain.errors import AprError, ErrorCode
from apr.domain.identity import LOCAL_DEVICE_ID, ServiceIdentity, require_local_device_id
from apr.domain.models import (
    AllocationState,
    EnsureRequest,
    EnsureResponse,
    PortAvailability,
    ResourceSpec,
    full_spec_dump,
)
from apr.domain.spec import specs_match
from apr.listener.probe import ListenerInfo, availability_for_ports, probe_listeners
from apr.store.repository import Repository


class EnsureService:
    def __init__(
        self,
        repo: Repository,
        *,
        port_pool: PortPool | PortPoolConfig | None = None,
        config: Config | None = None,
    ) -> None:
        self.repo = repo
        if isinstance(port_pool, PortPool):
            self.pool = port_pool
        elif isinstance(port_pool, PortPoolConfig):
            self.pool = PortPool.from_config(port_pool)
        elif config is not None:
            self.pool = PortPool.from_config(config.port_pool)
        else:
            self.pool = PortPool.from_config(PortPoolConfig())
        self.allocator = Allocator(self.pool)

    def ensure(self, request: EnsureRequest) -> EnsureResponse:
        if not request.resources:
            raise AprError(ErrorCode.INVALID_REQUEST, "resources must be non-empty")

        agent = request.agent
        device_id = require_local_device_id(request.device_id)
        identity = ServiceIdentity.from_raw(
            device_id=device_id,
            project_id=request.service.project_id,
            service_key=request.service.key,
            instance=request.service.instance,
        )
        service_name = request.service.name or request.service.key

        with self.repo.db.transaction() as conn:
            device = conn.execute(
                "SELECT id FROM nodes WHERE id = ?", (identity.device_id,)
            ).fetchone()
            if device is None:
                raise AprError(
                    ErrorCode.INVALID_REQUEST,
                    f"Unknown device_id: {identity.device_id}",
                )
            svc = self.repo.find_service_by_identity_conn(conn, identity)
            if svc is None:
                svc = self.repo.create_service(
                    identity,
                    name=service_name,
                    description=request.service.description,
                    code_path=request.service.code_path,
                    working_directory=request.service.working_directory,
                    start_command=request.service.start_command,
                    stop_command=request.service.stop_command,
                    health_check=request.service.health_check,
                    configuration=request.service.configuration,
                    auto_start=bool(request.service.auto_start),
                    project_origin=request.service.project_origin,
                    registered_by_agent=agent.type if agent else None,
                    conn=conn,
                )
            else:
                # Update index metadata without touching ports (FR-002).
                svc = self.repo.update_service_metadata(
                    svc.id,
                    name=request.service.name if request.service.name else None,
                    description=request.service.description,
                    code_path=request.service.code_path,
                    working_directory=request.service.working_directory,
                    start_command=request.service.start_command,
                    stop_command=request.service.stop_command,
                    health_check=request.service.health_check,
                    configuration=request.service.configuration,
                    auto_start=request.service.auto_start,
                    project_origin=request.service.project_origin,
                    registered_by_agent=agent.type if agent else None,
                    conn=conn,
                )

            existing = self.repo.find_allocation(
                svc.id, request.allocation_name, conn=conn
            )
            if existing is not None and existing.state == AllocationState.RESERVED:
                if not specs_match(existing.request_spec_json, request.resources):
                    raise AprError(
                        ErrorCode.ALLOCATION_SPEC_MISMATCH,
                        "Existing allocation resource spec differs from the request; "
                        "APR will not silently resize or replace ports.",
                    )
                return self._response_from_existing(
                    existing,
                    svc.id,
                    device_id=identity.device_id,
                    existing=True,
                )

            if existing is not None and existing.state == AllocationState.RELEASED:
                self.repo.delete_released_allocation_for_reuse(
                    conn, svc.id, request.allocation_name
                )

            # Snapshot OS listeners + DB claims, then First Fit.
            is_local = identity.device_id == LOCAL_DEVICE_ID
            listeners = probe_listeners() if is_local else {}
            claimed = self.repo.active_claimed_ports(
                device_id=identity.device_id,
                conn=conn,
            )
            if is_local:
                claimed |= self.repo.reserved_forward_ports(conn=conn)
            listening = set(listeners.keys())

            try:
                result = self.allocator.allocate(
                    request.resources,
                    claimed=claimed,
                    listening=listening,
                )
            except AprError:
                raise

            transport_by_resource = {r.name: r.transport for r in request.resources}
            port_rows = [
                {
                    **row,
                    "transport": transport_by_resource.get(row["resource_name"], "tcp"),
                }
                for row in result.port_rows()
            ]
            alloc = self.repo.create_allocation_with_ports(
                conn,
                service_id=svc.id,
                device_id=identity.device_id,
                allocation_name=request.allocation_name,
                request_spec=full_spec_dump(request.resources),
                port_rows=port_rows,
                sticky=True,
            )

            ports_map = self._ports_map(alloc.ports, request.resources)
            blocks_map = self._blocks_map(alloc.ports, request.resources)
            avail = self._availability(
                ports_map,
                blocks_map,
                listeners,
                observable=is_local,
            )

            return EnsureResponse(
                service_id=svc.id,
                allocation_id=alloc.id,
                device_id=identity.device_id,
                existing=False,
                sticky=True,
                ports=ports_map,
                blocks=blocks_map,
                availability=avail,
            )

    def _response_from_existing(
        self,
        alloc: Any,
        service_id: str,
        *,
        device_id: str,
        existing: bool,
    ) -> EnsureResponse:
        is_local = device_id == LOCAL_DEVICE_ID
        listeners = probe_listeners() if is_local else {}
        # Reconstruct resources shape from stored ports for maps.
        ports_map: dict[str, int] = {}
        blocks_map: dict[str, dict[str, int]] = {}

        by_res: dict[str, list] = {}
        for p in alloc.ports:
            by_res.setdefault(p.resource_name, []).append(p)

        for res_name, items in by_res.items():
            items_sorted = sorted(items, key=lambda x: x.ordinal)
            if all(i.port_name for i in items_sorted):
                for i in items_sorted:
                    ports_map[i.port_name] = i.port
            elif len(items_sorted) == 1:
                key = items_sorted[0].port_name or res_name
                ports_map[key] = items_sorted[0].port
            else:
                ports = [i.port for i in items_sorted]
                blocks_map[res_name] = {
                    "start": ports[0],
                    "end": ports[-1],
                    "size": len(ports),
                }

        avail = self._availability(
            ports_map,
            blocks_map,
            listeners,
            observable=is_local,
        )
        return EnsureResponse(
            service_id=service_id,
            allocation_id=alloc.id,
            device_id=device_id,
            existing=existing,
            sticky=bool(alloc.sticky),
            ports=ports_map,
            blocks=blocks_map,
            availability=avail,
        )

    def _ports_map(self, port_rows: list, resources: list[ResourceSpec]) -> dict[str, int]:
        # Prefer using allocator-style reconstruction.
        from apr.allocator.engine import AllocationResult, PortAssignment

        result = AllocationResult(
            assignments=[
                PortAssignment(
                    resource_name=p.resource_name,
                    port_name=p.port_name,
                    port=p.port,
                    ordinal=p.ordinal,
                )
                for p in port_rows
            ]
        )
        return result.named_ports()

    def _blocks_map(
        self, port_rows: list, resources: list[ResourceSpec]
    ) -> dict[str, dict[str, int]]:
        from apr.allocator.engine import AllocationResult, PortAssignment

        result = AllocationResult(
            assignments=[
                PortAssignment(
                    resource_name=p.resource_name,
                    port_name=p.port_name,
                    port=p.port,
                    ordinal=p.ordinal,
                )
                for p in port_rows
            ]
        )
        return result.blocks()

    def _availability(
        self,
        ports_map: dict[str, int],
        blocks_map: dict[str, dict[str, int]],
        listeners: dict[int, ListenerInfo],
        *,
        observable: bool = True,
    ) -> dict[str, PortAvailability]:
        # Key by port name / block name for response.
        out: dict[str, PortAvailability] = {}
        for name, port in ports_map.items():
            if not observable:
                out[name] = PortAvailability(state="unknown")
                continue
            info = listeners.get(port)
            if info is None:
                out[name] = PortAvailability(state="free")
            else:
                out[name] = PortAvailability(
                    state="occupied",
                    pid=info.pid,
                    command=info.command,
                )
        for name, block in blocks_map.items():
            if not observable:
                out[name] = PortAvailability(state="unknown")
                continue
            # Report availability on the block name using the start port as representative;
            # also check if any port in the block is occupied.
            occupied_any = False
            pid = None
            command = None
            for p in range(block["start"], block["end"] + 1):
                info = listeners.get(p)
                if info is not None:
                    occupied_any = True
                    pid = info.pid
                    command = info.command
                    break
            if occupied_any:
                out[name] = PortAvailability(state="occupied", pid=pid, command=command)
            else:
                out[name] = PortAvailability(state="free")
        return out


def check_allocation_ports(
    repo: Repository, allocation_id: str
) -> dict[str, Any]:
    alloc = repo.get_allocation(allocation_id)
    if alloc is None:
        raise AprError(
            ErrorCode.ALLOCATION_NOT_FOUND, f"Allocation not found: {allocation_id}"
        )
    listeners = probe_listeners()
    ports = { (p.port_name or f"{p.resource_name}[{p.ordinal}]"): p.port for p in alloc.ports }
    raw = availability_for_ports(ports.values(), listeners)
    availability = {}
    for name, port in ports.items():
        entry = raw.get(port, {"state": "free"})
        availability[name] = entry
    return {
        "allocation_id": alloc.id,
        "service_id": alloc.service_id,
        "state": alloc.state.value,
        "ports": ports,
        "availability": availability,
    }
