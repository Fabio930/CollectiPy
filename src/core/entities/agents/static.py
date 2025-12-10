# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Static agent."""

from __future__ import annotations

from core.entities.agents.base import Agent
from core.util.bodies.shapes3D import Shape3DFactory
from core.util.geometry_utils.vector3D import Vector3D


class StaticAgent(Agent):
    """Static agent."""

    def __init__(self, entity_type: str, config_elem: dict, _id: int = 0):
        """Initialize the instance."""
        super().__init__(entity_type, config_elem, _id)
        if config_elem.get("shape") in ("sphere", "cube", "cuboid", "cylinder"):
            self.shape_type = "dense"
        self.shape = Shape3DFactory.create_shape("agent", config_elem.get("shape", "point"), dict(config_elem))
<<<<<<< Updated upstream
        self.shape.add_attachment(
            Shape3DFactory.create_shape("mark", "circle", {"_id": "led", "color": "red", "diameter": 0.01})
        )
=======
        marker = Shape3DFactory.create_shape("mark", "circle", {"_id": "led", "color": "red", "diameter": 0.01})
        self.shape.add_attachment(marker)
        self._led_attachment = marker
        self._led_default_color = marker.color()
>>>>>>> Stashed changes
        self._level_attachment = None
        self._sync_shape_hierarchy_metadata()
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.start_position = Vector3D()
        self.start_orientation = Vector3D()
<<<<<<< Updated upstream
        temp_position = config_elem.get("position", None)
        self.perception_distance = config_elem.get("perception_distance", 0.1)
        if temp_position is not None:
            self.position_from_dict = True
            try:
                self.start_position = Vector3D(temp_position[0], temp_position[1], temp_position[2])
            except Exception:
                self.start_position = Vector3D(temp_position[-1][0], temp_position[-1][1], temp_position[-1][2])
        temp_orientation = config_elem.get("orientation", None)
        if temp_orientation is not None:
            self.orientation_from_dict = True
            try:
                self.start_orientation = Vector3D(temp_orientation[0], temp_orientation[1], temp_orientation[2])
            except Exception:
                self.start_orientation = Vector3D(
                    temp_orientation[-1][0], temp_orientation[-1][1], temp_orientation[-1][2]
                )
            self.orientation = self.start_orientation
=======
        self.perception_distance = config_elem.get("perception_distance", 0.1)
>>>>>>> Stashed changes

    def to_origin(self):
        """To origin."""
        self.position = Vector3D()
        self.shape.center = self.position
        self.shape.set_vertices()

    def set_start_position(self, new_position: Vector3D, _translate: bool = True):
        """Set the start position."""
        self.start_position = new_position
        self.set_position(new_position, _translate)

    def set_position(self, new_position: Vector3D, _translate: bool = True):
        """Set the position."""
        self.position = new_position
        if _translate:
            self.shape.translate(self.position)

    def set_start_orientation(self, new_orientation: Vector3D):
        """Set the start orientation."""
        self.start_orientation = new_orientation
        self.set_orientation(new_orientation)

    def set_orientation(self, new_orientation: Vector3D):
        """Set the orientation."""
        self.orientation = new_orientation
        self.shape.rotate(self.start_orientation.z)

    def get_start_position(self):
        """Return the start position."""
        return self.start_position

    def get_start_orientation(self):
        """Return the start orientation."""
        return self.start_orientation

    def get_position(self):
        """Return the position."""
        return self.position

    def get_orientation(self):
        """Return the orientation."""
        return self.orientation

    def close(self):
        """Close the component resources."""
        del self.shape
        return

    def get_shape(self):
        """Return the shape."""
        return self.shape

    def get_shape_type(self):
        """Return the shape type."""
        return self.shape_type
