# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""EntityManager initialisation helpers (central placement, per-manager seeding)."""

from __future__ import annotations

import math
from random import Random

from core.entities.agents import make_agent_seed
from core.util.geometry_utils.vector3D import Vector3D
from core.util.logging_util import get_logger
from core.util.pose_utils import get_explicit_orientation, get_explicit_position

logger = get_logger("entity_manager")


def _base_seed(config, random_seed: int):
    """Return the seed agents of a group derive from: the group's own seed, or the run seed."""
    configured = config.get("random_seed") if isinstance(config, dict) else None
    return random_seed if configured is None else configured


def compute_spawn_poses(manager, random_seed: int, objects: dict) -> dict:
    """
    Place every agent of the simulation in a single pass.

    `manager` owns all the agents (not just one block), so overlaps are checked
    against objects and every other agent, and the result does not depend on how
    agents are later split across manager processes.

    Returns {"groups": {group: (cx, cy, radius, distribution, parameters)},
             "poses": {agent_name: (x, y, z, position_from_config,
                                    orientation_z, orientation_from_config)}}.
    """
    logger.info("Placing agents with random seed %s", random_seed)
    # Shapes already in the arena: objects first, then agents as they are placed.
    placed = [
        (shape, manager._estimate_entity_radius(shape))
        for payload in objects.values()
        for shape in payload[0]
    ]

    # Track group-level spawn disks (center, radius) to reduce overlap.
    group_spawn_specs = []

    # Global arena metrics used for spawn defaults.
    width = manager._global_max.x - manager._global_min.x
    height = manager._global_max.y - manager._global_min.y
    unbounded = bool(manager.wrap_config and manager.wrap_config.get("unbounded"))

    def _estimate_spawn_radius() -> float:
        """Return a default spawn radius from arena size or shape radius."""
        getter = getattr(manager.arena_shape, "get_radius", None)
        if callable(getter):
            try:
                r = getter()
                if isinstance(r, (int, float)) and r > 0:
                    return float(r)
            except Exception:
                pass
        if unbounded:
            radius = max(width, height)
        else:
            radius = min(width, height) / 2
        return max(0.1, radius)

    groups = {}
    poses = {}
    for group_key, (config, entities) in manager.agents.items():
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
            radius = _estimate_spawn_radius()
        else:
            try:
                radius = float(radius)
            except Exception:
                radius = _estimate_spawn_radius()

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
        groups[group_key] = (cx, cy, radius, distribution, spawn_params)

        center = Vector3D(cx, cy, 0.0)
        base_seed = _base_seed(config, random_seed)
        for entity in entities:
            # Dedicated stream: placement never consumes the agent's behaviour randomness.
            rng = Random(make_agent_seed(base_seed, f"{entity.entity_type}|spawn", int(entity._id)))
            orientation_z = get_explicit_orientation(entity)
            orientation_from_config = orientation_z is not None
            if orientation_z is None:
                orientation_z = rng.uniform(-180.0, 180.0)
            shape = entity.get_shape()
            entity_radius = manager._estimate_entity_radius(shape)
            bounds = manager._placement_bounds(entity)
            # Height of the center above the floor, wherever the shape currently is.
            rest_z = shape.center_of_mass().z - shape.min_vert().z

            explicit_position = get_explicit_position(entity, rest_z)
            spawn_point = explicit_position
            placed_ok = False
            if spawn_point is not None:
                placed_ok = not manager._is_overlapping_spawn(placed, entity, entity_radius, spawn_point)
                if not placed_ok:
                    logger.warning(
                        "%s explicit position %s overlaps or exits bounds; using spawn sampling",
                        entity.get_name(),
                        (spawn_point.x, spawn_point.y, spawn_point.z),
                    )
            from_config = placed_ok
            if not placed_ok:
                for _ in range(manager.PLACEMENT_MAX_ATTEMPTS):
                    spawn_point = manager._sample_spawn_point(
                        rng, center, radius, distribution, bounds, rest_z, spawn_params
                    )
                    if not manager._is_overlapping_spawn(placed, entity, entity_radius, spawn_point):
                        placed_ok = True
                        break
            if not placed_ok:
                # If we couldn't find a free spot, just place it at the last sampled point.
                logger.warning(
                    "%s could not find non-overlapping spawn after %d attempts",
                    entity.get_name(),
                    manager.PLACEMENT_MAX_ATTEMPTS,
                )

            entity.set_position(spawn_point)
            if not unbounded:
                manager._clamp_to_arena(entity)
            position = entity.get_position()
            poses[entity.get_name()] = (
                position.x,
                position.y,
                position.z,
                from_config,
                orientation_z,
                orientation_from_config,
            )
            placed.append((shape, entity_radius))

    logger.info("Agents placed: %d", len(poses))
    return {"groups": groups, "poses": poses}


def initialize_entities(manager, random_seed: int, spawn: dict) -> None:
    """Initialize this manager's entities at the beginning of a run with the centrally computed poses."""
    logger.info("Initializing agents with random seed %s", random_seed)
    groups = spawn["groups"]
    poses = spawn["poses"]

    for group_key, (config, entities) in manager.agents.items():
        cx, cy, radius, distribution, spawn_params = groups[group_key]
        base_seed = _base_seed(config, random_seed)

        for entity in entities:
            # Deterministic per-agent seed that depends on the run seed.
            entity.random_generator.seed(make_agent_seed(base_seed, entity.entity_type, int(entity._id)))
            entity.reset()

            # Per-entity spawn params used by movement models (e.g. random_way_point).
            entity.spawn_params = (Vector3D(cx, cy, 0.0), radius, distribution)
            entity.spawn_parameters = spawn_params

            x, y, z, from_config, orientation_z, orientation_from_config = poses[entity.get_name()]
            entity.position_from_dict = from_config
            entity.orientation_from_dict = orientation_from_config
            orientation_vec = Vector3D(0.0, 0.0, orientation_z)

            entity.set_start_position(Vector3D(x, y, z))
            entity.set_start_orientation(orientation_vec)
            shape = entity.get_shape()
            if shape is not None:
                # Attachments only follow the body when explicitly moved.
                shape.translate_attachments(orientation_vec.z)

    logger.info("Entities initialized")
