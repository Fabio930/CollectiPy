from __future__ import annotations

from typing import Any

from core.util.geometry_utils.vector3D import Vector3D


def _entity_index(entity: Any) -> int | None:
    """Return numeric entity index if available."""
    raw_id = getattr(entity, "_id", None)
    if raw_id is None:
        return None
    try:
        idx = int(raw_id)
    except (TypeError, ValueError):
        return None
    if idx < 0:
        return None
    return idx


def get_explicit_position(entity: Any, fallback_z: float | None = None) -> Vector3D | None:
    """Return explicit spawn position for an entity if configured."""
    cfg = getattr(entity, "config_elem", {})
    if not isinstance(cfg, dict):
        return None
    positions = cfg.get("position")
    if not isinstance(positions, list):
        return None
    idx = _entity_index(entity)
    if idx is None or idx >= len(positions):
        return None
    entry = positions[idx]
    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
        return None
    try:
        x = float(entry[0])
        y = float(entry[1])
    except (TypeError, ValueError):
        return None
    z_val = None
    if len(entry) >= 3 and entry[2] is not None:
        try:
            z_val = float(entry[2])
        except (TypeError, ValueError):
            z_val = None
    if z_val is None:
        z_val = fallback_z if fallback_z is not None else 0.0
    return Vector3D(x, y, z_val)


def get_explicit_orientation(entity: Any) -> float | None:
    """Return explicit orientation angle (Z) for an entity if configured."""
    cfg = getattr(entity, "config_elem", {})
    if not isinstance(cfg, dict):
        return None
    orientations = cfg.get("orientation")
    if not isinstance(orientations, list):
        return None
    idx = _entity_index(entity)
    if idx is None or idx >= len(orientations):
        return None
    angle = orientations[idx]
    if angle is None:
        return None
    try:
        return float(angle)
    except (TypeError, ValueError):
        return None
