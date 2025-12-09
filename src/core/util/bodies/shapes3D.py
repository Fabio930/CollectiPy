# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

from __future__ import annotations

import math
from core.util.geometry_utils.vector3D import Vector3D

_PI = math.pi


def _merge_dimension_config(config_elem: dict) -> dict:
    """Merge the explicit dimension block into the flat config copy."""
    merged = dict(config_elem) if config_elem else {}
    dimensions = merged.pop("dimensions", None)
    if isinstance(dimensions, dict):
        for key, value in dimensions.items():
            if value is not None:
                merged[key] = value
    return merged


def _resolve_dimension(config_elem: dict, name: str, fallback: str | None = None, fallback_scale: float = 1.0, default: float = 1.0) -> float:
    """Return the requested dimension, using fallback (with scale) or default."""
    value = config_elem.get(name)
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    if fallback:
        value = config_elem.get(fallback)
        if value is not None:
            try:
                return float(value) * fallback_scale
            except (TypeError, ValueError):
                pass
    return default
class Shape3DFactory:
    """Shape 3 d factory."""

    @staticmethod
    def _normalize_cuboid_config(shape_type: str, config_elem: dict) -> dict:
        """
        Ensure consistent dimension fields for cuboid-derived shapes.
        - square: width = depth = (side|depth|width|height|1), height defaults to the same if missing
        - cube:   width = depth = height = (side|depth|width|height|1)
        - cuboid: fill any missing width/depth/height with the first available numeric dimension
        """
        cfg = dict(config_elem) if config_elem else {}
        def _to_float(val):
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        width = _to_float(cfg.get("width"))
        depth = _to_float(cfg.get("depth"))
        height = _to_float(cfg.get("height"))
        side = _to_float(cfg.get("side"))

        base = next((v for v in (side, depth, width, height) if v is not None), 1.0)

        if shape_type == "cube":
            width = depth = height = base
        elif shape_type == "square":
            side_val = side if side is not None else base
            width = depth = side_val
            if height is None:
                height = side_val
        else:  # cuboid or rectangle
            if width is None and depth is not None:
                width = depth
            if depth is None and width is not None:
                depth = width
            if width is None:
                width = base
            if depth is None:
                depth = base
            if height is None:
                height = base

        cfg["width"] = width
        cfg["depth"] = depth
        cfg["height"] = height
        if side is not None:
            cfg["side"] = side
        return cfg

    @staticmethod
    def create_shape(_object:str, shape_type:str, config_elem:dict):
        """Create shape."""
        normalized_cfg = _merge_dimension_config(config_elem)
        if shape_type == "sphere":
            return Sphere(_object, shape_type, normalized_cfg)
        elif shape_type == "unbounded":
            return UnboundedShape(_object, shape_type, normalized_cfg)
        elif shape_type in ("square", "cube", "rectangle", "cuboid"):
            normalized_cfg = Shape3DFactory._normalize_cuboid_config(shape_type, normalized_cfg)
            return Cuboid(_object, shape_type, normalized_cfg)
        elif shape_type in ("circle", "cylinder"):
            return Cylinder(_object, shape_type, normalized_cfg)
        elif shape_type == "point" or shape_type == "none":
            return Shape(normalized_cfg)
        else:
            raise ValueError(f"Unknown shape type: {shape_type}")

