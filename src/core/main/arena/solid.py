# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Concrete arena implementations with collision shapes."""
from __future__ import annotations

from core.main.arena.base import Arena, BoundaryGrid
from core.main.arena.placement_mixin import PlacementMixin
from core.main.arena.runtime_mixin import RuntimeMixin
from core.util.bodies.shapes3D import Shape3DFactory
from core.util.geometry_utils.vector3D import Vector3D
from core.util.hierarchy_overlay import Bounds2D
from core.util.logging_util import get_logger

logger = get_logger("arena")


class SolidArena(RuntimeMixin, PlacementMixin, Arena):
    """Arena with a bounded shape used for collisions and spawning."""

    def __init__(self, config_elem):
        """Initialize the instance."""
        super().__init__(config_elem)
        self._grid_origin = None
        self._grid_cell_size = None
        self._boundary_grid: BoundaryGrid | None = None
        self.shape = self._build_arena_shape(config_elem)
        self._update_hierarchy_from_shape()

    def _build_arena_shape(self, config_elem):
        """Return the collision shape based on the arena configuration."""
        shape_type = self._arena_shape_type()
        shape_cfg = self._arena_shape_config(config_elem)
        return Shape3DFactory.create_shape("arena", shape_type, shape_cfg)

    def _arena_shape_type(self):
        """Return the default shape id used for the arena."""
        return self._id

    def _arena_shape_config(self, config_elem):
        """Return the arena configuration passed to the shape factory."""
        shape_cfg = dict(config_elem.arena.get("dimensions", {}))
        shape_cfg["color"] = config_elem.arena.get("color", "gray")
        return shape_cfg

    def get_shape(self):
        """Return the shape."""
        return self.shape

    def initialize(self):
        """Initialize the component state."""
        super().initialize()
        min_v = self.shape.min_vert()
        max_v = self.shape.max_vert()
        rng = self.random_generator
        self._grid_origin = Vector3D(min_v.x, min_v.y, 0)
        radii_map, max_radius = self._compute_entity_radii()
        self._grid_cell_size = max(max_radius * 2.0, 0.05)
        self._boundary_grid = BoundaryGrid(min_v, max_v, self._grid_cell_size)
        occupancy = {}
        for (config, entities) in self.objects.values():
            spawn_cfg = {}
            if isinstance(config, dict):
                if "spawn" in config and isinstance(config.get("spawn"), dict):
                    spawn_cfg = config.get("spawn")
                elif "distribute" in config and isinstance(config.get("distribute"), dict):
                    spawn_cfg = config.get("distribute")
            n_entities = len(entities)
            for entity in entities:
                entity.set_position(Vector3D(999, 0, 0), False)
            for n in range(n_entities):
                entity = entities[n]
                if not entity.get_orientation_from_dict():
                    rand_angle = rng.uniform(0.0, 360.0)
                    entity.set_start_orientation(Vector3D(0, 0, rand_angle))

                placed = self._place_entity_random(
                    entity,
                    radii_map[id(entity)],
                    occupancy,
                    rng,
                    min_v,
                    max_v,
                    spawn_cfg,
                )
                if not placed:
                    raise Exception(f"Impossible to place object {entity.entity()} in the arena")

    def reset(self):
        """Reset the component state."""
        super().reset()
        min_vert = self.shape.min_vert() if self.shape is not None else None
        max_vert = self.shape.max_vert() if self.shape is not None else None
        min_v = self._clamp_vector_to_float_limits(min_vert) if min_vert is not None else None
        max_v = self._clamp_vector_to_float_limits(max_vert) if max_vert is not None else None
        if min_v is None or max_v is None:
            raise ValueError("Arena shape bounds unavailable")
        rng = self.random_generator
        if self.data_handling is not None:
            self.data_handling.close(self.agents_shapes)
        for (config, entities) in self.objects.values():
            n_entities = len(entities)
            for entity in entities:
                entity.set_position(Vector3D(999, 0, 0), False)
            for n in range(n_entities):
                entity = entities[n]
                entity.set_start_orientation(entity.get_start_orientation())
                if not entity.get_orientation_from_dict():
                    rand_angle = rng.uniform(0.0, 360.0)
                    entity.set_start_orientation(Vector3D(0, 0, rand_angle))
                position = entity.get_start_position()

                count = 0
                done = False
                shape_n = entity.get_shape()
                shape_type_n = entity.get_shape_type()
                while not done and count < 500:
                    done = True
                    rand_pos = Vector3D(
                        rng.uniform(min_v.x, max_v.x),
                        rng.uniform(min_v.y, max_v.y),
                        position.z,
                    )
                    entity.to_origin()
                    entity.set_position(rand_pos)
                    shape_n = entity.get_shape()
                    if shape_n.check_overlap(self.shape)[0]:
                        done = False
                    if done:
                        for m in range(n_entities):
                            if m == n:
                                continue
                            other_entity = entities[m]
                            other_shape = other_entity.get_shape()
                            other_shape_type = other_entity.get_shape_type()
                            if shape_type_n == other_shape_type and shape_n.check_overlap(other_shape)[0]:
                                done = False
                                break
                    count += 1
                    if done:
                        entity.set_start_position(rand_pos)
                if not done:
                    raise Exception(f"Impossible to place object {entity.entity()} in the arena")

    def _update_hierarchy_from_shape(self):
        """Update hierarchy from shape."""
        bounds = None
        if hasattr(self, "shape") and self.shape is not None:
            min_vert = self.shape.min_vert()
            max_vert = self.shape.max_vert()
            min_v = self._clamp_vector_to_float_limits(min_vert) if min_vert is not None else None
            max_v = self._clamp_vector_to_float_limits(max_vert) if max_vert is not None else None
            if min_v is not None and max_v is not None:
                bounds = Bounds2D(min_v.x, min_v.y, max_v.x, max_v.y)
        self._hierarchy = self._create_hierarchy(bounds)
        if hasattr(self, "shape") and self.shape is not None and hasattr(self.shape, "metadata"):
            self.shape.metadata["hierarchy"] = self._hierarchy
            if self._hierarchy:
                self.shape.metadata["hierarchy_colors"] = getattr(self._hierarchy, "level_colors", {})
                self.shape.metadata["hierarchy_node_numbers"] = {
                    node_id: node.order for node_id, node in self._hierarchy.nodes.items()
                }
