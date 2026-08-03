"""First Fit port allocation engine (PRD §15)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from apr.allocator.pool import PortPool, resolve_range
from apr.domain.errors import AprError, ErrorCode
from apr.domain.models import ResourceSpec, ResourceType, WithinRange


@dataclass
class PortAssignment:
    """One allocated port belonging to a resource."""

    resource_name: str
    port_name: str | None
    port: int
    ordinal: int = 0


@dataclass
class AllocationResult:
    assignments: list[PortAssignment] = field(default_factory=list)

    def named_ports(self) -> dict[str, int]:
        """Map for response `ports` field: named singles and count ports."""
        out: dict[str, int] = {}
        by_res: dict[str, list[PortAssignment]] = {}
        for a in self.assignments:
            by_res.setdefault(a.resource_name, []).append(a)

        for res_name, items in by_res.items():
            # If every assignment has a port_name, use those keys.
            if all(a.port_name for a in items):
                for a in items:
                    assert a.port_name is not None
                    out[a.port_name] = a.port
                continue
            # Block resources (no port names, multi-port) → only in blocks map.
            if len(items) > 1:
                continue
            # Single port: key is port_name or resource name.
            a = items[0]
            out[a.port_name or res_name] = a.port
        return out

    def blocks(self) -> dict[str, dict[str, int]]:
        """Map for response `blocks` field: contiguous multi-port resources without port_names."""
        by_res: dict[str, list[PortAssignment]] = {}
        for a in self.assignments:
            by_res.setdefault(a.resource_name, []).append(a)
        out: dict[str, dict[str, int]] = {}
        for name, items in by_res.items():
            if len(items) <= 1:
                continue
            # Named count contiguous still goes to ports map, not blocks.
            if any(a.port_name for a in items):
                continue
            ports = sorted(i.port for i in items)
            if ports[-1] - ports[0] + 1 == len(ports):
                out[name] = {
                    "start": ports[0],
                    "end": ports[-1],
                    "size": len(ports),
                }
        return out

    def port_rows(self) -> list[dict]:
        return [
            {
                "resource_name": a.resource_name,
                "port_name": a.port_name,
                "port": a.port,
                "ordinal": a.ordinal,
            }
            for a in self.assignments
        ]


class Allocator:
    """First Fit allocator over a port pool."""

    def __init__(self, pool: PortPool) -> None:
        self.pool = pool

    def allocate(
        self,
        resources: list[ResourceSpec],
        *,
        claimed: Iterable[int],
        listening: Iterable[int],
    ) -> AllocationResult:
        """Allocate all resources atomically in memory; raises on failure."""
        unavailable = set(claimed) | set(listening) | set(self.pool.excluded)
        # Also track ports reserved in this batch.
        batch_taken: set[int] = set()
        result = AllocationResult()

        for resource in resources:
            taken = unavailable | batch_taken
            assignments = self._allocate_one(resource, taken)
            for a in assignments:
                if a.port in batch_taken:
                    raise AprError(
                        ErrorCode.INTERNAL_ERROR,
                        f"Internal double-assign of port {a.port}",
                    )
                batch_taken.add(a.port)
            result.assignments.extend(assignments)

        return result

    def _allocate_one(
        self, resource: ResourceSpec, unavailable: set[int]
    ) -> list[PortAssignment]:
        start, end = self._range_for(resource.within)

        if resource.type == ResourceType.SINGLE:
            port = self._pick_single(resource, start, end, unavailable)
            return [
                PortAssignment(
                    resource_name=resource.name,
                    port_name=resource.name,
                    port=port,
                    ordinal=0,
                )
            ]

        if resource.type == ResourceType.BLOCK:
            assert resource.size is not None
            block_start = self._find_contiguous(resource.size, start, end, unavailable)
            return [
                PortAssignment(
                    resource_name=resource.name,
                    port_name=None,
                    port=block_start + i,
                    ordinal=i,
                )
                for i in range(resource.size)
            ]

        # count
        assert resource.count is not None
        names = resource.port_names
        if names is None:
            names = [f"{resource.name}_{i}" for i in range(resource.count)]

        if resource.contiguous:
            block_start = self._find_contiguous(resource.count, start, end, unavailable)
            return [
                PortAssignment(
                    resource_name=resource.name,
                    port_name=names[i],
                    port=block_start + i,
                    ordinal=i,
                )
                for i in range(resource.count)
            ]

        ports = self._find_n(resource.count, start, end, unavailable)
        return [
            PortAssignment(
                resource_name=resource.name,
                port_name=names[i],
                port=ports[i],
                ordinal=i,
            )
            for i in range(resource.count)
        ]

    def _range_for(self, within: WithinRange | None) -> tuple[int, int]:
        if within is None:
            return self.pool.start, self.pool.end
        start, end = resolve_range(self.pool, within.start, within.end)
        if start > end:
            raise AprError(
                ErrorCode.PORT_CAPACITY_EXHAUSTED,
                f"Requested range {within.start}-{within.end} does not intersect "
                f"pool {self.pool.start}-{self.pool.end}.",
            )
        return start, end

    def _is_free(self, port: int, unavailable: set[int], start: int, end: int) -> bool:
        return (
            start <= port <= end
            and port not in unavailable
            and port not in self.pool.excluded
            and self.pool.start <= port <= self.pool.end
        )

    def _pick_single(
        self,
        resource: ResourceSpec,
        start: int,
        end: int,
        unavailable: set[int],
    ) -> int:
        if resource.preferred_port is not None:
            pref = resource.preferred_port
            if self._is_free(pref, unavailable, start, end):
                return pref
            if resource.strict_preferred:
                raise AprError(
                    ErrorCode.PREFERRED_PORT_UNAVAILABLE,
                    f"Preferred port {pref} is unavailable for resource '{resource.name}'.",
                )
            # fall through to first fit

        for scan_start, scan_end in self.pool.first_fit_ranges(start, end):
            for port in range(scan_start, scan_end + 1):
                if self._is_free(port, unavailable, start, end):
                    return port
        raise AprError(
            ErrorCode.PORT_CAPACITY_EXHAUSTED,
            f"No free port available in {start}-{end} for resource '{resource.name}'.",
        )

    def _find_contiguous(
        self, size: int, start: int, end: int, unavailable: set[int]
    ) -> int:
        if size < 1:
            raise AprError(ErrorCode.INVALID_REQUEST, "size/count must be >= 1")
        for scan_start, scan_end in self.pool.first_fit_ranges(start, end):
            limit = scan_end - size + 1
            p = scan_start
            while p <= limit:
                ok = True
                for i in range(size):
                    port = p + i
                    if not self._is_free(port, unavailable, start, end):
                        ok = False
                        # jump past the blocking port
                        p = port + 1
                        break
                if ok:
                    return p
        raise AprError(
            ErrorCode.PORT_CAPACITY_EXHAUSTED,
            f"No contiguous block of {size} ports is available in {start}-{end}.",
        )

    def _find_n(
        self, n: int, start: int, end: int, unavailable: set[int]
    ) -> list[int]:
        found: list[int] = []
        for scan_start, scan_end in self.pool.first_fit_ranges(start, end):
            for port in range(scan_start, scan_end + 1):
                if self._is_free(port, unavailable, start, end):
                    found.append(port)
                    if len(found) == n:
                        return found
        raise AprError(
            ErrorCode.PORT_CAPACITY_EXHAUSTED,
            f"Need {n} free ports in {start}-{end}, found only {len(found)}.",
        )
