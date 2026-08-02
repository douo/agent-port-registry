"""HTTP error mapping for APR API."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from apr.domain.errors import AprError, ErrorCode

_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.SERVICE_IDENTITY_CONFLICT: 409,
    ErrorCode.ALLOCATION_SPEC_MISMATCH: 409,
    ErrorCode.PORT_CAPACITY_EXHAUSTED: 507,
    ErrorCode.PREFERRED_PORT_UNAVAILABLE: 409,
    ErrorCode.PORT_OCCUPIED: 409,
    ErrorCode.ALLOCATION_RELEASED: 409,
    ErrorCode.SERVICE_NOT_FOUND: 404,
    ErrorCode.ALLOCATION_NOT_FOUND: 404,
    ErrorCode.PROCESS_MANAGEMENT_DISABLED: 403,
    ErrorCode.PROCESS_ALREADY_RUNNING: 409,
    ErrorCode.PROCESS_NOT_RUNNING: 409,
    ErrorCode.PROCESS_START_FAILED: 500,
    ErrorCode.NO_START_COMMAND: 400,
    ErrorCode.INTERNAL_ERROR: 500,
}


async def apr_error_handler(_request: Request, exc: AprError) -> JSONResponse:
    status = _STATUS.get(exc.code, 500)
    return JSONResponse(exc.to_dict(), status_code=status)


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    err = AprError(ErrorCode.INTERNAL_ERROR, str(exc) or "internal error")
    return JSONResponse(err.to_dict(), status_code=500)
