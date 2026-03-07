# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

from __future__ import annotations

import importlib
import math
import numpy as np
from functools import lru_cache
from typing import Optional
from core.configuration.plugin_base import MovementModel
from core.configuration.plugin_registry import (
    get_detection_model,
    get_movement_model,
)
from models.utility_functions import normalize_angle
from core.util.logging_util import get_logger

logger = get_logger("movement.spin_model")


def _resolve_spin_backend_module_name(moving_behavior: str) -> str:
    """Map moving behavior name to spin backend module name."""
    behavior = (moving_behavior or "").strip().lower()
    if behavior == "spin_model":
        return "models.spin_models.spin_system"
    if behavior.startswith("spin_model_"):
        suffix = behavior.removeprefix("spin_model_")
        if suffix:
            return f"models.spin_models.spin_system_{suffix}"
    return "models.spin_models.spin_system"


@lru_cache(maxsize=32)
def _resolve_spin_module_class(moving_behavior: str):
    """Return SpinModule class for the configured movement behavior."""
    module_name = _resolve_spin_backend_module_name(moving_behavior)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to import spin backend module '{module_name}' "
            f"for moving_behavior='{moving_behavior}'."
        ) from exc
    spin_class = getattr(module, "SpinModule", None)
    if spin_class is None:
        raise RuntimeError(
            f"Spin backend module '{module_name}' does not expose a SpinModule class "
            f"(moving_behavior='{moving_behavior}')."
        )
    return spin_class


def _resolve_perception_backend_module_name(detection_type: str) -> str:
    """Map detection type to perception backend module name."""
    det_type = (detection_type or "").strip().upper()
    if det_type == "GPS":
        return "models.spin_models.perception_system"
    if det_type == "VISUAL":
        return "models.spin_models.perception_system_visual"  # Esempio: modulo separato per VISUAL
    # Aggiungi altri tipi di detection qui se necessario
    return "models.spin_models.perception_system"


@lru_cache(maxsize=32)
def _resolve_perception_module_class(detection_type: str):
    """Return PerceptionModule class for the configured detection type."""
    module_name = _resolve_perception_backend_module_name(detection_type)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to import perception backend module '{module_name}' "
            f"for detection_type='{detection_type}'."
        ) from exc
    perception_class = getattr(module, "PerceptionModule", None)
    if perception_class is None:
        raise RuntimeError(
            f"Perception backend module '{module_name}' does not expose a PerceptionModule class "
            f"(detection_type='{detection_type}')."
        )
    return perception_class


