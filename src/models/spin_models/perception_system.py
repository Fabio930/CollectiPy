# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Perception system model for spin-based movement behaviours."""
from __future__ import annotations

import math
import numpy as np
from models.utility_functions import normalize_angle

class PerceptionModule:
    """Perception layer converting detections into spin-friendly channels."""
    def __init__(
        self,
        num_groups: int,
        num_spins_per_group: int,
        perception_width: float,
        group_angles: np.ndarray,
        reference: str = "egocentric",
        max_detection_distance: float | None = None,
        agent_strength: float = 5.0,
    ):
        self.num_groups = num_groups
        self.num_spins_per_group = num_spins_per_group
        self.perception_width = perception_width
        self.group_angles = group_angles
        self.reference = reference
        self.max_detection_distance = (
            float(max_detection_distance) if max_detection_distance is not None else math.inf
        )
        self.agent_strength = agent_strength

    def build_channels(self, observer, detections: dict) -> dict[str, np.ndarray]:
        """Convert raw detections into object/agent/combined perception channels."""
        channel_size = self.num_groups * self.num_spins_per_group
        agent_channel = np.zeros(channel_size, dtype=np.float32)
        object_channel = np.zeros(channel_size, dtype=np.float32)
        obs_pos = observer.position
        obs_orient_z = observer.orientation.z
        for target in detections.get("agents", []) or []:
            position = target.get("position")
            if position is None:
                continue
            dx = position.x - obs_pos.x
            dy = position.y - obs_pos.y
            dz = position.z - obs_pos.z
            strength = target.get("strength", self.agent_strength)
            width = target.get("width", self.perception_width)
            self._accumulate_target(agent_channel, dx, dy, dz, width, strength, obs_orient_z)

        for target in detections.get("objects", []) or []:
            position = target.get("position")
            if position is None:
                continue
            dx = position.x - obs_pos.x
            dy = position.y - obs_pos.y
            dz = position.z - obs_pos.z
            uncertainty = target.get("uncertainty", 0.0) or 0.0
            width = self.perception_width + uncertainty
            try:
                strength = float(target.get("strength", 0.0) or 0.0)
            except (TypeError, ValueError):
                strength = 0.0
            self._accumulate_target(object_channel, dx, dy, dz, width, strength, obs_orient_z)

        combined_channel = agent_channel + object_channel
        return {
            "objects": object_channel,
            "agents": agent_channel,
            "combined": combined_channel,
        }

    def _accumulate_target(self, perception, dx, dy, dz, effective_width, strength, observer_orient_z):
        """Accumulate weighted contribution of a target into a perception channel."""
        distance = math.hypot(dx, dy, dz)
        if math.isfinite(self.max_detection_distance) and distance > self.max_detection_distance:
            return
        angle_to_object = math.degrees(math.atan2(-dy, dx))
        if self.reference == "egocentric":
            angle_to_object -= observer_orient_z
        angle_to_object = normalize_angle(angle_to_object)
        angle_diffs = np.abs(self.group_angles - math.radians(angle_to_object))
        angle_diffs = np.minimum(angle_diffs, 2 * math.pi - angle_diffs)
        sigma = max(effective_width, 1e-6)
        weights = (self.perception_width / sigma) * np.exp(-(angle_diffs ** 2) / (2 * (sigma ** 2)))
        weights *= strength
        perception += np.repeat(weights, self.num_spins_per_group)