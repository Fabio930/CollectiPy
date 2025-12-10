# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Base arena definitions (seed handling, object creation, hierarchy)."""
from __future__ import annotations

<<<<<<< Updated upstream
import math
import random
import sys
import time
=======
import math, random, sys, time
>>>>>>> Stashed changes
from typing import Any, Optional

from core.configuration.config import Config
from core.entities import EntityFactory
from core.util.dataHandling import DataHandlingFactory
from core.util.geometry_utils.vector3D import Vector3D
from core.util.hierarchy_overlay import Bounds2D, HierarchyOverlay
from core.util.logging_util import get_logger

logger = get_logger("arena")

FLOAT_MAX = sys.float_info.max
FLOAT_MIN = -FLOAT_MAX
BOUNDARY_RADIUS_EPS = 0.0001


class BoundaryGrid:
    """Minimal boundary grid to track cells near arena limits."""

    def __init__(self, min_v: Vector3D, max_v: Vector3D, cell_size: float):
        self.min_v = min_v
        self.max_v = max_v
        self.cell_size = max(cell_size, 0.00001)
        # Strips: band1 is closest to edge, band2 is adjacent.
        self.band1 = self.cell_size * 1.0
        self.band2 = self.cell_size * 2.0

    def band_for_point(self, point: Vector3D | None) -> int:
        """
        Return 0 if outside boundary strips,
        1 if in the closest strip, 2 if in the second strip.
        """
        if point is None:
            return 0
        dx_min = abs(point.x - self.min_v.x)
        dx_max = abs(point.x - self.max_v.x)
        dy_min = abs(point.y - self.min_v.y)
        dy_max = abs(point.y - self.max_v.y)

        near_edge = min(dx_min, dx_max, dy_min, dy_max)
        if near_edge <= self.band1:
            return 1
        if near_edge <= self.band2:
            return 2
        return 0