class SpinMovementModel(MovementModel):
    """Spin movement model."""
    def __init__(self, agent):
        """Initialize the instance."""
        self.agent = agent
        self.moving_behavior = str(agent.config_elem.get("moving_behavior", "spin_model") or "spin_model").lower()
        self._spin_module_class = _resolve_spin_module_class(self.moving_behavior)
        self.spin_model_params = agent.config_elem.get("spin_model", {})
        self.spin_pre_run_steps = self.spin_model_params.get("spin_pre_run_steps", 0)
        self.spin_per_tick = self.spin_model_params.get("spin_per_tick", 3)
        self.perception_width = self.spin_model_params.get("perception_width", 0.3)
        self.num_groups = self.spin_model_params.get("num_groups", 8)
        self.num_spins_per_group = self.spin_model_params.get("num_spins_per_group", 5)
        self.global_inhibition = self.spin_model_params.get("global_inhibition", 0)
        agent_task = agent.get_task() if hasattr(agent, "get_task") else None
        spin_task = self.spin_model_params.get("task")
        self.task = agent_task or spin_task or "selection"
        if agent_task is None and hasattr(agent, "set_task"):
            agent.set_task(self.task)
        self.reference = self.spin_model_params.get("reference", "egocentric")
        self.fallback_behavior = str(agent.config_elem.get("fallback_moving_behavior", "none") or "none").lower()
        self.group_angles = np.linspace(0, 2 * math.pi, self.num_groups, endpoint=False)
        self.perception = None
        self._active_perception_channel = "objects"
        self.perception_range = self._resolve_detection_range()
        self.spin_system: Optional[object] = None
        self._fallback_model = None
        self.detection_model = self._create_detection_model()
        # Carica dinamicamente il perception module basato su detection type
        detection_type = str(agent.config_elem.get("detection", {}).get("type", "GPS") or "GPS").upper()
        self._perception_module_class = _resolve_perception_module_class(detection_type)
        self.perception_model = self._perception_module_class(
            self.num_groups,
            self.num_spins_per_group,
            self.perception_width,
            self.group_angles,
            self.reference,
            self.perception_range,
            float(self.spin_model_params.get("agent_signal_strength", 5)),
        )
        self.reset()

    def _create_detection_model(self):
        """Create detection model."""
        context = {
            "num_groups": self.num_groups,
            "num_spins_per_group": self.num_spins_per_group,
            "perception_width": self.perception_width,
            "group_angles": self.group_angles,
            "reference": self.reference,
            "global_inhibition": self.global_inhibition,
            "perception_global_inhibition": self.global_inhibition,
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
        self.spin_system = self._spin_module_class(
            self.agent.random_generator,
            self.num_groups,
            self.num_spins_per_group,
            float(self.spin_model_params.get("T", 0.5)),
            float(self.spin_model_params.get("J", 1)),
            float(self.spin_model_params.get("nu", 0)),
            global_inhibition=self.global_inhibition,
            p_spin_up=float(self.spin_model_params.get("p_spin_up", 0.5)),
            time_delay=int(self.spin_model_params.get("time_delay", 1)),
            dynamics=self.spin_model_params.get("dynamics", "metropolis"),
        )

    def pre_run(self, objects: dict, agents: dict) -> None:
        """Pre run."""
        if self.spin_pre_run_steps <= 0:
            return
        self._update_perception(objects, agents, None, None)
        if self.perception is None:
            return
        if self.spin_system is None:
            self.reset()
            if self.spin_system is None:
                return
        for _ in range(self.spin_pre_run_steps):
            self.spin_system.step(timedelay=False)
        self.spin_system.set_p_spin_up(float(np.mean(self.spin_system.get_states())))
        self.spin_system.reset_spins()
        logger.debug("%s spin pre-run completed (%d steps)", self.agent.get_name(), self.spin_pre_run_steps)

    def step(self, agent, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Execute the simulation step."""
        if self.spin_system is None:
            self.reset()
            if self.spin_system is None:
                return
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
        raw_snapshot = self.detection_model.sense(self.agent, objects, agents, arena_shape)
        if raw_snapshot is None:
            self.perception = None
            return
        snapshot = self._convert_detection_snapshot(raw_snapshot)
        if snapshot is None:
            self.perception = None
            return
        if isinstance(snapshot, dict):
            selected, channel_name = self._select_perception_channel(snapshot)
        else:
            selected, channel_name = snapshot, "raw"
        self.perception = selected
        self._active_perception_channel = channel_name
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

    def _convert_detection_snapshot(self, snapshot):
        """Convert raw detection output into perception channels when needed."""
        if snapshot is None:
            return None
        if not isinstance(snapshot, dict):
            return snapshot
        if all(isinstance(v, np.ndarray) for v in snapshot.values() if v is not None):
            return snapshot
        if self.perception_model is None:
            return None
        try:
            return self.perception_model.build_channels(self.agent, snapshot)
        except Exception as exc:
            logger.error("%s failed to convert detection snapshot: %s", self.agent.get_name(), exc)
            return None

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
            return 0.1
        try:
            value = float(range_candidate)
        except (TypeError, ValueError):
            logger.warning("%s invalid detection range '%s', using default 0.1", self.agent.get_name(), range_candidate)
            return 0.1
        if value <= 0:
            return 0.1
        return value

    def _run_fallback(self, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Run the fallback."""
        if self.fallback_behavior in (self.moving_behavior, "none"):
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


MOVEMENT_MODEL_CLASS = SpinMovementModel
MOVEMENT_MODEL_ALIASES = ("spin_model_flocking",)
