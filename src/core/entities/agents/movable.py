# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Movable agent."""

from __future__ import annotations

from typing import Optional

from core.configuration.plugin_registry import get_logic_model, get_movement_model
from core.entities.agents.base import logger as _base_logger
from core.entities.agents.static import StaticAgent
from core.util.bodies.shapes3D import Shape3DFactory
from core.util.geometry_utils.vector3D import Vector3D
from models.utility_functions import normalize_angle


logger = _base_logger


class MovableAgent(StaticAgent):
    """Movable agent."""

    STOP = 0
    FORWARD = 1
    LEFT = 2
    RIGHT = 3

    def __init__(self, entity_type: str, config_elem: dict, _id: int = 0):
        """Initialize the instance."""
        super().__init__(entity_type, config_elem, _id)
        self.config_elem = config_elem
        self.max_absolute_velocity = float(config_elem.get("max_linear_velocity", 0.01)) / self.ticks_per_second
        self.max_angular_velocity = int(config_elem.get("max_angular_velocity", 10)) / self.ticks_per_second
        self.forward_vector = Vector3D()
        self.delta_orientation = Vector3D()
        self.goal_position = None
        self.prev_orientation = Vector3D()
        self.position = Vector3D()
        self.prev_position = Vector3D()
        self.prev_goal_distance = 0
        self.moving_behavior = config_elem.get("moving_behavior", "random_walk")
        self.fallback_moving_behavior = config_elem.get("fallback_moving_behavior", "none")
        self.logic_behavior = config_elem.get("logic_behavior")
        self.spin_model_params = config_elem.get("spin_model", {})
        # Resolve detection range before movement plugin creation so it propagates into detection models.
        self.detection_range = self._resolve_detection_range()
        self.wrap_config = None
        self.hierarchy_target = self.hierarchy_target or "0"
        self.hierarchy_node = "0"
        self.hierarchy_level = 0
        self._level_color_map = {}
        self._level_attachment = None
        self.max_turning_ticks = 160
        self.standard_motion_steps = 5 * 16
        self.crw_exponent = config_elem.get("crw_exponent", 1)
        self.levy_exponent = config_elem.get("levy_exponent", 1.75)
        self._movement_plugin = self._init_movement_model()
        self._logic_plugin = self._init_logic_model()

    def _init_movement_model(self):
        """Init movement model."""
        model = get_movement_model(self.moving_behavior, self)
        if model is None and self.moving_behavior != "random_walk":
            model = get_movement_model("random_walk", self)
        return model

    def _init_logic_model(self):
        """Init logic model."""
        return get_logic_model(self.logic_behavior, self)

    def reset(self):
        """Reset the component state."""
        if self._movement_plugin and hasattr(self._movement_plugin, "reset"):
            self._movement_plugin.reset()
        if self._logic_plugin and hasattr(self._logic_plugin, "reset"):
            self._logic_plugin.reset()
        self.turning_ticks = 0
        self.forward_ticks = 0
        self.motion = MovableAgent.STOP
        self.last_motion_tick = 0
        self.forward_vector = Vector3D()
        self.delta_orientation = Vector3D()
        self.goal_position = None
        self.prev_goal_distance = 0
        self._reset_detection_scheduler()
        self.clear_message_buffers()
        logger.info("%s reset with behavior %s", self.get_name(), self.moving_behavior)

    def get_detection_range(self) -> float:
        """Return the configured detection range."""
        return float(self.detection_range)

    def prepare_for_run(self, objects: dict, agents: dict):
        """Prepare for run."""
        if self._movement_plugin and hasattr(self._movement_plugin, "pre_run"):
            self._movement_plugin.pre_run(objects, agents)
            logger.debug("%s performed pre-run hook via %s", self.get_name(), type(self._movement_plugin).__name__)
        if self._logic_plugin and hasattr(self._logic_plugin, "pre_run"):
            self._logic_plugin.pre_run(objects, agents)
            logger.debug("%s performed logic pre-run hook via %s", self.get_name(), type(self._logic_plugin).__name__)

    def get_spin_system_data(self):
        """Return the spin-system payload delegating to the movement plugin when available.

        Older core code expected `Agent.get_spin_system_data()` to provide
        movement-specific spin payloads. Movement plugins (for example
        `SpinMovementModel`) may implement `get_spin_system_data()` themselves.
        Delegate to the plugin when present to ensure the GUI receives the
        spin data regardless of whether the behaviour is provided by a
        built-in agent class or a registered movement plugin.
        """
        if self._movement_plugin and hasattr(self._movement_plugin, "get_spin_system_data"):
            try:
                return self._movement_plugin.get_spin_system_data()
            except Exception:
                return None
        return None

    def post_step(self, position_correction: Vector3D):
        """Post step: apply collision correction as a delta, not as an absolute position."""
        if position_correction is not None:
            self.position = self.position + position_correction
            self.shape.translate(self.position)
            self.shape.translate_attachments(self.orientation.z)
            logger.debug(
                "%s position corrected by detector with delta %s -> new pos %s",
                self.get_name(),
                position_correction,
                (self.position.x, self.position.y, self.position.z),
            )

    def run(self, tick: int, arena_shape: Shape3DFactory, objects: dict, agents: dict):
        """Run the simulation routine."""
        self.prev_position = self.position
        self.prev_orientation = self.orientation
        self._refresh_message_timers()
        self.linear_velocity_cmd = 0.0
        self.angular_velocity_cmd = 0.0
        if hasattr(self, "forward_vector"):
            self.forward_vector = Vector3D()
        if hasattr(self, "delta_orientation"):
            self.delta_orientation = Vector3D()
        logger.debug("%s starting run tick=%s behavior=%s", self.get_name(), tick, self.moving_behavior)
        if self._logic_plugin:
            self._logic_plugin.step(self, tick, arena_shape, objects, agents)
        if not self._movement_plugin:
            raise ValueError("No movement model configured for agent")
        self._movement_plugin.step(self, tick, arena_shape, objects, agents)
        if self._logic_plugin and hasattr(self._logic_plugin, "after_movement"):
            self._logic_plugin.after_movement(self, tick, arena_shape, objects, agents)
        self._apply_motion(tick)
        self.shape.translate(self.position)
        self.shape.translate_attachments(self.orientation.z)

    def _apply_motion(self, tick: int):
        """Apply the motion using the configured kinematic model."""
        if self._motion_model is not None:
            self._motion_model.step(self, tick)
        else:
            self._legacy_motion_step()
        self.shape.rotate(self.delta_orientation.z)
        self.shape.translate(self.position)
        self.shape.translate_attachments(self.orientation.z)
        logger.debug(
            "%s applied motion -> position=%s orientation=%s delta=%s",
            self.get_name(),
            (self.position.x, self.position.y, self.position.z),
            self.orientation.z,
            (self.delta_orientation.x, self.delta_orientation.y, self.delta_orientation.z),
        )

    def _legacy_motion_step(self):
        """Fallback kinematic update preserving legacy behaviour."""
        self.position = self.position + getattr(self, "forward_vector", Vector3D())
        self.orientation = self.orientation + getattr(self, "delta_orientation", Vector3D())
        self.orientation.z = normalize_angle(self.orientation.z)

    def close(self):
        """Close the component resources."""
        return super().close()

    def enable_hierarchy_marker(self, level_colors: dict):
        """Enable the hierarchy marker."""
        if not level_colors:
            return
        self._level_color_map = dict(level_colors or {})
        if self._level_attachment is None:
            marker = Shape3DFactory.create_shape(
                "mark",
                "square",
                {"_id": "idle", "color": self._get_level_color(), "width": 0.012, "depth": 0.012},
            )
            marker.metadata["placement"] = "opposite"
            self.shape.add_attachment(marker)
            self._level_attachment = marker
        self._update_level_attachment_color()
        self.shape.translate_attachments(self.orientation.z)

    def _get_level_color(self, level: Optional[int] = None) -> str:
        """Return the level color."""
        if level is None:
            level = self.hierarchy_level if self.hierarchy_level is not None else 0
        if not self._level_color_map:
            return "black"
        return self._level_color_map.get(level, next(iter(self._level_color_map.values()), "black"))

    def _update_level_attachment_color(self):
        """Update level attachment color."""
        if not self._level_attachment:
            return
        self._level_attachment.set_color(self._get_level_color())

    def set_hierarchy_level(self, level):
        """Set the hierarchy level."""
        super().set_hierarchy_level(level)
        self._update_level_attachment_color()
