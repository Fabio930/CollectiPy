# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import math
import numpy as np
from plugin_base import DetectionModel
from plugin_registry import register_detection_model
from models.utils import normalize_angle
from logging_utils import get_logger

logger = get_logger("detection.gps")

class GPSDetectionModel(DetectionModel):
    """Gps detection model."""
    def __init__(self, agent, context: dict | None = None):
        """Initialize the instance."""
        self.agent = agent
        context = context or {}
        self.num_groups = context.get("num_groups", 8)
        self.num_spins_per_group = context.get("num_spins_per_group", 12)
        self.perception_width = context.get("perception_width", 0.5)
        self.group_angles = context.get("group_angles", np.linspace(0, 2 * math.pi, self.num_groups, endpoint=False))
        self.reference = context.get("reference", "egocentric")
        self.perception_global_inhibition = context.get("perception_global_inhibition", 0)
        fallback_distance = 0.1
        if hasattr(self.agent, "get_detection_range"):
            try:
                fallback_distance = float(self.agent.get_detection_range())
            except Exception:
                fallback_distance = 0.1
        elif hasattr(self.agent, "perception_distance"):
            try:
                fallback_distance = float(self.agent.perception_distance)
            except Exception:
                fallback_distance = 0.1
        try:
            self.max_detection_distance = float(
                context.get(
                    "max_detection_distance",
                    fallback_distance,
                )
            )
        except (TypeError, ValueError):
            self.max_detection_distance = fallback_distance

    def sense(self, agent, objects: dict, agents: dict, arena_shape=None):
        """Sense the environment and expose all perception channels."""
        channel_size = self.num_groups * self.num_spins_per_group
        agent_channel = np.zeros(channel_size)
        object_channel = np.zeros(channel_size)
        hierarchy = self._resolve_hierarchy(agent, arena_shape)
        self._collect_agent_targets(agent_channel, agents, hierarchy)
        self._collect_object_targets(object_channel, objects)
        self._apply_global_inhibition(agent_channel)
        self._apply_global_inhibition(object_channel)
        combined_channel = agent_channel + object_channel
        logger.debug(
            "%s GPS detection objects_max=%.4f agents_max=%.4f combined_max=%.4f",
            agent.get_name(),
            float(np.max(object_channel)) if object_channel.size else 0.0,
            float(np.max(agent_channel)) if agent_channel.size else 0.0,
            float(np.max(combined_channel)) if combined_channel.size else 0.0,
        )
        return {
            "objects": object_channel,
            "agents": agent_channel,
            "combined": combined_channel,
        }

    def _collect_agent_targets(self, perception, agents, hierarchy):
        """Accumulate perception contributed by neighbor agents."""
        for club, agent_shapes in agents.items():
            for n, shape in enumerate(agent_shapes):
                meta = getattr(shape, "metadata", {}) if hasattr(shape, "metadata") else {}
                target_name = meta.get("entity_name")
                if target_name:
                    if target_name == self.agent.get_name():
                        continue
                elif f"{club}_{n}" == self.agent.get_name():
                    continue
                target_node = meta.get("hierarchy_node")
                if not self._hierarchy_allows_agent(target_node, hierarchy):
                    continue
                agent_pos = shape.center_of_mass()
                dx = agent_pos.x - self.agent.position.x
                dy = agent_pos.y - self.agent.position.y
                dz = agent_pos.z - self.agent.position.z
                self._accumulate_target(perception, dx, dy, dz, self.perception_width, 5)

    def _collect_object_targets(self, perception, objects):
        """Accumulate perception contributed by configured objects."""
        for _, (_, positions, strengths, uncertainties) in objects.items():
            for position, strength, uncertainty in zip(positions, strengths, uncertainties):
                dx = position.x - self.agent.position.x
                dy = position.y - self.agent.position.y
                dz = position.z - self.agent.position.z
                effective_width = self.perception_width + uncertainty
                self._accumulate_target(perception, dx, dy, dz, effective_width, strength)

    def _apply_global_inhibition(self, perception_channel):
        """Apply the configured global inhibition to a channel."""
        if self.perception_global_inhibition == 0:
            return
        perception_channel -= self.perception_global_inhibition

    def _accumulate_target(self, perception, dx, dy, dz, effective_width, strength):
        """Accumulate the target."""
        distance = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
        if distance > self.max_detection_distance:
            return
        angle_to_object = math.degrees(math.atan2(-dy, dx))
        self._apply_weights(perception, angle_to_object, effective_width, strength)

    def _apply_weights(self, perception, angle_to_object, effective_width, strength):
        """Apply the weights."""
        if self.reference == "egocentric":
            angle_to_object -= self.agent.orientation.z
        angle_to_object = normalize_angle(angle_to_object)
        angle_diffs = np.abs(self.group_angles - math.radians(angle_to_object))
        angle_diffs = np.minimum(angle_diffs, 2 * math.pi - angle_diffs)
        sigma = max(effective_width, 1e-6)
        weights = (self.perception_width / sigma) * np.exp(-(angle_diffs ** 2) / (2 * (sigma ** 2)))
        weights *= strength
        perception += np.repeat(weights, self.num_spins_per_group)

    def _hierarchy_allows_agent(self, target_node, hierarchy) -> bool:
        """Return True if the observer can interact with the target based on hierarchy."""
        checker = getattr(self.agent, "allows_hierarchical_link", None)
        if not callable(checker):
            return True
        try:
            return bool(checker(target_node, "detection", hierarchy))
        except Exception:
            return False

    @staticmethod
    def _resolve_hierarchy(agent, arena_shape):
        """Resolve the hierarchy reference from the arena shape or the agent context."""
        if arena_shape is not None:
            metadata = getattr(arena_shape, "metadata", None)
            if metadata:
                hierarchy = metadata.get("hierarchy")
                if hierarchy:
                    return hierarchy
        return getattr(agent, "hierarchy_context", None)

register_detection_model("GPS", lambda agent, context=None: GPSDetectionModel(agent, context))
