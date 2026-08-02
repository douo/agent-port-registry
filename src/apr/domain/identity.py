"""Service identity normalization (PRD §6.1)."""

from __future__ import annotations

from dataclasses import dataclass


EMPTY_AGENT_TYPE = "human"
EMPTY_AGENT_PROJECT = "-"
EMPTY_INSTANCE = "default"


def normalize_agent_type(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return EMPTY_AGENT_TYPE
    return str(value).strip()


def normalize_agent_project(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return EMPTY_AGENT_PROJECT
    return str(value).strip()


def normalize_instance(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return EMPTY_INSTANCE
    return str(value).strip()


def normalize_service_key(value: str) -> str:
    key = str(value).strip()
    if not key:
        raise ValueError("service.key must be non-empty")
    return key


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """Normalized unique key components for a Service."""

    agent_type: str | None
    agent_project_id: str | None
    agent_type_key: str
    agent_project_key: str
    service_key: str
    instance_key: str

    @classmethod
    def from_raw(
        cls,
        *,
        agent_type: str | None,
        agent_project_id: str | None,
        service_key: str,
        instance: str | None,
    ) -> ServiceIdentity:
        return cls(
            agent_type=(agent_type.strip() if agent_type and agent_type.strip() else None),
            agent_project_id=(
                agent_project_id.strip()
                if agent_project_id and str(agent_project_id).strip()
                else None
            ),
            agent_type_key=normalize_agent_type(agent_type),
            agent_project_key=normalize_agent_project(agent_project_id),
            service_key=normalize_service_key(service_key),
            instance_key=normalize_instance(instance),
        )

    def display_key(self) -> str:
        return (
            f"{self.agent_type_key} + {self.agent_project_key} + "
            f"{self.service_key} + {self.instance_key}"
        )
