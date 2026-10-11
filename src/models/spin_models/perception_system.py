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
        obs_pos = observer.position
        agent_rows = []
        for target in detections.get("agents", []) or []:
            position = target.get("position")
            if position is None:
                continue
            agent_rows.append(
                (
                    position.x - obs_pos.x,
                    position.y - obs_pos.y,
                    position.z - obs_pos.z,
                    target.get("width", self.perception_width),
                    target.get("strength", self.agent_strength),
                )
            )

        object_rows = []
        for target in detections.get("objects", []) or []:
            position = target.get("position")
            if position is None:
                continue
            uncertainty = target.get("uncertainty", 0.0) or 0.0
            try:
                strength = float(target.get("strength", 0.0) or 0.0)
            except (TypeError, ValueError):
                strength = 0.0
            object_rows.append(
                (
                    position.x - obs_pos.x,
                    position.y - obs_pos.y,
                    position.z - obs_pos.z,
                    self.perception_width + uncertainty,
                    strength,
                )
            )

        agent_channel = self._accumulate_targets(agent_rows, observer.orientation.z)
        object_channel = self._accumulate_targets(object_rows, observer.orientation.z)
        return {
            "objects": object_channel,
            "agents": agent_channel,
            "combined": agent_channel + object_channel,
        }

    def _accumulate_targets(self, rows, observer_orient_z) -> np.ndarray:
        """Sum the weighted contributions of targets (dx, dy, dz, width, strength) into a channel."""
        if not rows:
            return np.zeros(self.num_groups * self.num_spins_per_group, dtype=np.float32)
        dx, dy, dz, width, strength = np.array(rows, dtype=np.float64).T
        if math.isfinite(self.max_detection_distance):
            in_range = np.sqrt(dx * dx + dy * dy + dz * dz) <= self.max_detection_distance
            dx, dy, width, strength = dx[in_range], dy[in_range], width[in_range], strength[in_range]
        angles = np.degrees(np.arctan2(-dy, dx))
        if self.reference == "egocentric":
            angles -= observer_orient_z
        angles = np.radians((angles + 180.0) % 360.0 - 180.0)
        angle_diffs = np.abs(self.group_angles[None, :] - angles[:, None])
        angle_diffs = np.minimum(angle_diffs, 2 * math.pi - angle_diffs)
        sigma = np.maximum(width, 1e-6)[:, None]
        weights = (self.perception_width / sigma) * np.exp(-(angle_diffs ** 2) / (2 * (sigma ** 2)))
        weights *= strength[:, None]
        return np.repeat(weights.sum(axis=0), self.num_spins_per_group).astype(np.float32)
