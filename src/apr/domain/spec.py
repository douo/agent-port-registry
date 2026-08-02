"""Allocation request_spec comparison (PRD §6.3)."""

from __future__ import annotations

import json
from typing import Any

from apr.domain.models import ResourceSpec, resource_specs_to_canonical


def canonical_spec_json(resources: list[ResourceSpec]) -> str:
    return json.dumps(resource_specs_to_canonical(resources), sort_keys=True, separators=(",", ":"))


def specs_match(stored_spec_json: str, resources: list[ResourceSpec]) -> bool:
    """Return True if resource *shape* matches the stored allocation.

    Compared fields (PRD §6.3):
    - resource count / names / types
    - count / contiguous
    - block.size
    - port_names list
    """
    try:
        stored = json.loads(stored_spec_json)
    except json.JSONDecodeError:
        return False

    # Support both full dumps and canonical dumps.
    if isinstance(stored, dict) and "resources" in stored:
        stored_list = stored["resources"]
    elif isinstance(stored, list):
        stored_list = stored
    else:
        return False

    # Re-canonicalize stored list through ResourceSpec when possible.
    try:
        stored_resources = [ResourceSpec.model_validate(_strip_non_shape(s)) for s in stored_list]
        stored_canon = resource_specs_to_canonical(stored_resources)
    except Exception:
        stored_canon = [_shape_only(s) for s in stored_list]

    new_canon = resource_specs_to_canonical(resources)
    return stored_canon == new_canon


def _strip_non_shape(item: dict[str, Any]) -> dict[str, Any]:
    """Keep fields needed to construct ResourceSpec for shape compare."""
    out: dict[str, Any] = {
        "name": item.get("name"),
        "type": item.get("type"),
    }
    for k in ("size", "count", "contiguous", "port_names"):
        if k in item and item[k] is not None:
            out[k] = item[k]
    # ResourceSpec validators may need defaults for missing optional fields.
    return out


def _shape_only(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": item.get("name"),
        "type": item.get("type"),
    }
    t = item.get("type")
    if t == "block":
        out["size"] = item.get("size")
    if t == "count":
        out["count"] = item.get("count")
        out["contiguous"] = bool(item.get("contiguous", False))
        if item.get("port_names") is not None:
            out["port_names"] = item.get("port_names")
    return out
