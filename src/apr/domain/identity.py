"""Stable deployment identity normalization.

An Agent is an actor, not part of a service's identity.  The same deployment
must therefore resolve to the same record when Codex, Claude Code, or a human
configures it later.
"""

from __future__ import annotations

from dataclasses import dataclass

from apr.domain.errors import AprError, ErrorCode


LOCAL_DEVICE_ID = "NODE_LOCAL"
EMPTY_PROJECT = "-"
EMPTY_INSTANCE = "default"


def normalize_project(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return EMPTY_PROJECT
    return str(value).strip()


def normalize_device_id(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return LOCAL_DEVICE_ID
    return str(value).strip()


def require_local_device_id(value: str | None) -> str:
    """Reject attempts to mutate another node through this APR instance."""
    device_id = normalize_device_id(value)
    if device_id != LOCAL_DEVICE_ID:
        raise AprError(
            ErrorCode.INVALID_REQUEST,
            "A master APR cannot mutate a target node; run this operation on "
            "the target node's local APR.",
        )
    return device_id


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
    """Normalized unique key for one service deployment on one device."""

    device_id: str
    project_id: str | None
    project_key: str
    service_key: str
    instance_key: str

    @classmethod
    def from_raw(
        cls,
        *,
        device_id: str | None,
        project_id: str | None,
        service_key: str,
        instance: str | None,
    ) -> ServiceIdentity:
        return cls(
            device_id=normalize_device_id(device_id),
            project_id=(
                project_id.strip()
                if project_id and str(project_id).strip()
                else None
            ),
            project_key=normalize_project(project_id),
            service_key=normalize_service_key(service_key),
            instance_key=normalize_instance(instance),
        )

    def display_key(self) -> str:
        return (
            f"{self.device_id} + {self.project_key} + "
            f"{self.service_key} + {self.instance_key}"
        )