class Shape:
    """Shape."""
    dense_shapes = ["sphere", "cube", "cuboid", "cylinder"]
    flat_shapes = ["circle", "square", "rectangle"]
    no_shapes = ["point", "none"]

    def __init__(self, config_elem:dict, center: Vector3D | None = None):
        """Initialize the instance."""
        center = center or Vector3D()
        self.center = Vector3D(center.x, center.y, center.z)
        self._object = "arena"
        self._id = "point"
        self._color = config_elem.get("color", "black")
        self.vertices_list = []
        self.attachments = []
        self.metadata: dict = {}

    def add_attachment(self, attachment):
        """Add attachment."""
        self.attachments.append(attachment)

    def get_attachments(self):
        """Return the attachments."""
        return self.attachments

    def translate_attachments(self, angle: float):
        """Translate the attachments."""
        if not self.attachments:
            return
        max_v = self.max_vert()
        angle_rad = math.radians(angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        cx, cy = self.center.x, self.center.y
        dx = max_v.x - cx - 0.01
        dy = max_v.y - cy - 0.01
        primary_x = dx * cos_a
        primary_y = dy * -sin_a
        for attachment in self.attachments:
            placement = attachment.metadata.get("placement")
            if placement == "opposite":
                target_x = cx - primary_x
                target_y = cy - primary_y
            else:
                target_x = cx + primary_x
                target_y = cy + primary_y
            attachment.translate(Vector3D(target_x, target_y, max_v.z))

    def color(self) -> str:
        """Return the configured color."""
        return self._color

    def set_color(self, color: str):
        """Set the color."""
        self._color = color

    def center_of_mass(self) -> Vector3D:
        """Center of mass."""
        return self.center

    def vertices(self) -> list:
        """Return the shape vertices."""
        return self.vertices_list

    def translate(self, new_center: Vector3D):
        """Translate the shape in space."""
        self.center = new_center
        self.set_vertices()

    def get_radius(self) -> float:
        """Return the radius."""
        return 0

    def set_vertices(self):
        """Set the vertices."""
        pass

    def check_overlap(self, _shape):
        """Check overlap."""
        for vertex in self.vertices_list:
            if _shape._object == "arena":
                if not self._is_point_inside_shape(vertex, _shape):
                    return True, vertex
            else:
                if self._is_point_inside_shape(vertex, _shape):
                    return True, vertex
        for vertex in _shape.vertices_list:
            if self._is_point_inside_shape(vertex, self):
                return True, vertex
        return False, Vector3D()

    def _get_random_point_inside_shape(self, random_generator, arena_shape):
        """Return the random point inside shape."""
        if isinstance(arena_shape, (Cylinder, Sphere)):
            angle = random_generator.uniform(0, 2 * _PI)
            r = arena_shape.radius * math.sqrt(random_generator.uniform(0, 1))
            x = arena_shape.center.x + r * math.cos(angle)
            y = arena_shape.center.y + r * math.sin(angle)
            z = arena_shape.center.z
            return Vector3D(x, y, z)
        else:
            min_v = arena_shape.min_vert()
            max_v = arena_shape.max_vert()
            if isinstance(self, (Cylinder, Sphere)):
                tmp = self.get_radius()
                min_v += Vector3D(tmp, tmp, tmp)
                max_v -= Vector3D(tmp, tmp, tmp)
            else:
                tmp = self.center - self.max_vert()
                min_v += tmp
                max_v -= tmp
            return Vector3D(
                random_generator.uniform(min_v.x, max_v.x),
                random_generator.uniform(min_v.y, max_v.y),
                random_generator.uniform(min_v.z, max_v.z)
            )

    def _is_point_inside_shape(self, point, shape):
        """Is point inside shape."""
        if isinstance(shape, Cylinder):
            dx = point.x - shape.center.x
            dy = point.y - shape.center.y
            dz = point.z - shape.center.z
            distance = math.sqrt(dx * dx + dy * dy + dz * dz)
            return distance <= shape.radius
        else:
            min_v = shape.min_vert()
            max_v = shape.max_vert()
            return (min_v.x <= point.x <= max_v.x and
                    min_v.y <= point.y <= max_v.y and
                    min_v.z <= point.z <= max_v.z)

    def rotate(self, angle_z: float):
        """Rotate the shape."""
        angle_rad_z = math.radians(angle_z)
        if angle_rad_z > 0:
            cos_z = math.cos(angle_rad_z)
            sin_z = math.sin(angle_rad_z)
            cx, cy = self.center.x, self.center.y
            for vertex in self.vertices_list:
                # Ottimizza la rotazione solo sul piano XY
                x_shift = vertex.x - cx
                y_shift = vertex.y - cy
                x_new = cx + x_shift * cos_z - y_shift * sin_z
                y_new = cy + x_shift * sin_z + y_shift * cos_z
                vertex.x, vertex.y = x_new, y_new

    def min_vert(self):
        # Usa min/max con generator expression per efficienza
        """Min vert."""
        if not self.vertices_list:
            return Vector3D()
        return Vector3D(
            min(v.x for v in self.vertices_list),
            min(v.y for v in self.vertices_list),
            min(v.z for v in self.vertices_list)
        )

    def max_vert(self):
        """Max vert."""
        if not self.vertices_list:
            return Vector3D()
        return Vector3D(
            max(v.x for v in self.vertices_list),
            max(v.y for v in self.vertices_list),
            max(v.z for v in self.vertices_list)
        )

class Sphere(Shape):
    """Sphere."""
    def __init__(self, _object: str, shape_type: str, config_elem: dict, center: Vector3D | None = None):
        """Initialize the instance."""
        super().__init__(config_elem=config_elem, center=center)
        self._object = _object
        self._id = shape_type
        self.radius = _resolve_dimension(config_elem, "radius", fallback="diameter", fallback_scale=0.5, default=1.0)
        self.set_vertices()

    def volume(self):
        """Compute the enclosed volume."""
        return (4 / 3) * _PI * self.radius ** 3

    def get_radius(self) -> float:
        """Return the radius."""
        return self.radius

    def surface_area(self):
        """Surface area."""
        return 4 * _PI * self.radius ** 2

    def set_vertices(self):
        """Set the vertices."""
        self.vertices_list = []
        num_vertices = 32
        cx, cy, cz = self.center.x, self.center.y, self.center.z
        r = self.radius
        for i in range(num_vertices):
            theta = 2 * _PI * (i / num_vertices)
            cos_theta = math.cos(theta)
            sin_theta = math.sin(theta)
            for j in range(num_vertices):
                phi = _PI * j / num_vertices
                sin_phi = math.sin(phi)
                x = cx + r * sin_phi * cos_theta
                y = cy + r * sin_phi * sin_theta
                z = cz + r * math.cos(phi)
                self.vertices_list.append(Vector3D(x, y, z))

class Cuboid(Shape):
    """Cuboid."""
    def __init__(self, _object: str, shape_type: str, config_elem: dict, center: Vector3D | None = None):
        """Initialize the instance."""
        super().__init__(config_elem=config_elem, center=center)
        self._object = _object
        self._id = shape_type
        self.width = config_elem.get("width", 1.0)
        self.height = config_elem.get("height", 1.0)
        self.depth = config_elem.get("depth", 1.0)
        self.set_vertices()

    def volume(self):
        """Compute the enclosed volume."""
        if self._id in Shape.flat_shapes:
            return self.width * self.depth
        else:
            return self.width * self.height * self.depth

    def surface_area(self):
        """Surface area."""
        if self._id in Shape.flat_shapes:
            return self.width * self.depth
        else:
            return 2 * (self.width * self.height + self.height * self.depth + self.depth * self.width)

    def set_vertices(self):
        """Set the vertices."""
        half_width = self.width * 0.5
        half_height = self.height * 0.5
        half_depth = self.depth * 0.5
        cx, cy, cz = self.center.x, self.center.y, self.center.z
        if self._object == "arena":
            self.vertices_list = [
                Vector3D(cx - half_width, cy - half_depth, 0),
                Vector3D(cx - half_width, cy - half_depth, self.height),
                Vector3D(cx + half_width, cy - half_depth, 0),
                Vector3D(cx + half_width, cy - half_depth, self.height),
                Vector3D(cx + half_width, cy + half_depth, 0),
                Vector3D(cx + half_width, cy + half_depth, self.height),
                Vector3D(cx - half_width, cy + half_depth, 0),
                Vector3D(cx - half_width, cy + half_depth, self.height)
            ]
        else:
            if self._id in Shape.flat_shapes:
                self.center.z = 0
                self.vertices_list = [
                    Vector3D(cx - half_width, cy - half_depth, 0),
                    Vector3D(cx + half_width, cy - half_depth, 0),
                    Vector3D(cx + half_width, cy + half_depth, 0),
                    Vector3D(cx - half_width, cy + half_depth, 0)
                ]
            else:
                self.vertices_list = [
                    Vector3D(cx - half_width, cy - half_depth, cz - half_height),
                    Vector3D(cx - half_width, cy - half_depth, cz + half_height),
                    Vector3D(cx + half_width, cy - half_depth, cz - half_height),
                    Vector3D(cx + half_width, cy - half_depth, cz + half_height),
                    Vector3D(cx + half_width, cy + half_depth, cz - half_height),
                    Vector3D(cx + half_width, cy + half_depth, cz + half_height),
                    Vector3D(cx - half_width, cy + half_depth, cz - half_height),
                    Vector3D(cx - half_width, cy + half_depth, cz + half_height)
                ]

class Cylinder(Shape):
    """Cylinder."""
    def __init__(self, _object: str, shape_type: str, config_elem: dict, center: Vector3D | None = None):
        """Initialize the instance."""
        super().__init__(config_elem=config_elem, center=center)
        self._object = _object
        self._id = shape_type
        self.radius = _resolve_dimension(config_elem, "radius", fallback="diameter", fallback_scale=0.5, default=1.0)
        self.height = _resolve_dimension(config_elem, "height", default=1.0)
        self.set_vertices()

    def volume(self):
        """Compute the enclosed volume."""
        return _PI * self.radius ** 2 * self.height

    def get_radius(self) -> float:
        """Return the radius."""
        return self.radius

    def surface_area(self):
        """Surface area."""
        return 2 * _PI * self.radius * (self.radius + self.height)

    def set_vertices(self):
        """Set the vertices."""
        self.vertices_list = []
        if self._object == "arena":
            # Higher resolution keeps agents from spawning outside when density is high.
            num_vertices = 52
            angle_increment = 2 * _PI / num_vertices
            cx, cy = self.center.x, self.center.y
            for i in range(num_vertices):
                angle = i * angle_increment
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                x = cx + self.radius * cos_a
                y = cy + self.radius * sin_a
                z1 = 0
                z2 = self.height
                self.vertices_list.append(Vector3D(x, y, z1))
                self.vertices_list.append(Vector3D(x, y, z2))
        else:
            num_vertices = 12 if self._object == "mark" else 20
            angle_increment = 2 * _PI / num_vertices
            cx, cy, cz = self.center.x, self.center.y, self.center.z
            if self._id in Shape.flat_shapes:
                self.center.z = 0
                for i in range(num_vertices):
                    angle = i * angle_increment
                    cos_a = math.cos(angle)
                    sin_a = math.sin(angle)
                    x = cx + self.radius * cos_a
                    y = cy + self.radius * sin_a
                    self.vertices_list.append(Vector3D(x, y, 0))
            else:
                half_height = self.height * 0.5
                last_x = cx + self.radius
                last_y = cy
                for i in range(num_vertices):
                    angle = i * angle_increment
                    cos_a = math.cos(angle)
                    sin_a = math.sin(angle)
                    last_x = cx + self.radius * cos_a
                    last_y = cy + self.radius * sin_a
                    self.vertices_list.append(Vector3D(last_x, last_y, cz - half_height))
                # Add the last pair of vertices using the final loop values.
                self.vertices_list.append(Vector3D(last_x, last_y, cz + half_height))


class UnboundedShape(Shape):
    """Shape representing an unbounded arena (large placeholder square)."""
    BOUND = 1e9

    def __init__(self, _object: str, shape_type: str, config_elem: dict, center: Vector3D | None = None):
        super().__init__(config_elem=config_elem, center=center)
        self._object = _object
        self._id = shape_type
        self.side = float(config_elem.get("side", self.BOUND * 2.0))
        self.set_vertices()

    def set_vertices(self):
        """Set four extreme vertices to approximate infinity."""
        half = min(self.BOUND, self.side * 0.5)
        b = half
        # Use a thin prism so z-bounds include tall objects.
        self.vertices_list = [
            Vector3D(-b, -b, -self.BOUND * 0.5),
            Vector3D(b, -b, -self.BOUND * 0.5),
            Vector3D(b, b, -self.BOUND * 0.5),
            Vector3D(-b, b, -self.BOUND * 0.5),
            Vector3D(-b, -b, self.BOUND * 0.5),
            Vector3D(b, -b, self.BOUND * 0.5),
            Vector3D(b, b, self.BOUND * 0.5),
            Vector3D(-b, b, self.BOUND * 0.5),
        ]

    def get_radius(self) -> float:
        """Return an effective radius."""
        return min(self.BOUND, self.side * 0.5)
