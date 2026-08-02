"""ID generation for services and allocations."""

from __future__ import annotations

import secrets
import time


def _ulid_like(prefix: str) -> str:
    """Time-sortable unique id without external deps: prefix + timestamp + random.

    Format: {prefix}_{timestamp_ms_base36}{random_base36}
    """
    ms = int(time.time() * 1000)
    ts = _b36(ms)
    rnd = _b36(secrets.randbits(48))
    return f"{prefix}_{ts}{rnd}".upper()


def _b36(n: int) -> str:
    if n == 0:
        return "0"
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    chars: list[str] = []
    while n:
        n, r = divmod(n, 36)
        chars.append(alphabet[r])
    return "".join(reversed(chars))


def new_service_id() -> str:
    return _ulid_like("svc")


def new_allocation_id() -> str:
    return _ulid_like("alloc")
