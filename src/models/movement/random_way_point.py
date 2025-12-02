# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import math
from plugin_base import MovementModel
from plugin_registry import register_movement_model
from models.movement.common import apply_motion_state
from models.utils import normalize_angle
from geometry_utils.vector3D import Vector3D
from logging_utils import get_logger

logger = get_logger("movement.random_way_point")

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
        logger.debug("%s steering %s (angle_to_goal=%.2f)", agent.get_name(), agent.motion, angle_to_goal)

    def _random_goal(self, arena_shape):
        """Return a new goal position."""
        agent = self.agent
        shape = agent.get_shape()
        dx = float(shape.max_vert().x - shape.min_vert().x)
        dy = float(shape.max_vert().y - shape.min_vert().y)
        agent_radius = 0.5 * max(abs(dx), abs(dy))
        wrap_cfg = self.wrap_config or getattr(agent, "wrap_config", None)
        unbounded = bool(wrap_cfg and wrap_cfg.get("unbounded"))
        if unbounded:
            center = getattr(agent, "position", None) or agent.get_start_position()
            factor = getattr(agent, "random_waypoint_radius_factor", 5.0)
            radius = max(agent_radius * factor, agent_radius * 1.5)
            distribution = getattr(agent, "random_waypoint_distribution", "uniform")
            return self._sample_spawn(center, radius, distribution)

        min_v = arena_shape.min_vert()
        max_v = arena_shape.max_vert()
        min_x = float(min_v.x)
        max_x = float(max_v.x)
        min_y = float(min_v.y)
        max_y = float(max_v.y)

        hierarchy = getattr(agent, "hierarchy_context", None)
        node_id = getattr(agent, "hierarchy_node", None)
        info = getattr(hierarchy, "information_scope", None) if hierarchy is not None else None
        use_node_bounds = (
            hierarchy is not None
            and isinstance(info, dict)
            and info.get("over")
            and "movement" in info.get("over")
            and node_id is not None
        )

        if use_node_bounds:
            try:
                node = hierarchy.get_node(node_id)
            except Exception:
                node = None
            if node and getattr(node, "bounds", None):
                b = node.bounds
                min_x = float(getattr(b, "x_min", min_x))
                min_y = float(getattr(b, "y_min", min_y))
                max_x = float(getattr(b, "x_max", max_x))
                max_y = float(getattr(b, "y_max", max_y))

        margin_factor = getattr(agent, "random_waypoint_margin_factor", 1.0)
        margin = agent_radius * margin_factor
        min_x += margin
        max_x -= margin
        min_y += margin
        max_y -= margin

        if min_x > max_x:
            cx_full = (min_v.x + max_v.x) * 0.5
            min_x = max_x = cx_full
        if min_y > max_y:
            cy_full = (min_v.y + max_v.y) * 0.5
            min_y = max_y = cy_full

        cx = 0.5 * (min_x + max_x)
        cy = 0.5 * (min_y + max_y)

        distribution = getattr(agent, "random_waypoint_distribution", "uniform")
        distribution = (distribution or "uniform").lower()

        rng = agent.get_random_generator()

        if distribution == "gaussian":
            span_x = max_x - min_x
            span_y = max_y - min_y
            std_x = span_x / 6.0 if span_x > 0.0 else 0.0
            std_y = span_y / 6.0 if span_y > 0.0 else 0.0
            gx = rng.gauss(cx, std_x) if std_x > 0.0 else cx
            gy = rng.gauss(cy, std_y) if std_y > 0.0 else cy
            gx = min(max(gx, min_x), max_x)
            gy = min(max(gy, min_y), max_y)
        elif distribution == "ring":
            half_w = max_x - min_x
            half_h = max_y - min_y
            r_max = 0.5 * min(half_w, half_h)
            if r_max <= 0.0:
                gx, gy = cx, cy
            else:
                r_min = 0.5 * r_max
                r = rng.uniform(r_min, r_max)
                theta = rng.uniform(0.0, 2.0 * math.pi)
                gx = cx + r * math.cos(theta)
                gy = cy + r * math.sin(theta)
                gx = min(max(gx, min_x), max_x)
                gy = min(max(gy, min_y), max_y)

        else:
            gx = rng.uniform(min_x, max_x)
            gy = rng.uniform(min_y, max_y)

        gz = abs(agent.get_shape().min_vert().z)
        goal = Vector3D(gx, gy, gz)
        return goal


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
