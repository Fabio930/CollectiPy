# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""EntityManager runtime: orchestrates agents, messaging and detection."""

from __future__ import annotations

import math
import sys
import time
import multiprocessing as mp
from typing import Optional, cast

from core.main.entity_manager.loop import manager_run
from core.main.entity_manager.initialize import compute_spawn_poses, initialize_entities
from core.messaging.message_proxy import MessageProxy
from core.detection.detection_proxy import DetectionProxy
from core.util.bodies.shapes3D import ShapeState
from core.util.geometry_utils.vector3D import Vector3D
from core.util.hierarchy_overlay import HierarchyOverlay
from core.util.logging_util import get_logger

logger = get_logger("entity_manager")
FLOAT_MAX = sys.float_info.max
FLOAT_MIN = -FLOAT_MAX
# Seconds a manager waits for the detection server to merge the current tick.
DETECTION_SYNC_TIMEOUT = 2.0


class _DetectionStub:
    """Lightweight proxy exposing center_of_mass/metadata for detection."""

    __slots__ = ("_pos", "metadata")

    def __init__(self, pos: Vector3D, metadata: dict | None = None) -> None:
        self._pos = pos
        self.metadata = metadata or {}

    def center_of_mass(self) -> Vector3D:
        """Return the stored position."""
        return self._pos


