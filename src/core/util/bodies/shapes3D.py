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
from core.util.logging_util import get_logger

_PI = math.pi
# Tolerance for shapes that merely touch (e.g. a body resting on the floor plane).
_CONTACT_EPS = 1e-9
logger = get_logger("shapes3D")


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
        logger.info("Creating shape %s for %s", shape_type, _object)
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
    flat_shapes = ["circle", "square", "rectangle"]
    # Round footprints look the same at any heading: their vertices are never rotated.
    _round = False

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
        self.rotation_z = 0.0
        # Geometry caches: where the vertices were generated, their bounding box and radius.
        self._built_center: tuple | None = None
        self._bounds: tuple | None = None
        self._bounding_radius: float | None = None

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
        """Translate the shape in space (the existing vertices are shifted, not regenerated)."""
        built = self._built_center
        self.center = new_center
        if built is None:
            self.set_vertices()
            return
        if self._is_flat():
            new_center.z = 0
        dx = new_center.x - built[0]
        dy = new_center.y - built[1]
        dz = new_center.z - built[2]
        if not (dx or dy or dz):
            return
        for vertex in self.vertices_list:
            vertex.x += dx
            vertex.y += dy
            vertex.z += dz
        self._built_center = (new_center.x, new_center.y, new_center.z)
        bounds = self._bounds
        if bounds is not None:
            self._bounds = (
                bounds[0] + dx, bounds[1] + dy, bounds[2] + dz,
                bounds[3] + dx, bounds[4] + dy, bounds[5] + dz,
            )

    def set_pose(self, new_center: Vector3D, angle_z: float):
        """Move and orient the shape in one pass."""
        if self._round or angle_z == self.rotation_z:
            self.rotation_z = float(angle_z)
            self.translate(new_center)
            return
        self.rotation_z = float(angle_z)
        self.center = new_center
        self.set_vertices()

    def get_radius(self) -> float:
        """Return the radius."""
        return 0

    def bounding_radius(self) -> float:
        """Radius of the sphere around the center that contains the shape (0.05 for point shapes)."""
        radius = self._bounding_radius
        if radius is None:
            radius = float(self.get_radius() or 0.0)
            if radius <= 0:
                center = self.center
                radius = max(
                    (math.sqrt((v.x - center.x) ** 2 + (v.y - center.y) ** 2 + (v.z - center.z) ** 2)
                     for v in self.vertices_list),
                    default=0.05,
                )
            self._bounding_radius = radius
        return radius

    def _is_flat(self) -> bool:
        """Flat shapes lie on the floor plane (z = 0)."""
        return False

    def set_vertices(self):
        """(Re)generate the vertices around the current center, with the current heading."""
        self._build_vertices()
        center = self.center
        self._built_center = (center.x, center.y, center.z)
        self._bounds = None
        self._apply_rotation()

    def _build_vertices(self):
        """Fill `vertices_list` for the current center (implemented by concrete shapes)."""
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

    def _is_point_inside_shape(self, point, shape):
        """Is point inside shape."""
        dx = point.x - shape.center.x
        dy = point.y - shape.center.y
        if isinstance(shape, Sphere):
            dz = point.z - shape.center.z
            return dx * dx + dy * dy + dz * dz <= shape.radius ** 2 + _CONTACT_EPS
        if isinstance(shape, Cylinder):
            z_min, z_max = shape.z_bounds()
            return (math.hypot(dx, dy) <= shape.radius and
                    z_min - _CONTACT_EPS <= point.z <= z_max + _CONTACT_EPS)
        else:
            bounds = shape._get_bounds()
            return (bounds[0] <= point.x <= bounds[3] and
                    bounds[1] <= point.y <= bounds[4] and
                    bounds[2] <= point.z <= bounds[5])

    def rotate(self, angle_z: float):
        """Set the heading of the shape (degrees, same convention as the agents' orientation)."""
        if self._round or angle_z == self.rotation_z:
            self.rotation_z = float(angle_z)
            return
        self.rotation_z = float(angle_z)
        self.set_vertices()

    def _apply_rotation(self):
        """Rotate the freshly built vertices around the center on the XY plane."""
        if self._round or not self.rotation_z:
            return
        # Headings grow clockwise in arena coordinates (see the unicycle model).
        angle_rad = -math.radians(self.rotation_z)
        cos_z = math.cos(angle_rad)
        sin_z = math.sin(angle_rad)
        cx, cy = self.center.x, self.center.y
        for vertex in self.vertices_list:
            x_shift = vertex.x - cx
            y_shift = vertex.y - cy
            vertex.x = cx + x_shift * cos_z - y_shift * sin_z
            vertex.y = cy + x_shift * sin_z + y_shift * cos_z

    def _get_bounds(self) -> tuple:
        """Return (min_x, min_y, min_z, max_x, max_y, max_z) of the vertices, cached until they change."""
        bounds = self._bounds
        if bounds is None:
            vertices = self.vertices_list
            if not vertices:
                return (0, 0, 0, 0, 0, 0)
            xs = [v.x for v in vertices]
            ys = [v.y for v in vertices]
            zs = [v.z for v in vertices]
            bounds = self._bounds = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        return bounds

    def min_vert(self):
        """Min vert."""
        bounds = self._get_bounds()
        return Vector3D(bounds[0], bounds[1], bounds[2])

    def max_vert(self):
        """Max vert."""
        bounds = self._get_bounds()
        return Vector3D(bounds[3], bounds[4], bounds[5])

