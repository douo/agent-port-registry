"""Port pool and exclude-list helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from apr.config import PortPoolConfig


@dataclass
class PortPool:
    start: int
    end: int
    first_fit_start: int | None = None
    excluded: set[int] = field(default_factory=set)

    @classmethod
    def from_config(cls, cfg: PortPoolConfig) -> PortPool:
        return cls(
            start=cfg.start,
            end=cfg.end,
            first_fit_start=cfg.first_fit_start,
            excluded=parse_exclude(cfg.exclude),
        )

    def contains(self, port: int) -> bool:
        return self.start <= port <= self.end and port not in self.excluded

    def first_fit_ranges(self, start: int, end: int) -> list[tuple[int, int]]:
        """Return scan ranges with the configured high-priority band first."""
        anchor = self.first_fit_start
        if anchor is None or anchor <= start or anchor > end:
            return [(start, end)]
        return [(anchor, end), (start, anchor - 1)]


def parse_exclude(items: list[str | int]) -> set[int]:
    """Parse exclude entries: bare ports or 'start-end' ranges."""
    out: set[int] = set()
    for item in items:
        if isinstance(item, int):
            out.add(item)
            continue
        s = str(item).strip()
        if not s:
            continue
        if "-" in s:
            # Distinguish negative numbers: only treat as range if both sides present.
            left, _, right = s.partition("-")
            if left.strip() and right.strip():
                a, b = int(left.strip()), int(right.strip())
                if a > b:
                    a, b = b, a
                out.update(range(a, b + 1))
                continue
        out.add(int(s))
    return out


def resolve_range(
    pool: PortPool,
    within_start: int | None = None,
    within_end: int | None = None,
) -> tuple[int, int]:
    start = pool.start if within_start is None else max(pool.start, within_start)
    end = pool.end if within_end is None else min(pool.end, within_end)
    if within_start is not None:
        start = max(start, within_start)
    if within_end is not None:
        end = min(end, within_end)
    # If request within is entirely outside pool, use the within window clipped to 1..65535
    # but still require intersection with pool for allocation from pool.
    if within_start is not None and within_end is not None:
        # Prefer the intersection of pool and within.
        start = max(pool.start, within_start)
        end = min(pool.end, within_end)
    return start, end
