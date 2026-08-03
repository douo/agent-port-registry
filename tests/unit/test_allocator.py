"""First Fit allocator tests."""

from __future__ import annotations

import pytest

from apr.allocator.engine import Allocator
from apr.allocator.pool import PortPool, parse_exclude
from apr.domain.errors import AprError, ErrorCode
from apr.domain.models import ResourceSpec, WithinRange


def _pool(
    start: int = 20000,
    end: int = 20020,
    exclude: list | None = None,
    first_fit_start: int | None = None,
) -> PortPool:
    return PortPool(
        start=start,
        end=end,
        first_fit_start=first_fit_start,
        excluded=parse_exclude(exclude or []),
    )


def test_single_first_fit() -> None:
    alloc = Allocator(_pool())
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single")],
        claimed=set(),
        listening=set(),
    )
    assert result.assignments[0].port == 20000
    assert result.named_ports()["http"] == 20000


def test_skips_claimed_and_listening() -> None:
    alloc = Allocator(_pool())
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single")],
        claimed={20000, 20001},
        listening={20002},
    )
    assert result.assignments[0].port == 20003


def test_exclude_list() -> None:
    alloc = Allocator(_pool(exclude=["20000-20005", 20007]))
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single")],
        claimed=set(),
        listening=set(),
    )
    assert result.assignments[0].port == 20006


def test_preferred_port() -> None:
    alloc = Allocator(_pool())
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single", preferred_port=20010)],
        claimed=set(),
        listening=set(),
    )
    assert result.assignments[0].port == 20010


def test_preferred_low_port_before_first_fit_start() -> None:
    alloc = Allocator(_pool(start=3000, end=45999, first_fit_start=41000))
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single", preferred_port=3210)],
        claimed=set(),
        listening=set(),
    )
    assert result.named_ports()["http"] == 3210


def test_unavailable_preferred_port_falls_back_to_priority_band() -> None:
    alloc = Allocator(_pool(start=3000, end=45999, first_fit_start=41000))
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single", preferred_port=5173)],
        claimed={5173},
        listening=set(),
    )
    assert result.named_ports()["http"] == 41000


def test_first_fit_wraps_to_lower_band_after_priority_band_is_full() -> None:
    alloc = Allocator(_pool(start=3000, end=41001, first_fit_start=41000))
    result = alloc.allocate(
        [ResourceSpec(name="http", type="single")],
        claimed={41000, 41001},
        listening=set(),
    )
    assert result.named_ports()["http"] == 3000


def test_count_and_block_use_priority_band() -> None:
    alloc = Allocator(_pool(start=3000, end=45999, first_fit_start=41000))
    result = alloc.allocate(
        [
            ResourceSpec(
                name="named",
                type="count",
                count=2,
                port_names=["api", "metrics"],
            ),
            ResourceSpec(name="workers", type="block", size=2),
        ],
        claimed=set(),
        listening=set(),
    )
    assert result.named_ports() == {"api": 41000, "metrics": 41001}
    assert result.blocks()["workers"] == {
        "start": 41002,
        "end": 41003,
        "size": 2,
    }


def test_strict_preferred_unavailable() -> None:
    alloc = Allocator(_pool())
    with pytest.raises(AprError) as ei:
        alloc.allocate(
            [
                ResourceSpec(
                    name="http",
                    type="single",
                    preferred_port=20000,
                    strict_preferred=True,
                )
            ],
            claimed={20000},
            listening=set(),
        )
    assert ei.value.code == ErrorCode.PREFERRED_PORT_UNAVAILABLE


def test_block_contiguous() -> None:
    alloc = Allocator(_pool(end=20050))
    result = alloc.allocate(
        [ResourceSpec(name="workers", type="block", size=8)],
        claimed={20000, 20001},
        listening=set(),
    )
    ports = [a.port for a in result.assignments]
    assert ports == list(range(20002, 20010))
    blocks = result.blocks()
    assert blocks["workers"] == {"start": 20002, "end": 20009, "size": 8}


def test_block_jumps_over_hole() -> None:
    alloc = Allocator(_pool(end=20030))
    # Occupy middle so first fit of 5 starts after the hole
    claimed = {20002}
    result = alloc.allocate(
        [ResourceSpec(name="workers", type="block", size=5)],
        claimed=claimed,
        listening=set(),
    )
    ports = [a.port for a in result.assignments]
    assert ports == list(range(20003, 20008))


def test_count_non_contiguous() -> None:
    alloc = Allocator(_pool(end=20020))
    result = alloc.allocate(
        [
            ResourceSpec(
                name="service-ports",
                type="count",
                count=3,
                contiguous=False,
                port_names=["http", "metrics", "debug"],
            )
        ],
        claimed={20001},
        listening={20003},
    )
    named = result.named_ports()
    assert named == {"http": 20000, "metrics": 20002, "debug": 20004}


def test_count_contiguous_named() -> None:
    alloc = Allocator(_pool(end=20020))
    result = alloc.allocate(
        [
            ResourceSpec(
                name="service-ports",
                type="count",
                count=3,
                contiguous=True,
                port_names=["http", "metrics", "debug"],
            )
        ],
        claimed=set(),
        listening=set(),
    )
    named = result.named_ports()
    assert named == {"http": 20000, "metrics": 20001, "debug": 20002}


def test_multi_resource_no_overlap() -> None:
    alloc = Allocator(_pool(end=20030))
    result = alloc.allocate(
        [
            ResourceSpec(name="http", type="single"),
            ResourceSpec(name="workers", type="block", size=4),
            ResourceSpec(
                name="aux",
                type="count",
                count=2,
                contiguous=False,
                port_names=["metrics", "debug"],
            ),
        ],
        claimed=set(),
        listening=set(),
    )
    ports = [a.port for a in result.assignments]
    assert len(ports) == len(set(ports))
    assert result.named_ports()["http"] == 20000
    assert result.blocks()["workers"]["start"] == 20001


def test_within_range() -> None:
    alloc = Allocator(_pool(start=20000, end=30000))
    result = alloc.allocate(
        [
            ResourceSpec(
                name="http",
                type="single",
                within=WithinRange(start=25000, end=25010),
            )
        ],
        claimed=set(),
        listening=set(),
    )
    assert result.assignments[0].port == 25000


def test_capacity_exhausted() -> None:
    alloc = Allocator(_pool(start=20000, end=20002))
    with pytest.raises(AprError) as ei:
        alloc.allocate(
            [ResourceSpec(name="workers", type="block", size=8)],
            claimed=set(),
            listening=set(),
        )
    assert ei.value.code == ErrorCode.PORT_CAPACITY_EXHAUSTED