class ShapeState:
    """Pose-only stand-in for a shape (center, metadata, radius) for consumers that do not draw it."""

    __slots__ = ("center", "metadata", "_radius")

    def __init__(self, shape: Shape):
        self.center = shape.center
        self.metadata = shape.metadata
        self._radius = shape.bounding_radius()

    def center_of_mass(self) -> Vector3D:
        """Center of mass."""
        return self.center

    def bounding_radius(self) -> float:
        """Radius of the sphere around the center that contains the shape."""
        return self._radius


class Sphere(Shape):
    """Sphere."""
    _round = True

    def __init__(self, _object: str, shape_type: str, config_elem: dict, center: Vector3D | None = None):
        """Initialize the instance."""
        super().__init__(config_elem=config_elem, center=center)
        self._object = _object
        self._id = shape_type
        self.radius = _resolve_dimension(config_elem, "radius", fallback="diameter", fallback_scale=0.5, default=1.0)
        self.set_vertices()

    def get_radius(self) -> float:
        """Return the radius."""
        return self.radius

    def _build_vertices(self):
        """Set the vertices: both poles plus rings of points along the meridians."""
        num_meridians = 16
        num_parallels = 7
        cx, cy, cz = self.center.x, self.center.y, self.center.z
        r = self.radius
        self.vertices_list = [Vector3D(cx, cy, cz + r)]
        for i in range(num_meridians):
            theta = 2 * _PI * (i / num_meridians)
            cos_theta = math.cos(theta)
            sin_theta = math.sin(theta)
            for j in range(1, num_parallels + 1):
                phi = _PI * j / (num_parallels + 1)
                sin_phi = math.sin(phi)
                x = cx + r * sin_phi * cos_theta
                y = cy + r * sin_phi * sin_theta
                z = cz + r * math.cos(phi)
                self.vertices_list.append(Vector3D(x, y, z))
        self.vertices_list.append(Vector3D(cx, cy, cz - r))

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

    def _is_flat(self) -> bool:
        return self._object != "arena" and self._id in Shape.flat_shapes

    def _build_vertices(self):
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
    _round = True

    def __init__(self, _object: str, shape_type: str, config_elem: dict, center: Vector3D | None = None):
        """Initialize the instance."""
        super().__init__(config_elem=config_elem, center=center)
        self._object = _object
        self._id = shape_type
        self.radius = _resolve_dimension(config_elem, "radius", fallback="diameter", fallback_scale=0.5, default=1.0)
        self.height = _resolve_dimension(config_elem, "height", default=1.0)
        self.set_vertices()

    def z_bounds(self) -> tuple[float, float]:
        """Return the vertical extent of the cylinder."""
        if self._object == "arena":
            return 0.0, self.height
        if self._id in Shape.flat_shapes:
            return 0.0, 0.0
        half_height = self.height * 0.5
        return self.center.z - half_height, self.center.z + half_height

    def get_radius(self) -> float:
        """Return the radius."""
        return self.radius

    def _is_flat(self) -> bool:
        return self._object != "arena" and self._id in Shape.flat_shapes

    def _build_vertices(self):
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

    def _build_vertices(self):
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