class EntityManager:
    """Entity manager."""

    PLACEMENT_MAX_ATTEMPTS = 200
    PLACEMENT_MARGIN_FACTOR = 1.3
    PLACEMENT_MARGIN_EPS = 0.002

    # ----------------------------------------------------------------------
    # Queue helpers
    # ----------------------------------------------------------------------
    @staticmethod
    def _blocking_get(q, timeout: float = 0.01, sleep_s: float = 0.001):
        """Get from a queue/Pipe with a tiny sleep to avoid busy-wait."""
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

    # ----------------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------------
    def __init__(
        self,
        agents: dict,
        arena_shape,
        wrap_config=None,
        hierarchy: Optional[HierarchyOverlay] = None,
        snapshot_stride: int = 1,
        manager_id: int = 0,
        collisions: bool = False,
        message_tx=None,
        message_rx=None,
        detection_tx=None,
        detection_rx=None,
        snapshot_shapes: bool = True,
        snapshot_spins: bool = True,
    ):
        """
        Initialize the instance.

        `snapshot_shapes` / `snapshot_spins` tell whether the per-tick snapshots must
        carry full shapes (needed by the GUI) and spin data (GUI or spin exports).
        """
        self.agents = agents
        self.arena_shape = arena_shape
        self.wrap_config = wrap_config
        self.hierarchy: Optional[HierarchyOverlay] = hierarchy
        self.snapshot_stride = max(1, snapshot_stride)
        self.manager_id = manager_id
        self.collisions = collisions
        self.message_tx = message_tx
        self.message_rx = message_rx
        self.detection_tx = detection_tx
        self.detection_rx = detection_rx
        self.snapshot_shapes = snapshot_shapes
        self.snapshot_spins = snapshot_spins

        # Single message proxy shared by all messaging-enabled entities
        # in this manager. When None, messaging is effectively disabled.
        self._message_proxy = None
        self._global_min = self.arena_shape.min_vert()
        self._global_max = self.arena_shape.max_vert()
        self._invalid_hierarchy_nodes = set()

        all_entities = []
        for _, (_, entities) in self.agents.items():
            all_entities.extend(entities)
        self._manager_ticks_per_second = (
            all_entities[0].ticks() if all_entities and hasattr(all_entities[0], "ticks") else 1
        )

        if self.message_tx is not None and self.message_rx is not None:
            self._message_proxy = MessageProxy(
                all_entities, self.message_tx, self.message_rx, manager_id=self.manager_id
            )
        else:
            self._message_proxy = None

        if detection_tx is not None and detection_rx is not None:
            self._detection_proxy = DetectionProxy(
                all_entities, detection_tx, detection_rx, manager_id=self.manager_id
            )
        else:
            self._detection_proxy = None

        self._cross_detection_rate = self._resolve_cross_detection_rate()
        self._cross_det_quanta = None
        self._cross_det_budget = 0.0
        self._cross_det_budget_cap = float("inf")
        self._last_cross_det_tick = -1
        self._cached_detection_agents: dict | None = None
        self._configure_cross_detection_scheduler()

        self._global_min = self._clamp_vector_to_float_limits(self._global_min)
        self._global_max = self._clamp_vector_to_float_limits(self._global_max)

        for _, (config, entities) in self.agents.items():
            msg_cfg = config.get("messages", {}) if isinstance(config, dict) else {}
            use_proxy = bool(msg_cfg) and self._message_proxy is not None
            for e in entities:
                e.wrap_config = self.wrap_config
                if hasattr(e, "set_hierarchy_context"):
                    e.set_hierarchy_context(self.hierarchy)
                else:
                    setattr(e, "hierarchy_context", self.hierarchy)
                if use_proxy and hasattr(e, "set_message_bus"):
                    e.set_message_bus(self._message_proxy)

        logger.info("EntityManager ready with agent groups: %s", list(self.agents.keys()))
        self._initialize_hierarchy_markers()

    # ----------------------------------------------------------------------
    # Initialization
    # ----------------------------------------------------------------------
    def _resolve_cross_detection_rate(self) -> float:
        """Return how often (Hz) to pull cross-process detection snapshots."""
        rate = None
        for cfg, _ in self.agents.values():
            det_cfg = cfg.get("detection", {}) if isinstance(cfg, dict) else {}
            candidate = det_cfg.get("snapshot_per_second") or det_cfg.get("rx_per_second")
            if candidate is None:
                continue
            try:
                val = float(candidate)
            except (TypeError, ValueError):
                continue
            if rate is None or val > rate:
                rate = val
        if rate is None:
            # Not throttled: refresh every tick, like a single manager seeing live shapes.
            return math.inf
        return max(rate, 0.0)

    def _initialize_hierarchy_markers(self):
        """Initialize hierarchy markers on entities."""
        if not self.hierarchy:
            return
        level_colors = getattr(self.hierarchy, "level_colors", {})
        if not level_colors:
            return
        for (_, entities) in self.agents.values():
            for entity in entities:
                if hasattr(entity, "enable_hierarchy_marker"):
                    entity.enable_hierarchy_marker(level_colors)

    def initialize(self, random_seed: int, spawn: dict):
        """Initialize entities at the beginning of a run with the poses computed by the arena."""
        return initialize_entities(self, random_seed, spawn)

    def compute_spawn_poses(self, random_seed: int, objects: dict) -> dict:
        """Place all the agents owned by this manager (used by the arena on the full population)."""
        return compute_spawn_poses(self, random_seed, objects)

    def close(self):
        """Close resources."""
        # Close shared message proxy, if any.
        if self._message_proxy is not None:
            try:
                self._message_proxy.close()
            except Exception:
                pass

        # Close all entities.
        for _, (_, entities) in self.agents.items():
            for entity in entities:
                try:
                    entity.close()
                except Exception:
                    pass

        logger.info("EntityManager closed all resources")
        return

    # ----------------------------------------------------------------------
    # Geometry helpers
    # ----------------------------------------------------------------------
    @staticmethod
    def _clamp_value_to_float_limits(value: float) -> float:
        """Clamp a numeric value to float representable limits."""
        try:
            if math.isinf(value):
                return FLOAT_MAX if value > 0 else FLOAT_MIN
            if value > FLOAT_MAX:
                return FLOAT_MAX
            if value < FLOAT_MIN:
                return FLOAT_MIN
            return float(value)
        except Exception:
            return 0.0

    @classmethod
    def _clamp_vector_to_float_limits(cls, vec: Vector3D | None) -> Vector3D:
        """Clamp vector coordinates to float limits."""
        if vec is None:
            return Vector3D()
        return Vector3D(
            cls._clamp_value_to_float_limits(vec.x),
            cls._clamp_value_to_float_limits(vec.y),
            cls._clamp_value_to_float_limits(vec.z),
        )

    @staticmethod
    def _estimate_entity_radius(shape):
        """Estimate a placement radius for the given shape."""
        if not shape:
            return 0.0
        return shape.bounding_radius()

    @staticmethod
    def _sample_spawn_point(rng, center: Vector3D, radius: float, distribution: str, bounds, z: float, params: dict | None = None):
        """Sample a spawn position inside a disk (at height z) and clamp it to the given bounds."""
        dist = str(distribution).strip().lower() if distribution is not None else "uniform"
        params = params or {}

        if radius <= 0.0:
            x = center.x
            y = center.y
        else:
            if dist in ("gaussian", "normal"):
                try:
                    std = float(params.get("std") or params.get("sigma") or radius / 3.0)
                except (TypeError, ValueError):
                    std = radius / 3.0
                x = rng.gauss(center.x, std)
                y = rng.gauss(center.y, std)
            elif dist in ("exp", "exponential"):
                try:
                    scale = float(params.get("scale") or params.get("lambda") or radius / 2.0)
                except (TypeError, ValueError):
                    scale = radius / 2.0
                r = -math.log(max(1e-9, 1.0 - rng.random())) * max(scale, 1e-6)
                theta = rng.uniform(0.0, 2.0 * math.pi)
                x = center.x + r * math.cos(theta)
                y = center.y + r * math.sin(theta)
            elif dist == "ring":
                r = rng.uniform(radius * 0.5, radius)
                theta = rng.uniform(0.0, 2.0 * math.pi)
                x = center.x + r * math.cos(theta)
                y = center.y + r * math.sin(theta)
            else:
                r = math.sqrt(rng.uniform(0.0, 1.0)) * radius
                theta = rng.uniform(0.0, 2.0 * math.pi)
                x = center.x + r * math.cos(theta)
                y = center.y + r * math.sin(theta)

        min_x, min_y, max_x, max_y = bounds
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_y > max_y:
            min_y, max_y = max_y, min_y

        x = min(max(x, min_x), max_x)
        y = min(max(y, min_y), max_y)

        return Vector3D(x, y, z)

    def _placement_bounds(self, entity):
        """Return padded XY bounds for spawn placement."""
        radius = self._estimate_entity_radius(entity.get_shape())
        pad = radius * self.PLACEMENT_MARGIN_FACTOR + self.PLACEMENT_MARGIN_EPS
        return self._get_entity_xy_bounds(entity, pad=pad)

    def _is_overlapping_spawn(self, placed: list, entity, entity_radius: float, position: Vector3D) -> bool:
        """Return True if placing entity at position would overlap placed shapes or arena walls.

        `placed` holds (shape, radius) pairs; the entity shape is left at `position`.
        """
        shape = entity.get_shape()
        shape.translate(position)
        if shape.check_overlap(self.arena_shape)[0]:
            return True
        for other, other_radius in placed:
            other_center = other.center_of_mass()
            # Footprints too far apart cannot overlap: skip the vertex-level test.
            if math.hypot(position.x - other_center.x, position.y - other_center.y) >= entity_radius + other_radius:
                continue
            if shape.check_overlap(other)[0]:
                return True
        return False

    def _clamp_vector_to_entity_bounds(self, entity, vector: Vector3D):
        """Clamp the vector to the hierarchy bounds (if any)."""
        if not self.hierarchy:
            return vector
        node_id = getattr(entity, "hierarchy_node", None)
        if not node_id:
            return vector
        clamp_fn = getattr(self.hierarchy, "clamp_point", None)
        if not callable(clamp_fn):
            return vector
        clamped_x, clamped_y = cast(tuple[float, float], clamp_fn(node_id, vector.x, vector.y))
        if clamped_x == vector.x and clamped_y == vector.y:
            return vector
        return Vector3D(clamped_x, clamped_y, vector.z)

    def _get_entity_xy_bounds(self, entity, pad: float = 0.0):
        """Return xy bounds padded inward by `pad` to keep placements inside walls."""
        hierarchy = self.hierarchy
        use_hierarchy = False
        if hierarchy:
            info = getattr(hierarchy, "information_scope", None)
            if info and isinstance(info, dict):
                over = info.get("over")
                if over and "movement" in over:
                    use_hierarchy = True

        if not use_hierarchy:
            min_x, min_y, max_x, max_y = (
                self._global_min.x,
                self._global_min.y,
                self._global_max.x,
                self._global_max.y,
            )
        else:
            node_id = getattr(entity, "hierarchy_node", None)
            if not node_id:
                min_x, min_y, max_x, max_y = (
                    self._global_min.x,
                    self._global_min.y,
                    self._global_max.x,
                    self._global_max.y,
                )
            else:
                try:
                    min_x, min_y, max_x, max_y = hierarchy.bounds_of(node_id) if hierarchy else (
                        self._global_min.x,
                        self._global_min.y,
                        self._global_max.x,
                        self._global_max.y,
                    )
                except Exception:
                    min_x, min_y, max_x, max_y = (
                        self._global_min.x,
                        self._global_min.y,
                        self._global_max.x,
                        self._global_max.y,
                    )

        min_x += pad
        min_y += pad
        max_x -= pad
        max_y -= pad

        return min_x, min_y, max_x, max_y

    def _clamp_to_arena(self, entity):
        """
        Clamp entity position inside arena bounds when wrap-around is disabled.

        This is the only "collision" that remains when collisions=False:
        agents will never go outside the arena perimeter.
        """
        if self.wrap_config and self.wrap_config.get("unbounded"):
            return
        pos = entity.get_position()
        radius = self._estimate_entity_radius(entity.get_shape())
        min_v = self._global_min
        max_v = self._global_max
        cx = (min_v.x + max_v.x) * 0.5
        cy = (min_v.y + max_v.y) * 0.5

        # Circle-aware clamp when arena exposes a radius.
        arena_radius = None
        getter = getattr(self.arena_shape, "get_radius", None)
        if callable(getter):
            try:
                candidate = getter()
                if isinstance(candidate, (int, float)):
                    arena_radius = float(candidate)
            except Exception:
                arena_radius = None

        clamped_pos = None
        if arena_radius is not None and arena_radius > 0:
            limit = max(0.0, arena_radius - radius)
            dx = float(pos.x - cx)
            dy = float(pos.y - cy)
            dist = math.hypot(dx, dy)
            if dist > limit and dist > 0:
                scale = limit / dist if dist > 0 else 0.0
                clamped_pos = Vector3D(cx + dx * scale, cy + dy * scale, pos.z)
        if clamped_pos is None:
            min_x = min_v.x + radius
            max_x = max_v.x - radius
            min_y = min_v.y + radius
            max_y = max_v.y - radius
            if min_x > max_x or min_y > max_y:
                clamped_pos = Vector3D(cx, cy, pos.z)
            else:
                clamped_x = min(max(pos.x, min_x), max_x)
                clamped_y = min(max(pos.y, min_y), max_y)
                if clamped_x == pos.x and clamped_y == pos.y:
                    return
                clamped_pos = Vector3D(clamped_x, clamped_y, pos.z)

        if clamped_pos and (clamped_pos.x != pos.x or clamped_pos.y != pos.y):
            entity.set_position(clamped_pos)
            try:
                shape = entity.get_shape()
                shape.translate(clamped_pos)
                shape.translate_attachments(entity.get_orientation().z)
            except Exception:
                pass
            logger.debug(
                "%s clamped to arena bounds %s",
                entity.get_name(),
                (clamped_pos.x, clamped_pos.y, clamped_pos.z),
            )

    # ----------------------------------------------------------------------
    # Cross-manager detection
    # ----------------------------------------------------------------------
    def _configure_cross_detection_scheduler(self):
        """Setup throttling for cross-process detection refresh."""
        rate = self._cross_detection_rate
        if math.isinf(rate):
            self._cross_det_quanta = math.inf
            self._cross_det_budget_cap = math.inf
        elif rate <= 0:
            self._cross_det_quanta = 0.0
            self._cross_det_budget_cap = 0.0
        else:
            ticks = max(1.0, float(self._manager_ticks_per_second))
            self._cross_det_quanta = rate / ticks
            self._cross_det_budget_cap = max(1.0, rate * 2.0)
        # Prime budget to allow the first tick to pull a snapshot.
        self._cross_det_budget = 1.0
        self._last_cross_det_tick = -1

    def _should_refresh_cross_detection(self, tick: int | None = None) -> bool:
        """Return True if we should pull a fresh detection snapshot this tick."""
        if tick is None or self._cross_det_quanta is None:
            return True
        if tick == self._last_cross_det_tick:
            return False
        if self._cross_det_quanta == 0.0:
            return False
        if math.isinf(self._cross_det_quanta):
            self._last_cross_det_tick = tick
            return True
        self._cross_det_budget = min(
            self._cross_det_budget + self._cross_det_quanta,
            self._cross_det_budget_cap,
        )
        if self._cross_det_budget >= 1.0:
            self._cross_det_budget -= 1.0
            self._last_cross_det_tick = tick
            return True
        return False

    # ----------------------------------------------------------------------
    # Snapshots/helpers used by loop
    # ----------------------------------------------------------------------
    def _build_detection_agents_from_snapshot(self, snapshot) -> dict | None:
        """Convert a lightweight detection snapshot into shape-like objects."""
        if not isinstance(snapshot, list):
            return None
        grouped: dict[str, list[_DetectionStub]] = {}
        for info in snapshot:
            group_val = info.get("entity")
            if group_val is None:
                continue
            try:
                group = str(group_val)
            except Exception:
                continue
            if not group:
                continue
            uid = info.get("uid")
            try:
                x = float(info.get("x", 0.0))
                y = float(info.get("y", 0.0))
                z = float(info.get("z", 0.0))
            except (TypeError, ValueError):
                x = y = z = 0.0
            meta = {
                "entity_name": uid,
                "hierarchy_node": info.get("hierarchy_node"),
            }
            grouped.setdefault(group, []).append(_DetectionStub(Vector3D(x, y, z), meta))
        return grouped if grouped else None

    def _local_detection_snapshot(self) -> list:
        """
        Snapshot of the local agents in the detection server's format and order.

        Used when this manager owns the whole population: agents perceive the
        positions frozen at the start of the tick, exactly as with several managers.
        """
        rows = []
        for _, entities in self.agents.values():
            for entity in entities:
                pos = entity.get_position()
                rows.append(
                    {
                        "uid": entity.get_name(),
                        "entity": entity.entity(),
                        "x": pos.x,
                        "y": pos.y,
                        "z": pos.z,
                        "hierarchy_node": getattr(entity, "hierarchy_node", None),
                    }
                )
        rows.sort(key=lambda row: row["uid"])
        return rows

    def _gather_detection_agents(self, tick: int | None = None) -> dict:
        """
        Return agents grouped for perception.

        The view is a snapshot of the positions at the start of the tick: the global
        one from the detection server with several managers, a local one otherwise.
        Refreshes are throttled by _cross_detection_rate.
        """
        if self._should_refresh_cross_detection(tick):
            snapshot = None
            if self._detection_proxy is not None:
                try:
                    snapshot = self._detection_proxy.get_snapshot(wait_timeout=DETECTION_SYNC_TIMEOUT)
                except Exception:
                    snapshot = None
            else:
                snapshot = self._local_detection_snapshot()
            if snapshot is not None:
                # An empty snapshot means nobody is in range: never keep showing older positions.
                self._cached_detection_agents = self._build_detection_agents_from_snapshot(snapshot)
        return self._cached_detection_agents or {}

    def pack_detector_data(self, with_shapes: bool = True) -> dict:
        """
        Build the payload for the asynchronous CollisionDetector.

        Returns:
            {club: (shapes, velocities, forward_vectors, positions, names, headings)}

        Shapes are rigid, so the detector keeps the copies received with the first
        payload of a run and afterwards only needs the poses: `shapes` is None
        when `with_shapes` is False.
        """
        out = {}
        for _, entities in self.agents.values():
            if not entities:
                continue
            shapes = [entity.get_shape() for entity in entities] if with_shapes else None
            velocities = [entity.get_max_absolute_velocity() for entity in entities]
            vectors = [entity.get_forward_vector() for entity in entities]
            positions = [entity.get_position() for entity in entities]
            names = [entity.get_name() for entity in entities]
            headings = [entity.get_orientation().z for entity in entities]
            out[entities[0].entity()] = (shapes, velocities, vectors, positions, names, headings)
        logger.debug("Pack detector data prepared for %d groups", len(out))
        return out

    def get_agent_metadata(self, tick: int | None = None) -> dict:
        """Return per-agent metadata used by the GUI."""
        current_tick = int(tick) if tick is not None else -1
        metadata = {}
        for _, entities in self.agents.values():
            if not entities:
                continue
            group_key = entities[0].entity()
            items = []
            for entity in entities:
                msg_enabled = bool(getattr(entity, "msg_enable", False))
                msg_range = float(getattr(entity, "msg_comm_range", float("inf"))) if msg_enabled else 0.0
                items.append(
                    {
                        "name": entity.get_name(),
                        "msg_enable": msg_enabled,
                        "msg_comm_range": msg_range,
                        "msg_tx_rate": float(getattr(entity, "msgs_per_sec", 0.0)),
                        "msg_rx_rate": float(getattr(entity, "msg_receive_per_sec", 0.0)),
                        "msg_channels": getattr(entity, "msg_channel_mode", "dual"),
                        "msg_type": getattr(entity, "msg_type", None),
                        "msg_kind": getattr(entity, "msg_kind", None),
                        "handshake_partner": getattr(entity, "handshake_partner", None),
                        "handshake_state": getattr(entity, "_handshake_state", "idle"),
                        "handshake_pending": bool(getattr(entity, "_handshake_pending_accept", None)),
                        "handshake_activity_tick": int(getattr(entity, "_handshake_activity_tick", -1)),
                        "last_tx_tick": int(getattr(entity, "_last_tx_tick", -1)),
                        "last_rx_tick": int(getattr(entity, "_last_rx_tick", -1)),
                        "current_tick": current_tick,
                        "detection_range": float(entity.get_detection_range()),
                        "detection_type": getattr(entity, "detection", None),
                        "detection_frequency": float(getattr(entity, "detection_rate_per_sec", math.inf)),
                    }
                )
                # Expose current motion commands and deltas for debugging
                try:
                    items[-1]["linear_velocity_cmd"] = float(getattr(entity, "linear_velocity_cmd", 0.0))
                    items[-1]["angular_velocity_cmd"] = float(getattr(entity, "angular_velocity_cmd", 0.0))
                except Exception:
                    pass
                try:
                    # delta_orientation and forward_vector may be Vector3D
                    dov = getattr(entity, "delta_orientation", None)
                    if dov is not None:
                        items[-1]["delta_orientation_z"] = float(getattr(dov, "z", 0.0))
                    fv = getattr(entity, "forward_vector", None)
                    if fv is not None:
                        items[-1]["forward_vector_x"] = float(getattr(fv, "x", 0.0))
                        items[-1]["forward_vector_y"] = float(getattr(fv, "y", 0.0))
                except Exception:
                    pass
                # Optional per-agent snapshot metrics and orientation used by data handlers
                try:
                    metrics = getattr(entity, "snapshot_metrics", None)
                    if metrics is not None:
                        items[-1]["snapshot_metrics"] = dict(metrics)
                except Exception:
                    pass
                try:
                    orient = entity.get_orientation()
                    items[-1]["orientation_z"] = float(getattr(orient, "z", 0.0)) if orient is not None else 0.0
                except Exception:
                    items[-1]["orientation_z"] = 0.0
            metadata[group_key] = items
        for group_key, entries in metadata.items():
            for index, meta in enumerate(entries):
                if not meta.get("handshake_partner"):
                    continue
                logger.debug(
                    "metadata handshake link %s[%s] -> %s (%s)",
                    group_key,
                    index,
                    meta.get("handshake_partner"),
                    meta.get("handshake_state"),
                )
        return metadata

    def get_agent_shapes(self) -> dict:
        """Return agent shapes grouped by entity type."""
        shapes = {}
        for _, entities in self.agents.values():
            if not entities:
                continue
            group_key = entities[0].entity()
            group_shapes = []
            for entity in entities:
                shape = entity.get_shape()
                if hasattr(shape, "metadata"):
                    shape.metadata["entity_name"] = entity.get_name()
                    shape.metadata["hierarchy_node"] = getattr(entity, "hierarchy_node", None)
                # Nobody draws the agents in headless runs: the pose is all the arena needs.
                group_shapes.append(shape if self.snapshot_shapes else ShapeState(shape))
            shapes[group_key] = group_shapes
        return shapes

    def get_agent_spins(self) -> dict:
        """Return spin data grouped by entity type (empty when nobody consumes it)."""
        spins = {}
        if not self.snapshot_spins:
            return spins
        for _, entities in self.agents.values():
            if not entities:
                continue
            spins[entities[0].entity()] = [entity.get_spin_system_data() for entity in entities]
        return spins

    # ----------------------------------------------------------------------
    # Main loop
    # ----------------------------------------------------------------------
    def run(
        self,
        num_runs: int,
        time_limit: int,
        arena_queue: mp.Queue,
        agents_queue: mp.Queue,
        dec_agents_in: Optional[mp.Queue] = None,
        dec_agents_out: Optional[mp.Queue] = None,
        agent_barrier=None,
        log_context: dict | None = None,
    ):
        """Run the simulation loop."""
        manager_run(
            self,
            num_runs,
            time_limit,
            arena_queue,
            agents_queue,
            dec_agents_in,
            dec_agents_out,
            agent_barrier=agent_barrier,
            log_context=log_context,
        )
