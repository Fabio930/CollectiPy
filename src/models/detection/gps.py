# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import math
from plugin_base import DetectionModel
from plugin_registry import register_detection_model
from logging_utils import get_logger

logger = get_logger("detection.gps")

class GPSDetectionModel(DetectionModel):
    """GPS detection model: filters entities within range and returns raw info."""
    def __init__(self, agent, context: dict | None = None):
        """Initialize the instance."""
        self.agent = agent
        context = context or {}
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
        """Sense the environment and return reachable entities with metadata."""
        hierarchy = self._resolve_hierarchy(agent, arena_shape)
        reachable_agents = self._collect_agent_targets(agents, hierarchy)
        reachable_objects = self._collect_object_targets(objects)
        logger.debug(
            "%s GPS detection filtered -> objects=%d agents=%d",
            agent.get_name(),
            len(reachable_objects),
            len(reachable_agents),
        )
        return {
            "objects": reachable_objects,
            "agents": reachable_agents,
        }

    def _collect_agent_targets(self, agents, hierarchy):
        """Return neighbor agents within range with their metadata."""
        reachable = []
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
                distance = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
                if distance > self.max_detection_distance:
                    continue
                reachable.append(
                    {
                        "position": agent_pos,
                        "metadata": meta,
                        "distance": distance,
                        "entity": target_name or f"{club}_{n}",
                        "type": club,
                        "index": n,
                    }
                )
        return reachable

    def _collect_object_targets(self, objects):
        """Return configured objects within range with their info."""
        reachable = []
        for obj_type, (_, positions, strengths, uncertainties) in objects.items():
            for idx, (position, strength, uncertainty) in enumerate(zip(positions, strengths, uncertainties)):
                dx = position.x - self.agent.position.x
                dy = position.y - self.agent.position.y
                dz = position.z - self.agent.position.z
                distance = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
                if distance > self.max_detection_distance:
                    continue
                reachable.append(
                    {
                        "position": position,
                        "strength": strength,
                        "uncertainty": uncertainty,
                        "distance": distance,
                        "entity": obj_type,
                        "index": idx,
                    }
                )
        return reachable

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
