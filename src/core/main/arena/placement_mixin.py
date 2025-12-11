# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Placement and boundary utilities for arenas."""
from __future__ import annotations

import math
from typing import Any, TYPE_CHECKING

from core.main.arena.base import BOUNDARY_RADIUS_EPS, FLOAT_MAX, FLOAT_MIN
from core.util.geometry_utils.vector3D import Vector3D

if TYPE_CHECKING:
    from typing import Protocol

    class _PlacementMixinProps(Protocol):
        objects: dict[Any, Any]
        shape: Any
        _boundary_grid: Any
        _grid_cell_size: float | None
        _grid_origin: Vector3D | None
else:
    _PlacementMixinProps = object


class PlacementMixin(_PlacementMixinProps):
    """Helper methods for spawning entities and boundary checks."""

    _boundary_grid: Any

    @staticmethod
    def _estimate_shape_radius(shape) -> float:
        """Estimate a conservative radius for a shape."""
        if shape is None:
            return 0.0
        getter = getattr(shape, "get_radius", None)
        if callable(getter):
            try:
                candidate = getter()
                if isinstance(candidate, (int, float)):
                    r = float(candidate)
                    if r > 0:
                        return r
            except Exception:
                pass
        center = getattr(shape, "center", None)
        vertices = getattr(shape, "vertices_list", None)
        if center is not None and vertices:
            try:
                return max(
                    math.sqrt((v.x - center.x) ** 2 + (v.y - center.y) ** 2 + (v.z - center.z) ** 2)
                    for v in vertices
                )
            except Exception:
                pass
        return 0.05

    def _margin_to_float_limits(self, center: Vector3D) -> float:
        """Return the smallest remaining distance from center to float limits."""
        return min(
            FLOAT_MAX - center.x,
            center.x - FLOAT_MIN,
            FLOAT_MAX - center.y,
            center.y - FLOAT_MIN,
            FLOAT_MAX - center.z,
            center.z - FLOAT_MIN,
        )

    def _find_float_limit_violation(self, agents_shapes: dict | None, objects_data: dict | None = None) -> tuple | None:
        """
        Inspect agent and object centers near boundary strips; trigger when
        margin to float limits is smaller than (radius + epsilon).
        """
        if not isinstance(agents_shapes, dict):
            agents_shapes = None
        if agents_shapes:
            for group_key, shapes in agents_shapes.items():
                if not shapes:
                    continue
                for idx, shape in enumerate(shapes):
                    try:
                        center = getattr(shape, "center", None)
                        if center is None:
                            continue
                        band = self._boundary_grid.band_for_point(center) if self._boundary_grid else 2
                        if band == 0:
                            continue
                        radius = self._estimate_shape_radius(shape)
                        margin = self._margin_to_float_limits(center)
                        if margin <= radius + BOUNDARY_RADIUS_EPS:
                            return ("agent", group_key, idx, "center", (center.x, center.y, center.z), margin, radius)
                    except Exception:
                        continue
        if isinstance(objects_data, dict):
            for group_key, payload in objects_data.items():
                if not isinstance(payload, (list, tuple)) or not payload:
                    continue
                shapes = payload[0] if len(payload) > 0 else []
                positions = payload[1] if len(payload) > 1 else []
                radii_cache = []
                if shapes:
                    for shape in shapes:
                        radii_cache.append(self._estimate_shape_radius(shape))
                if shapes:
                    for idx, shape in enumerate(shapes):
                        try:
                            center = getattr(shape, "center", None)
                            if center is None:
                                continue
                            band = self._boundary_grid.band_for_point(center) if self._boundary_grid else 2
                            if band == 0:
                                continue
                            radius = radii_cache[idx] if idx < len(radii_cache) else self._estimate_shape_radius(shape)
                            margin = self._margin_to_float_limits(center)
                            if margin <= radius + BOUNDARY_RADIUS_EPS:
                                return ("object", group_key, idx, "center", (center.x, center.y, center.z), margin, radius)
                        except Exception:
                            continue
                if positions:
                    for idx, pos in enumerate(positions):
                        try:
                            band = self._boundary_grid.band_for_point(pos) if self._boundary_grid else 2
                            if band == 0:
                                continue
                            radius = radii_cache[idx] if idx < len(radii_cache) else 0.0
                            margin = self._margin_to_float_limits(pos)
                            if margin <= radius + BOUNDARY_RADIUS_EPS:
                                return ("object", group_key, idx, "position", (pos.x, pos.y, pos.z), margin, radius)
                        except Exception:
                            continue
        return None

    def _compute_entity_radii(self):
        """Compute entity radii."""
        radii = {}
        max_radius = 0.0
        for (_, entities) in self.objects.values():
            for entity in entities:
                entity.to_origin()
                shape = entity.get_shape()
                radius = self._estimate_shape_radius(shape)
                radii[id(entity)] = radius
                max_radius = max(max_radius, radius)
        return radii, max_radius if max_radius > 0 else 0.1

    def _place_entity_random(self, entity, radius, occupancy, rng, min_v, max_v, spawn_cfg=None):
        """Place entity random (optionally honoring spawn configuration)."""
        attempts = 0
        shape_n = entity.get_shape()
        min_vert_z = abs(shape_n.min_vert().z)
        effective_radius = radius * PLACEMENT_MARGIN_FACTOR + PLACEMENT_MARGIN_EPS
        min_x = min_v.x + effective_radius
        max_x = max_v.x - effective_radius
        min_y = min_v.y + effective_radius
        max_y = max_v.y - effective_radius
        if min_x >= max_x or min_y >= max_y:
            return False
        while attempts < PLACEMENT_MAX_ATTEMPTS:
            rand_pos = self._sample_spawn_position(spawn_cfg, rng, min_x, max_x, min_y, max_y, min_vert_z, effective_radius)
            entity.to_origin()
            entity.set_position(rand_pos)
            shape = entity.get_shape()
            if shape.check_overlap(self.shape)[0]:
                attempts += 1
                continue
            if self._shape_overlaps_grid(shape, rand_pos, radius, occupancy):
                attempts += 1
                continue
            entity.set_start_position(rand_pos)
            self._register_shape_in_grid(shape, rand_pos, radius, occupancy)
            return True
        return False

    def _sample_spawn_position(self, spawn_cfg, rng, min_x, max_x, min_y, max_y, z, fallback_radius):
        """Sample a spawn position using optional spawn configuration."""
        if isinstance(spawn_cfg, dict) and spawn_cfg:
            center_spec = spawn_cfg.get("center", [0.0, 0.0])
            if not isinstance(center_spec, (list, tuple)) or len(center_spec) < 2:
                center_spec = [0.0, 0.0]
            cx = float(center_spec[0])
            cy = float(center_spec[1])
            radius_val = spawn_cfg.get("radius", None)
            try:
                radius_val = float(radius_val) if radius_val is not None else None
            except (TypeError, ValueError):
                radius_val = None
            if radius_val is None:
                # Default to the largest inscribed circle of the arena footprint.
                radius_val = max(0.0, min(max_x - min_x, max_y - min_y) / 2.0)
            distribution = str(spawn_cfg.get("distribution", "uniform")).strip().lower()
            params = spawn_cfg.get("parameters", {}) if isinstance(spawn_cfg.get("parameters"), dict) else {}
            if distribution in {"gaussian", "normal"}:
                std = params.get("std") or params.get("sigma") or (radius_val / 3.0 if radius_val > 0 else fallback_radius)
                try:
                    std = float(std)
                except (TypeError, ValueError):
                    std = radius_val / 3.0 if radius_val > 0 else fallback_radius
                x = rng.gauss(cx, std)
                y = rng.gauss(cy, std)
            elif distribution in {"exp", "exponential"}:
                scale = params.get("scale") or params.get("lambda")
                try:
                    scale = float(scale) if scale is not None else radius_val / 2.0
                except (TypeError, ValueError):
                    scale = radius_val / 2.0
                r = -math.log(max(1e-9, 1.0 - rng.random())) * max(scale, 1e-6)
                theta = rng.uniform(0.0, 2 * math.pi)
                x = cx + r * math.cos(theta)
                y = cy + r * math.sin(theta)
            else:
                r = math.sqrt(rng.uniform(0.0, 1.0)) * radius_val
                theta = rng.uniform(0.0, 2 * math.pi)
                x = cx + r * math.cos(theta)
                y = cy + r * math.sin(theta)
            # Keep inside arena bounds.
            x = min(max(x, min_x), max_x)
            y = min(max(y, min_y), max_y)
            return Vector3D(x, y, z)
        return Vector3D(
            rng.uniform(min_x, max_x),
            rng.uniform(min_y, max_y),
            z,
        )

    def _place_entity_at_point(self, entity, position, radius, occupancy):
        """Place entity at the provided explicit position if it fits."""
        if position is None:
            return False
        entity.to_origin()
        entity.set_position(position)
        shape = entity.get_shape()
        if shape is None:
            return False
        if shape.check_overlap(self.shape)[0]:
            return False
        if self._shape_overlaps_grid(shape, position, radius, occupancy):
            return False
        entity.set_start_position(position)
        self._register_shape_in_grid(shape, position, radius, occupancy)
        return True

    def _shape_overlaps_grid(self, shape, position, radius, occupancy):
        """Return True if the shape overlaps occupied grid cells."""
        if not occupancy:
            return False
        cells = self._cells_for_shape(position, radius, pad=1)
        checked = set()
        for cell in cells:
            if cell in checked:
                continue
            checked.add(cell)
            for other_shape, other_radius in occupancy.get(cell, []):
                center_delta = Vector3D(
                    shape.center.x - other_shape.center.x,
                    shape.center.y - other_shape.center.y,
                    0,
                )
                if center_delta.magnitude() >= (radius + other_radius):
                    continue
                if shape.check_overlap(other_shape)[0]:
                    return True
        return False

    def _register_shape_in_grid(self, shape, position, radius, occupancy):
        """Register shape in grid."""
        cells = self._cells_for_shape(position, radius)
        for cell in cells:
            occupancy.setdefault(cell, []).append((shape, radius))

    def _cells_for_shape(self, position, radius, pad: int = 0):
        """Return grid cells covering a shape footprint."""
        if self._grid_cell_size is None or self._grid_cell_size <= 0:
            return [(0, 0)]
        origin = self._grid_origin or Vector3D()
        cell_size = self._grid_cell_size
        min_x = int(math.floor((position.x - radius - origin.x) / cell_size)) - pad
        max_x = int(math.floor((position.x + radius - origin.x) / cell_size)) + pad
        min_y = int(math.floor((position.y - radius - origin.y) / cell_size)) - pad
        max_y = int(math.floor((position.y + radius - origin.y) / cell_size)) + pad
        cells = []
        for cx in range(min_x, max_x + 1):
            for cy in range(min_y, max_y + 1):
                cells.append((cx, cy))
        return cells


PLACEMENT_MAX_ATTEMPTS = 200
PLACEMENT_MARGIN_FACTOR = 1.3
PLACEMENT_MARGIN_EPS = 0.002
