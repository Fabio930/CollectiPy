# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""EntityManager initialisation helpers (placement, seeding)."""

from __future__ import annotations

import math
from core.util.geometry_utils.vector3D import Vector3D
from core.util.logging_util import get_logger
from core.util.pose_utils import get_explicit_orientation, get_explicit_position

logger = get_logger("entity_manager")


def initialize_entities(manager, random_seed: int, objects: dict) -> None:
    """Initialize entities at the beginning of a run."""
    logger.info("Initializing agents with random seed %s", random_seed)
    seed_counter = 0
    placed_shapes = []

    # Track group-level spawn disks (center, radius) to reduce overlap.
    group_spawn_specs = []

    # Move everything far away before placement.
    for (_, entities) in manager.agents.values():
        for entity in entities:
            entity.set_position(Vector3D(999, 0, 0), False)

    # Global arena metrics used for spawn defaults.
    width = manager._global_max.x - manager._global_min.x
    height = manager._global_max.y - manager._global_min.y
    unbounded = bool(manager.wrap_config and manager.wrap_config.get("unbounded"))

    def _estimate_spawn_radius(entity) -> float:
        """Return a default spawn radius from arena size or shape radius."""
        getter = getattr(manager.arena_shape, "get_radius", None)
        if callable(getter):
            try:
                r = getter()
                if isinstance(r, (int, float)) and r > 0:
                    return float(r)
            except Exception:
                pass
        if manager.wrap_config and manager.wrap_config.get("unbounded"):
            radius = max(width, height)
        else:
            radius = min(width, height) / 2
        return max(0.1, radius)

    for (_, (config, entities)) in manager.agents.items():
        # Group-level spawn configuration: center, radius, distribution.
        spawn_cfg = config.get("spawn", {}) if isinstance(config, dict) else {}
        center_spec = spawn_cfg.get("center", [0.0, 0.0])
        radius = spawn_cfg.get("radius", None)
        distribution = spawn_cfg.get("distribution", "uniform")
        spawn_params = spawn_cfg.get("parameters", {}) if isinstance(spawn_cfg.get("parameters"), dict) else {}

        try:
            cx = float(center_spec[0])
            cy = float(center_spec[1])
        except Exception:
            cx = cy = 0.0

        if radius is None:
            radius = _estimate_spawn_radius(entities[0] if entities else None)
        else:
            try:
                radius = float(radius)
            except Exception:
                radius = _estimate_spawn_radius(entities[0] if entities else None)

        # Try to separate spawn disks of different groups if they overlap.
        for (pcx, pcy, pr) in group_spawn_specs:
            dx = cx - pcx
            dy = cy - pcy
            dist = math.hypot(dx, dy)
            min_dist = (radius + pr) * 0.7
            if dist < min_dist and dist > 0:
                # Shift away by a small factor to reduce overlap.
                scale = (min_dist - dist) / dist
                cx += dx * scale
                cy += dy * scale
        group_spawn_specs.append((cx, cy, radius))

        # Per-entity initialisation (random generator, reset, spawn params).
        for entity in entities:
            # Deterministic per-agent seed that depends on the run seed.
            seed_counter += 1
            if hasattr(entity, "random_generator"):
                try:
                    seed = entity._configured_seed if getattr(entity, "_configured_seed", None) is not None else None
                except Exception:
                    seed = None
                if seed is None:
                    try:
                        seed = entity.config_elem.get("random_seed")
                    except Exception:
                        seed = None
                if seed is None:
                    try:
                        seed = entity.make_agent_seed(random_seed, entity.entity_type, int(entity._id))  # type: ignore[attr-defined]
                    except Exception:
                        seed = random_seed + seed_counter
                try:
                    entity.random_generator.seed(seed)
                except Exception:
                    pass

            entity.reset()

            # Per-entity spawn params used by movement models (e.g. random_way_point).
            entity.spawn_params = (Vector3D(cx, cy, 0.0), radius, distribution)
            entity.spawn_parameters = spawn_params

            shape_ref = entity.get_shape()
            fallback_z = abs(shape_ref.min_vert().z) if shape_ref is not None else 0.0
            explicit_position = get_explicit_position(entity, fallback_z)
            spawn_point = explicit_position
            placed_ok = False
            if spawn_point is not None:
                if not manager._is_overlapping_spawn(placed_shapes, entity, spawn_point):
                    placed_ok = True
                else:
                    logger.warning(
                        "%s explicit position %s overlaps or exits bounds; using spawn sampling",
                        entity.get_name(),
                        (spawn_point.x, spawn_point.y, spawn_point.z),
                    )
                    spawn_point = None
            if not placed_ok:
                spawn_point = manager._sample_spawn_point(
                    entity,
                    Vector3D(cx, cy, 0.0),
                    radius,
                    distribution,
                    manager._placement_bounds(entity, unbounded),
                )
                for _ in range(manager.PLACEMENT_MAX_ATTEMPTS):
                    overlap = manager._is_overlapping_spawn(placed_shapes, entity, spawn_point)
                    if not overlap:
                        placed_ok = True
                        break
                    spawn_point = manager._sample_spawn_point(
                        entity,
                        Vector3D(cx, cy, 0.0),
                        radius,
                        distribution,
                        manager._placement_bounds(entity, unbounded),
                    )

            if not placed_ok and spawn_point is not None:
                # If we couldn't find a free spot, just place it at the last sampled point.
                logger.warning(
                    "%s could not find non-overlapping spawn after %d attempts",
                    entity.get_name(),
                    manager.PLACEMENT_MAX_ATTEMPTS,
                )

            entity.position_from_dict = explicit_position is not None
            explicit_orientation = get_explicit_orientation(entity)
            entity.orientation_from_dict = explicit_orientation is not None
            if explicit_orientation is not None:
                orientation_vec = Vector3D(0.0, 0.0, explicit_orientation)
            else:
                orientation_vec = entity.get_start_orientation() or Vector3D()

            entity.set_start_position(spawn_point)
            entity.set_start_orientation(orientation_vec)
            entity.set_position(spawn_point)
            entity.set_orientation(orientation_vec)

            # Keep a copy of the shape for overlap checks.
            shape = entity.get_shape()
            if shape is not None:
                shape.translate(spawn_point)
                placed_shapes.append(shape)

        # Clamp group after placement to ensure within arena bounds if bounded.
        for entity in entities:
            if not unbounded:
                manager._clamp_to_arena(entity)
                manager._apply_wrap(entity)

    # Update object positions with arena broadcast.
    for object_type, objects_tuple in objects.items():
        try:
            obj_config, obj_list = objects_tuple
        except Exception:
            continue
        if obj_list is None:
            continue
        for idx, obj in enumerate(obj_list):
            try:
                obj_config_for_idx = obj_config if isinstance(obj_config, dict) else {}
                orient = obj_config_for_idx.get("orientation")
                if orient:
                    try:
                        vec = Vector3D(orient[idx][0], orient[idx][1], orient[idx][2])
                    except Exception:
                        vec = Vector3D(orient[-1][0], orient[-1][1], orient[-1][2])
                    obj.set_orientation(vec)
            except Exception:
                continue

    logger.info("Entities initialized (seed_counter=%s)", seed_counter)
