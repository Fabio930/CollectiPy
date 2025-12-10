# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Concrete arena shape classes."""
from __future__ import annotations

import math

from core.configuration.config import Config
from core.main.arena.base import Arena
from core.main.arena.solid import SolidArena
from core.util.geometry_utils.vector3D import Vector3D
from core.util.logging_util import get_logger

logger = get_logger("arena")


class AbstractArena(Arena):
    """Abstract arena."""

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        logger.info("Abstract arena created successfully")
        self._hierarchy = self._create_hierarchy(None)

    def get_shape(self):
        """Return the shape."""
        return None

    def close(self):
        """Close the component resources."""
        super().close()


class UnboundedArena(SolidArena):
    """Unbounded arena rendered as a large square without wrap-around."""

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        dims = config_elem.arena.get("dimensions", {})
        raw = dims.get("diameter", None)
        diameter_val: float = -1.0
        if isinstance(raw, (int, float, str)):
            try:
                diameter_val = float(raw)
            except (TypeError, ValueError):
                diameter_val = -1.0
        self.diameter: float = diameter_val
        if self.diameter <= 0:
            self.diameter = self._estimate_initial_diameter(config_elem)
        if self.diameter <= 0:
            raise ValueError("UnboundedArena could not derive a positive initial diameter")
        super().__init__(config_elem)
        logger.info(
            "Unbounded arena created (diameter=%.3f, square side=%.3f)",
            self.diameter,
            self.diameter,
        )

    def _estimate_initial_diameter(self, config_elem: Config) -> float:
        """
        Heuristic initial span when the user does not provide a diameter.
        Uses agent count/size to choose a finite square for spawning/rendering.
        """
        agents_cfg = config_elem.environment.get("agents", {}) if hasattr(config_elem, "environment") else {}
        total = 0
        max_diam = 0.05
        for cfg in agents_cfg.values():
            if not isinstance(cfg, dict):
                continue
            num_val = cfg.get("number", 0)
            if isinstance(num_val, (list, tuple)) and num_val:
                num_val = num_val[0]
            if isinstance(num_val, (int, float, str)):
                try:
                    num_int = int(num_val)
                except (TypeError, ValueError):
                    num_int = 0
            else:
                num_int = 0
            total += max(num_int, 0)
            diam_val = cfg.get("diameter", max_diam)
            if isinstance(diam_val, (int, float, str)):
                try:
                    diam = float(diam_val)
                    if diam > max_diam:
                        max_diam = diam
                except (TypeError, ValueError):
                    pass
        if total <= 0:
            return 2.0
        agent_radius = max_diam * 0.5
        disk_radius = max(agent_radius * 4.0, agent_radius * math.sqrt(total) * 2.5, 0.5)
        return max(disk_radius * 2.0, 1.0)

    def _arena_shape_type(self):
        """Use a special unbounded footprint."""
        return "unbounded"

    def _arena_shape_config(self, config_elem: Config):
        """Adapt the configuration parameters for the unbounded factory."""
        return {
            "color": config_elem.arena.get("color", "gray"),
            "side": self.diameter,
        }

    def get_wrap_config(self):
        """Return the wrap config."""
        half = self.diameter * 0.5
        origin = Vector3D(-half, -half, 0)
        return {
            "unbounded": True,
            "origin": origin,
            "width": self.diameter,
            "height": self.diameter,
            "initial_half": half,
        }


class CircularArena(SolidArena):
    """Circular arena."""

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        dims = config_elem.arena.get("dimensions", {})
        self.height = dims.get("height", 1)
        self.radius = dims.get("radius", 1)
        self.color = config_elem.arena.get("color", "gray")
        logger.info("Circular arena created successfully")


class RectangularArena(SolidArena):
    """Rectangular arena."""

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        dims = config_elem.arena.get("dimensions", {})
        self.height = dims.get("height", 1)
        self.width = dims.get("width", 1)
        self.depth = dims.get("depth", 1)
        self.length = self.width
        self.color = config_elem.arena.get("color", "gray")
        logger.info("Rectangular arena created successfully")


class SquareArena(SolidArena):
    """Square arena."""

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        dims = config_elem.arena.get("dimensions", {})
        self.height = dims.get("height", 1)
        self.side = dims.get("side", 1)
        self.color = config_elem.arena.get("color", "gray")
        logger.info("Square arena created successfully")
