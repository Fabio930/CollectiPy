# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import logging
import numpy as np
from plugin_base import DetectionModel
from plugin_registry import register_detection_model
from logging_utils import get_logger

logger = get_logger("detection.visual")

class VisualDetectionModel(DetectionModel):
    """
    Placeholder for a future visual detection implementation.

    Currently returns a zeroed perception vector with the expected size
    so that movement models can continue to operate.
    """
    def __init__(self, agent, context: dict | None = None):
        """Initialize the instance."""
        context = context or {}
        self.num_groups = context.get("num_groups", 1)
        self.num_spins_per_group = context.get("num_spins_per_group", 1)

    def sense(self, agent, objects: dict, agents: dict, arena_shape=None):
        """Sense the environment and update perception."""
        perception = np.zeros(self.num_groups * self.num_spins_per_group)
        logger.debug("%s visual detection placeholder invoked", agent.get_name())
        return perception

register_detection_model("visual", lambda agent, context=None: VisualDetectionModel(agent, context))
