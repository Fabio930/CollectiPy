# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import logging
import math
from plugin_base import MovementModel
from plugin_registry import register_movement_model
from models.movement.common import apply_motion_state
from models.utils import normalize_angle
from geometry_utils.vector3D import Vector3D

logger = logging.getLogger("sim.movement.random_way_point")

class RandomWayPointMovement(MovementModel):
    """Random way point movement."""
    def __init__(self, agent):
        """Initialize the instance."""
        self.agent = agent
        self.wrap_config = getattr(agent, "wrap_config", None)

    def step(self, agent, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Execute the simulation step."""
        self._ensure_goal(arena_shape)
        self._steer_towards_goal()
        apply_motion_state(self.agent)

    def _ensure_goal(self, arena_shape) -> None:
        """Ensure goal."""
        agent = self.agent
        if agent.goal_position is None or self._distance_to_goal(agent) <= 0.001:
            agent.goal_position = self._random_goal(arena_shape)
            logger.debug(
                "%s new waypoint %s",
                agent.get_name(),
                (agent.goal_position.x, agent.goal_position.y, agent.goal_position.z)
            )

    def _steer_towards_goal(self) -> None:
        """Steer towards goal."""
        agent = self.agent
        dx, dy = self._wrapped_vector_to_goal(agent)
        angle_to_goal = math.degrees(math.atan2(-dy, dx))
        angle_to_goal = normalize_angle(angle_to_goal - agent.orientation.z)
        dist_mag = math.hypot(dx, dy)
        if abs(dist_mag) >= agent.prev_goal_distance:
            agent.last_motion_tick += 1
        agent.prev_goal_distance = dist_mag
        if agent.last_motion_tick > agent.ticks_per_second:
            agent.last_motion_tick = 0
            agent.goal_position = None
        if angle_to_goal >= agent.max_angular_velocity:
            agent.motion = agent.LEFT
        elif angle_to_goal <= -agent.max_angular_velocity:
            agent.motion = agent.RIGHT
        else:
            agent.motion = agent.FORWARD
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s steering %s (angle_to_goal=%.2f)", agent.get_name(), agent.motion, angle_to_goal)

    def _random_goal(self, arena_shape):
        """Return a new goal position."""
        center = getattr(self.agent, "position", None) or self.agent.get_start_position()
        radius = None
        distribution = "uniform"
        params = getattr(self.agent, "spawn_params", None)
        if params:
            center = params[0] or center
            radius = params[1]
            distribution = params[2] or "uniform"
        if radius is None:
            if self.wrap_config and self.wrap_config.get("unbounded"):
                width = float(self.wrap_config.get("width", 1.0))
                height = float(self.wrap_config.get("height", width))
                radius = max(0.1, min(width, height) * 0.5)
            else:
                radius = 1.0
        return self._sample_spawn(center, radius, distribution)

    def _wrapped_vector_to_goal(self, agent):
        """Return the shortest vector towards the goal accounting for wrap."""
        return (
            agent.goal_position.x - agent.position.x,
            agent.goal_position.y - agent.position.y
        )

    def _distance_to_goal(self, agent):
        """Return the wrapped distance to the current goal."""
        if agent.goal_position is None:
            return 0.0
        dx, dy = self._wrapped_vector_to_goal(agent)
        return math.hypot(dx, dy)

    def _sample_spawn(self, center, radius, distribution):
        """Sample a point from the configured distribution."""
        rng = self.agent.random_generator
        dist = str(distribution).lower()
        if dist == "gaussian":
            std = radius / 3.0
            x = rng.gauss(center.x, std)
            y = rng.gauss(center.y, std)
        elif dist == "ring":
            r = rng.uniform(radius * 0.5, radius)
            theta = rng.uniform(0.0, 2 * math.pi)
            x = center.x + r * math.cos(theta)
            y = center.y + r * math.sin(theta)
        else:
            r = math.sqrt(rng.uniform(0.0, 1.0)) * radius
            theta = rng.uniform(0.0, 2 * math.pi)
            x = center.x + r * math.cos(theta)
            y = center.y + r * math.sin(theta)
        return Vector3D(x, y, self.agent.position.z)

register_movement_model("random_way_point", lambda agent: RandomWayPointMovement(agent))
