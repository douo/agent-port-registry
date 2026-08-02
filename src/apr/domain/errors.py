"""Business error codes (PRD §16)."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    SERVICE_IDENTITY_CONFLICT = "SERVICE_IDENTITY_CONFLICT"
    ALLOCATION_SPEC_MISMATCH = "ALLOCATION_SPEC_MISMATCH"
    PORT_CAPACITY_EXHAUSTED = "PORT_CAPACITY_EXHAUSTED"
    PREFERRED_PORT_UNAVAILABLE = "PREFERRED_PORT_UNAVAILABLE"
    PORT_OCCUPIED = "PORT_OCCUPIED"
    ALLOCATION_RELEASED = "ALLOCATION_RELEASED"
    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    ALLOCATION_NOT_FOUND = "ALLOCATION_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AprError(Exception):
    """Domain error with stable machine-readable code."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": str(self.code), "message": self.message}}
