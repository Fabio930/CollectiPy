# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
# ------------------------------------------------------------------------------

"""
Logic plugin that clears messages when a waypoint is reached.

Agents running the random way-point movement invoke the configured message
delete trigger (``messages.delete_trigger``) when they reach their goal. If a
LED attachment is available it flashes yellow for half a second, then returns
to its original colour.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional, Tuple

from plugin_registry import register_logic_model

logger = logging.getLogger("sim.plugins.random_wp_cleanup")


class WaypointMessageCleanupLogic:
    """Clear radio buffers every time the random waypoint is reached."""

    def __init__(self, agent: Any, *, arrival_threshold: float = 0.01) -> None:
        self.agent = agent
        self.arrival_threshold = float(arrival_threshold)
        self.wrap_config = getattr(agent, "wrap_config", None)
        self._current_goal_signature: Optional[Tuple[float, float, float]] = self._goal_signature()
        self._handled_goal_signature: Optional[Tuple[float, float, float]] = None
        ticks_per_second = max(1, int(getattr(agent, "ticks_per_second", 1)))
        self._flash_ticks = max(1, int(round(0.5 * ticks_per_second)))
        self._flash_countdown = 0
        self._led = self._locate_led()
        self._led_base_color = self._led.color() if self._led else None
        self._delete_enabled = bool(getattr(agent, "msg_enable", False) and getattr(agent, "msg_delete_trigger", None))
        if getattr(agent, "moving_behavior", "") != "random_way_point":
            logger.debug("%s attached waypoint cleanup but moving_behavior is %s", agent.get_name(), getattr(agent, "moving_behavior", None))

    def step(self, _agent: Any, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Check whether the current waypoint is reached and purge messages."""
        _ = (arena_shape, objects, agents)
        self._update_led_flash()
        goal_signature = self._goal_signature()
        if goal_signature != self._current_goal_signature:
            self._current_goal_signature = goal_signature
            self._handled_goal_signature = None
        if not goal_signature or self._handled_goal_signature == goal_signature:
            return
        if self._has_reached_goal():
            self._handled_goal_signature = goal_signature
            self._run_cleanup()

    def _run_cleanup(self) -> None:
        """Trigger message deletion and flash the LED."""
        if self._delete_enabled and getattr(self.agent, "message_bus", None):
            success = self.agent.message_bus.trigger_delete([self.agent.get_name()])
            if not success:
                logger.debug("%s delete trigger failed or not available", self.agent.get_name())
        if hasattr(self.agent, "clear_message_buffers"):
            self.agent.clear_message_buffers()
        self._flash_led()

    def _has_reached_goal(self) -> bool:
        goal = getattr(self.agent, "goal_position", None)
        if goal is None:
            return False
        dx, dy = self._vector_to_goal(goal)
        distance = math.hypot(dx, dy)
        return distance <= self.arrival_threshold

    def _vector_to_goal(self, goal) -> Tuple[float, float]:
        """Compute the wrapped vector towards the goal."""
        agent = self.agent
        dx = goal.x - agent.position.x
        dy = goal.y - agent.position.y
        if not self.wrap_config:
            return dx, dy
        width = self.wrap_config.get("width", 0.0)
        height = self.wrap_config.get("height", 0.0)
        dx = self._wrap_delta(dx, width)
        dy = self._wrap_delta(dy, height)
        return dx, dy

    @staticmethod
    def _wrap_delta(delta: float, extent: float) -> float:
        """Wrap a delta around the given extent to keep the shortest distance."""
        if extent <= 0:
            return delta
        half = extent * 0.5
        return ((delta + half) % extent) - half

    def _goal_signature(self) -> Optional[Tuple[float, float, float]]:
        goal = getattr(self.agent, "goal_position", None)
        if goal is None:
            return None
        return (goal.x, goal.y, goal.z)

    def _locate_led(self):
        """Return the LED attachment if present."""
        shape = getattr(self.agent, "shape", None)
        attachments = shape.get_attachments() if shape else []
        for attachment in attachments:
            if getattr(attachment, "_id", "") == "led":
                return attachment
        return attachments[0] if attachments else None

    def _flash_led(self) -> None:
        if not self._led:
            return
        if self._led_base_color is None:
            self._led_base_color = self._led.color()
        self._led.set_color("yellow")
        self._flash_countdown = self._flash_ticks

    def _update_led_flash(self) -> None:
        if not self._led or self._flash_countdown <= 0:
            return
        self._flash_countdown -= 1
        if self._flash_countdown <= 0 and self._led_base_color:
            self._led.set_color(self._led_base_color)


def _create_waypoint_cleanup(agent: Any) -> WaypointMessageCleanupLogic:
    return WaypointMessageCleanupLogic(agent)


register_logic_model("waypoint_message_cleanup", _create_waypoint_cleanup)
