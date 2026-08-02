"""Domain and API-facing models (Pydantic)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ResourceType(StrEnum):
    SINGLE = "single"
    BLOCK = "block"
    COUNT = "count"


class AllocationState(StrEnum):
    RESERVED = "reserved"
    RELEASED = "released"


class WithinRange(BaseModel):
    start: int
    end: int

    @model_validator(mode="after")
    def _check_range(self) -> WithinRange:
        if self.start < 1 or self.end > 65535 or self.start > self.end:
            raise ValueError("within range must satisfy 1 <= start <= end <= 65535")
        return self


class ResourceSpec(BaseModel):
    name: str = Field(min_length=1)
    type: ResourceType
    size: int | None = None
    count: int | None = None
    contiguous: bool = False
    port_names: list[str] | None = None
    preferred_port: int | None = None
    strict_preferred: bool = False
    within: WithinRange | None = None

    @model_validator(mode="after")
    def _validate_by_type(self) -> ResourceSpec:
        if self.type == ResourceType.SINGLE:
            return self
        if self.type == ResourceType.BLOCK:
            if self.size is None or self.size < 1:
                raise ValueError("block resource requires size >= 1")
            return self
        # count
        if self.count is None or self.count < 1:
            raise ValueError("count resource requires count >= 1")
        if self.port_names is not None and len(self.port_names) != self.count:
            raise ValueError("port_names length must equal count")
        return self


class AgentContext(BaseModel):
    type: str | None = None
    project_id: str | None = None


class ServiceInput(BaseModel):
    key: str = Field(min_length=1)
    instance: str | None = "default"
    name: str | None = None
    description: str | None = None
    code_path: str | None = None
    working_directory: str | None = None
    start_command: str | None = None


class EnsureRequest(BaseModel):
    agent: AgentContext | None = None
    service: ServiceInput
    allocation_name: str = "default"
    resources: list[ResourceSpec] = Field(min_length=1)

    @field_validator("allocation_name")
    @classmethod
    def _alloc_name(cls, v: str) -> str:
        v = (v or "default").strip() or "default"
        return v


class PortAvailability(BaseModel):
    state: Literal["free", "occupied", "unknown"] = "unknown"
    pid: int | None = None
    command: str | None = None


class EnsureResponse(BaseModel):
    service_id: str
    allocation_id: str
    existing: bool
    sticky: bool = True
    ports: dict[str, int] = Field(default_factory=dict)
    blocks: dict[str, dict[str, int]] = Field(default_factory=dict)
    availability: dict[str, PortAvailability] = Field(default_factory=dict)


class ServiceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    code_path: str | None = None
    working_directory: str | None = None
    start_command: str | None = None


class ServiceCreateRequest(BaseModel):
    """Create a service index entry without allocating ports."""

    agent: AgentContext | None = None
    service: ServiceInput


class ReleaseRequest(BaseModel):
    reason: str | None = None


class DeleteRequest(BaseModel):
    reason: str | None = None


class ServiceRecord(BaseModel):
    id: str
    agent_type: str | None = None
    agent_project_id: str | None = None
    agent_type_key: str
    agent_project_key: str
    service_key: str
    instance_key: str
    name: str
    description: str | None = None
    code_path: str | None = None
    working_directory: str | None = None
    start_command: str | None = None
    created_at: str
    updated_at: str


class AllocatedPortRecord(BaseModel):
    allocation_id: str
    resource_name: str
    port_name: str | None = None
    port: int
    ordinal: int = 0


class AllocationRecord(BaseModel):
    id: str
    service_id: str
    allocation_name: str
    request_spec_json: str
    state: AllocationState
    sticky: bool = True
    created_at: str
    released_at: str | None = None
    release_reason: str | None = None
    ports: list[AllocatedPortRecord] = Field(default_factory=list)


def resource_specs_to_canonical(resources: list[ResourceSpec]) -> list[dict[str, Any]]:
    """Stable JSON-serializable form for request_spec comparison."""
    out: list[dict[str, Any]] = []
    for r in resources:
        item: dict[str, Any] = {
            "name": r.name,
            "type": str(r.type),
        }
        if r.type == ResourceType.BLOCK:
            item["size"] = r.size
        if r.type == ResourceType.COUNT:
            item["count"] = r.count
            item["contiguous"] = bool(r.contiguous)
            if r.port_names is not None:
                item["port_names"] = list(r.port_names)
        # preferred / within do not change identity of an existing allocation's
        # "resource shape"; PRD §6.3 lists count/type/size/names/contiguity.
        # We intentionally omit preferred_port and within from the canonical spec
        # used for mismatch detection of *shape*, but store full original for audit.
        out.append(item)
    return out


def full_spec_dump(resources: list[ResourceSpec]) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json", exclude_none=True) for r in resources]