class Arena:
    """Common arena base class (seed, hierarchy, object creation)."""

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        self.random_generator = random.Random()
        self._seed_random = random.SystemRandom()
        raw_tps = config_elem.environment.get("ticks_per_second", 3) if hasattr(config_elem, "environment") else 3
        if isinstance(raw_tps, (int, float, str)):
            try:
                self.ticks_per_second = int(raw_tps)
            except (TypeError, ValueError):
                self.ticks_per_second = 3
        else:
            self.ticks_per_second = 3
        configured_seed = config_elem.arena.get("random_seed")
        if not isinstance(configured_seed, (int, float, str)):
            configured_seed = 0
        try:
            self._configured_seed = int(configured_seed)
        except (TypeError, ValueError):
            self._configured_seed = 0
        self.random_seed = self._configured_seed
        self._id = "none" if config_elem.arena.get("_id") == "abstract" else config_elem.arena.get("_id", "none")
        self.objects = {
            object_type: (config_elem.environment.get("objects", {}).get(object_type), [])
            for object_type in config_elem.environment.get("objects", {}).keys()
        }
        self.agents_shapes = {}
        self.agents_spins = {}
        self.agents_metadata = {}
        self.data_handling = None
        self._boundary_grid: BoundaryGrid | None = None
        if len(config_elem.results) > 0 and not len(config_elem.gui) > 0:
            self.data_handling = DataHandlingFactory.create_data_handling(config_elem)
        self._hierarchy = None
        self._hierarchy_enabled = "hierarchy" in config_elem.arena
        self._hierarchy_config = config_elem.arena.get("hierarchy") if self._hierarchy_enabled else None
        gui_cfg = config_elem.gui if hasattr(config_elem, "gui") else {}
        throttle_cfg = gui_cfg.get("throttle", {})
        if isinstance(throttle_cfg, (int, float)):
            throttle_cfg = {"max_backlog": throttle_cfg}
        raw_threshold = throttle_cfg.get("max_backlog", gui_cfg.get("max_backlog", 6))
        if raw_threshold is None:
            threshold = 6
        elif not isinstance(raw_threshold, (int, float, str)):
            threshold = 6
        else:
            try:
                threshold = int(raw_threshold)
            except (TypeError, ValueError):
                threshold = 6
        self._gui_backpressure_threshold = max(0, threshold)
        raw_interval = throttle_cfg.get("poll_interval_ms", gui_cfg.get("poll_interval_ms", 8))
        if raw_interval is None:
            interval_ms = 8.0
        elif not isinstance(raw_interval, (int, float, str)):
            interval_ms = 8.0
        else:
            try:
                interval_ms = float(raw_interval)
            except (TypeError, ValueError):
                interval_ms = 8.0
        enabled_flag = throttle_cfg.get("enabled")
        if enabled_flag is None:
            enabled_flag = gui_cfg.get("adaptive_throttle", True)
        self._gui_backpressure_enabled = bool(enabled_flag) if enabled_flag is not None else True
        self._gui_backpressure_interval = max(0.001, interval_ms / 1000.0)
        self._gui_backpressure_active = False
        self.quiet = getattr(config_elem, "quiet", False) if config_elem else False
        self._speed_multiplier = 1.0

    # ----- Queue helpers -------------------------------------------------
    @staticmethod
    def _blocking_get(q, timeout: float = 0.01, sleep_s: float = 0.001):
        """Get from a queue/Pipe with tiny sleep to avoid busy-wait."""
        while True:
            if hasattr(q, "poll"):
                try:
                    if q.poll(timeout):
                        return q.get()
                except EOFError:
                    return None
            else:
                try:
                    return q.get(timeout=timeout)
                except EOFError:
                    return None
                except Exception:
                    pass
            time.sleep(sleep_s)

    @staticmethod
    def _maybe_get(q, timeout: float = 0.0):
        """Non-blocking get with optional timeout."""
        if hasattr(q, "poll"):
            try:
                if q.poll(timeout):
                    return q.get()
            except EOFError:
                return None
            return None
        try:
            return q.get(timeout=timeout)
        except EOFError:
            return None
        except Exception:
            return None

    # ----- Seed/state helpers -------------------------------------------
    def get_id(self):
        """Return the id."""
        return self._id

    def get_seed(self):
        """Return the seed."""
        return self.random_seed

    def get_random_generator(self):
        """Return the random generator."""
        return self.random_generator

    def increment_seed(self):
        """Increment seed."""
        self.random_seed += 1

    def reset_seed(self):
        """Reset the seed to a deterministic starting point."""
        base_seed = self._configured_seed if self._configured_seed is not None else 0
        if base_seed < 0:
            base_seed = 0
        self.random_seed = base_seed

    def randomize_seed(self):
        """Assign a random seed (used when GUI reset is requested)."""
        self.random_seed = self._seed_random.randrange(0, 2**32)

    def set_random_seed(self):
        """Set the random seed."""
        if self.random_seed > -1:
            self.random_generator.seed(self.random_seed)
        else:
            self.random_seed = self._seed_random.randrange(0, 2**32)
            self.random_generator.seed(self.random_seed)

    # ----- Lifecycle -----------------------------------------------------
    def initialize(self):
        """Initialize the component state (objects creation only)."""
        self.reset()
        created_counts: dict[str, int] = {}
        for key, (config, entities) in self.objects.items():
            object_count = config["number"]
            logger.info("Creating %s object(s) of type %s", object_count, key)
            for n in range(config["number"]):
                entities.append(EntityFactory.create_entity(entity_type="object_" + key, config_elem=config, _id=n))
            created_counts[key] = object_count

        if created_counts:
            total_created = sum(created_counts.values())
            logger.info("Objects initialized: total=%d breakdown=%s", total_created, created_counts)
        else:
            logger.info("No arena objects configured")

    def run(self, num_runs, time_limit, arena_queue, agents_queue, gui_in_queue, dec_arena_in, gui_control_queue, render=False):
        """Run the simulation routine (implemented by subclasses)."""
        raise NotImplementedError

    def reset(self):
        """Reset the component state (seed only)."""
        self.set_random_seed()

    def close(self):
        """Close the component resources."""
        for (config, entities) in self.objects.values():
            for n in range(len(entities)):
                entities[n].close()
        if self.data_handling is not None:
            self.data_handling.close(self.agents_shapes)
        logger.info("Arena closed all resources")
        return

    # ----- Hierarchy / wrap ----------------------------------------------
    def get_wrap_config(self) -> Optional[dict[str, Any]]:
        """Optional metadata describing wrap-around projection (default: None)."""
        return None

    def get_hierarchy(self):
        """Return the hierarchy."""
        return self._hierarchy

    def _create_hierarchy(self, bounds: Optional[Bounds2D]):
        """Create hierarchy."""
        if not self._hierarchy_enabled or self._hierarchy_config is None:
            return None

        cfg = self._hierarchy_config or {}
        raw_depth = cfg.get("depth", 0)
        raw_branches = cfg.get("branches", 1)
        try:
            depth = int(raw_depth)
        except (TypeError, ValueError):
            depth = 0
        try:
            branches = int(raw_branches)
        except (TypeError, ValueError):
            branches = 1
        info_scope_cfg = cfg.get("information_scope")

        try:
            return HierarchyOverlay(
                bounds,  # type: ignore
                depth=depth,
                branches=branches,
                owner_id="arena",
                info_scope_config=info_scope_cfg,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid hierarchy configuration: {exc}") from exc

    # ----- Numeric guards -----------------------------------------------
    @staticmethod
    def _clamp_value_to_float_limits(value: float) -> float:
        """Clamp a numeric value to float representable limits."""
        try:
            if value > FLOAT_MAX:
                return FLOAT_MAX
            if value < FLOAT_MIN:
                return FLOAT_MIN
            if math.isinf(value):
                return FLOAT_MAX if value > 0 else FLOAT_MIN
            return float(value)
        except Exception:
            return 0.0

    @classmethod
    def _clamp_vector_to_float_limits(cls, vec: Optional[Vector3D]) -> Optional[Vector3D]:
        """Clamp vector coordinates to float limits."""
        if vec is None:
            return None
        return Vector3D(
            cls._clamp_value_to_float_limits(vec.x),
            cls._clamp_value_to_float_limits(vec.y),
            cls._clamp_value_to_float_limits(vec.z),
        )
