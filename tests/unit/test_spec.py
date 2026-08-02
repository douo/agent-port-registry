"""Allocation spec matching tests."""

from apr.domain.models import ResourceSpec
from apr.domain.spec import canonical_spec_json, specs_match


def test_same_single_matches() -> None:
    resources = [ResourceSpec(name="http", type="single")]
    stored = canonical_spec_json(resources)
    assert specs_match(stored, resources)


def test_count_change_mismatch() -> None:
    original = [ResourceSpec(name="ports", type="count", count=1, port_names=["http"])]
    stored = canonical_spec_json(original)
    changed = [ResourceSpec(name="ports", type="count", count=3, port_names=["a", "b", "c"])]
    assert not specs_match(stored, changed)


def test_block_size_mismatch() -> None:
    original = [ResourceSpec(name="workers", type="block", size=8)]
    stored = canonical_spec_json(original)
    changed = [ResourceSpec(name="workers", type="block", size=4)]
    assert not specs_match(stored, changed)


def test_preferred_port_ignored_for_shape() -> None:
    a = [ResourceSpec(name="http", type="single", preferred_port=28080)]
    b = [ResourceSpec(name="http", type="single", preferred_port=29000)]
    assert specs_match(canonical_spec_json(a), b)
