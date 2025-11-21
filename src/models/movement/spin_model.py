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
import numpy as np
from models.spinsystem import SpinSystem
from plugin_base import MovementModel
from plugin_registry import (
    get_detection_model,
    get_movement_model,
    register_movement_model,
)
from models.utils import normalize_angle

logger = logging.getLogger("sim.spin")

class SpinMovementModel(MovementModel):
    """Spin movement model."""
    def __init__(self, agent):
        """Initialize the instance."""
        self.agent = agent
        self.spin_model_params = agent.config_elem.get("spin_model", {})
        self.spin_pre_run_steps = self.spin_model_params.get("spin_pre_run_steps", 0)
        self.spin_per_tick = self.spin_model_params.get("spin_per_tick", 10)
        self.perception_width = self.spin_model_params.get("perception_width", 0.5)
        self.num_groups = self.spin_model_params.get("num_groups", 16)
        self.num_spins_per_group = self.spin_model_params.get("num_spins_per_group", 8)
        self.perception_global_inhibition = self.spin_model_params.get("perception_global_inhibition", 0)
        agent_task = agent.get_task() if hasattr(agent, "get_task") else None
        spin_task = self.spin_model_params.get("task")
        self.task = agent_task or spin_task or "selection"
        if agent_task is None and hasattr(agent, "set_task"):
            agent.set_task(self.task)
        self.reference = self.spin_model_params.get("reference", "egocentric")
        self.fallback_behavior = agent.config_elem.get("fallback_moving_behavior", "none")
        self.group_angles = np.linspace(0, 2 * math.pi, self.num_groups, endpoint=False)
        self.perception = None
        self._active_perception_channel = "objects"
        self.perception_range = self._resolve_detection_range()
        self.spin_system = None
        self._fallback_model = None
        self.detection_model = self._create_detection_model()
        self.reset()

    def _create_detection_model(self):
        """Create detection model."""
        context = {
            "num_groups": self.num_groups,
            "num_spins_per_group": self.num_spins_per_group,
            "perception_width": self.perception_width,
            "group_angles": self.group_angles,
            "reference": self.reference,
            "perception_global_inhibition": self.perception_global_inhibition,
            "max_detection_distance": self.perception_range,
            "detection_config": getattr(self.agent, "detection_config", {}),
        }
        detection_name = getattr(self.agent, "detection", None)
        if not detection_name:
            detection_name = self.agent.config_elem.get("detection", "GPS")
        return get_detection_model(detection_name, self.agent, context)

    def reset(self) -> None:
        """Reset the component state."""
        self.perception = None
        self.spin_system = SpinSystem(
            self.agent.random_generator,
            self.num_groups,
            self.num_spins_per_group,
            float(self.spin_model_params.get("T", 0.5)),
            float(self.spin_model_params.get("J", 1)),
            float(self.spin_model_params.get("nu", 0)),
            float(self.spin_model_params.get("p_spin_up", 0.5)),
            int(self.spin_model_params.get("time_delay", 1)),
            self.spin_model_params.get("dynamics", "metropolis"),
        )

    def pre_run(self, objects: dict, agents: dict) -> None:
        """Pre run."""
        if self.spin_pre_run_steps <= 0:
            return
        self._update_perception(objects, agents, None, None)
        if self.perception is None:
            return
        for _ in range(self.spin_pre_run_steps):
            self.spin_system.step(timedelay=False)
        self.spin_system.set_p_spin_up(np.mean(self.spin_system.get_states()))
        self.spin_system.reset_spins()
        logger.debug("%s spin pre-run completed (%d steps)", self.agent.get_name(), self.spin_pre_run_steps)

    def step(self, agent, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Execute the simulation step."""
        self._update_perception(objects, agents, tick, arena_shape)
        if self.perception is None or not np.any(self.perception > 0):
            self._run_fallback(tick, arena_shape, objects, agents)
            return
        self.spin_system.update_external_field(self.perception)
        self.spin_system.run_spins(steps=self.spin_per_tick)
        angle_rad = self.spin_system.average_direction_of_activity()
        if angle_rad is None:
            return
        if self.reference == "allocentric":
            angle_rad = angle_rad - math.radians(self.agent.orientation.z)
        angle_deg = normalize_angle(math.degrees(angle_rad))
        angle_deg = max(min(angle_deg, self.agent.max_angular_velocity), -self.agent.max_angular_velocity)
        width = self.spin_system.get_width_of_activity()
        scaling_factor = 1.0 / width if width and width > 0 else 0.0
        scaling_factor = np.clip(scaling_factor, 0.0, 1.0)
        self.agent.linear_velocity_cmd = self.agent.max_absolute_velocity * scaling_factor
        self.agent.angular_velocity_cmd = angle_deg
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "%s spin direction updated -> angle=%.2f width=%.4f scaling=%.3f",
                self.agent.get_name(),
                angle_deg,
                width,
                scaling_factor
            )

    def _update_perception(self, objects: dict, agents: dict, tick: int | None = None, arena_shape=None) -> None:
        """Update perception."""
        if self.detection_model is None:
            self.perception = None
            return
        if tick is not None and hasattr(self.agent, "should_sample_detection"):
            if not self.agent.should_sample_detection(tick):
                return
        snapshot = self.detection_model.sense(self.agent, objects, agents, arena_shape)
        if snapshot is None:
            self.perception = None
            return
        if isinstance(snapshot, dict):
            selected, channel_name = self._select_perception_channel(snapshot)
        else:
            selected, channel_name = snapshot, "raw"
        self.perception = selected
        self._active_perception_channel = channel_name
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "%s perception snapshot channel=%s mean=%.3f",
                self.agent.get_name(),
                channel_name,
                float(np.mean(self.perception)) if self.perception is not None else 0.0,
            )

    def _select_perception_channel(self, snapshot: dict[str, np.ndarray]) -> tuple[np.ndarray, str]:
        """Select the perception channel matching the current task."""
        task_name = (self.agent.get_task() or self.task or "selection").lower()
        objects_channel = snapshot.get("objects")
        agents_channel = snapshot.get("agents")
        combined_channel = snapshot.get("combined")
        if task_name in ("selection", "objects"):
            return self._channel_with_fallback(
                (objects_channel, "objects"),
                (combined_channel, "combined"),
                (agents_channel, "agents"),
            )
        if task_name in ("flocking", "agents"):
            return self._channel_with_fallback(
                (agents_channel, "agents"),
                (combined_channel, "combined"),
                (objects_channel, "objects"),
            )
        if task_name in ("all", "combined", "hybrid", "group", "group_hunt"):
            return self._channel_with_fallback(
                (combined_channel, "combined"),
                (objects_channel, "objects"),
                (agents_channel, "agents"),
            )
        logger.warning("%s unknown task '%s', using combined perception", self.agent.get_name(), task_name)
        return self._channel_with_fallback(
            (combined_channel, "combined"),
            (objects_channel, "objects"),
            (agents_channel, "agents"),
        )

    def _channel_with_fallback(
        self,
        primary: tuple[np.ndarray | None, str],
        secondary: tuple[np.ndarray | None, str],
        tertiary: tuple[np.ndarray | None, str],
    ) -> tuple[np.ndarray, str]:
        """Return first available perception channel from the provided priority list."""
        for channel, name in (primary, secondary, tertiary):
            if channel is not None:
                return channel, name
        raise ValueError("Detection model did not provide any perception channels")

    def _resolve_detection_range(self) -> float:
        """Resolve the maximum detection radius from the agent configuration."""
        if hasattr(self.agent, "get_detection_range"):
            try:
                return float(self.agent.get_detection_range())
            except (TypeError, ValueError):
                logger.warning(
                    "%s provided invalid detection range via accessor; falling back to legacy config",
                    self.agent.get_name()
                )
        config_elem = getattr(self.agent, "config_elem", {})
        settings = {}
        if isinstance(config_elem, dict):
            settings = config_elem.get("detection_settings", {}) or {}
        range_candidate = None
        if isinstance(settings, dict):
            range_candidate = settings.get("range", settings.get("distance"))
        if range_candidate is None and isinstance(config_elem, dict):
            range_candidate = config_elem.get("perception_distance")
        if range_candidate is None and hasattr(self.agent, "perception_distance"):
            range_candidate = self.agent.perception_distance
        if range_candidate is None:
            return math.inf
        try:
            return float(range_candidate)
        except (TypeError, ValueError):
            logger.warning("%s invalid detection range '%s', using infinite distance", self.agent.get_name(), range_candidate)
            return math.inf

    def _run_fallback(self, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Run the fallback."""
        if self.fallback_behavior in ("spin_model","none"):
            return
        behavior = self.fallback_behavior
        if self._fallback_model is None:
            self._fallback_model = get_movement_model(self.fallback_behavior, self.agent)
            if self._fallback_model is None and self.fallback_behavior != "random_walk":
                self._fallback_model = get_movement_model("random_walk", self.agent)
                behavior = "random_walk"
        if self._fallback_model is None:
            logger.warning("%s has no fallback movement model configured", self.agent.get_name())
            return
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s fallback to %s", self.agent.get_name(), behavior)
        self._fallback_model.step(self.agent, tick, arena_shape, objects, agents)

    def get_spin_system_data(self):
        """Return the spin system data."""
        if not self.spin_system:
            return None
        return (
            self.spin_system.get_states(),
            self.spin_system.get_angles(),
            self.spin_system.get_external_field(),
            self.spin_system.get_avg_direction_of_activity(),
        )

register_movement_model("spin_model", lambda agent: SpinMovementModel(agent))
