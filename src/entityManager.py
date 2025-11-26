# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""EntityManager: synchronises agents and arena."""
import logging
import math
import multiprocessing as mp
import time
from typing import Optional

from messagebus import MessageBusFactory
from random import Random
from geometry_utils.vector3D import Vector3D
from arena_hierarchy import ArenaHierarchy

logger = logging.getLogger("sim.entity_manager")


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
        hierarchy: Optional[ArenaHierarchy] = None,
        snapshot_stride: int = 1,
        manager_id: int = 0,
        collisions: bool = False
    ):
        """Initialize the instance."""
        self.agents = agents
        self.arena_shape = arena_shape
        self.wrap_config = wrap_config
        self.hierarchy = hierarchy
        self.snapshot_stride = max(1, snapshot_stride)
        self.manager_id = manager_id
        self.collisions = collisions

        self.message_buses = {}
        self._global_min = self.arena_shape.min_vert()
        self._global_max = self.arena_shape.max_vert()
        self._invalid_hierarchy_nodes = set()

        bus_context = {
            "arena_shape": self.arena_shape,
            "wrap_config": self.wrap_config,
            "hierarchy": self.hierarchy,
        }

        # Try to use a shared bus when message configs match across groups.
        msg_configs = []
        for cfg, ents in self.agents.values():
            mc = cfg.get("messages", {}) if isinstance(cfg, dict) else {}
            msg_configs.append(mc)

        shared_bus = None
        if msg_configs and all(mc == msg_configs[0] for mc in msg_configs):
            any_msg_enabled = len(msg_configs[0]) > 0
            if any_msg_enabled:
                all_entities = []
                for (_, entities) in self.agents.values():
                    all_entities.extend(entities)
                shared_bus = MessageBusFactory.create(all_entities, msg_configs[0], bus_context)

        for agent_type, (config, entities) in self.agents.items():
            any_msg_enabled = len(config.get("messages", {})) > 0
            if shared_bus:
                bus = shared_bus
                self.message_buses[agent_type] = bus
                for e in entities:
                    if hasattr(e, "set_message_bus"):
                        e.set_message_bus(bus)
            elif any_msg_enabled:
                bus = MessageBusFactory.create(entities, config.get("messages", {}), bus_context)
                self.message_buses[agent_type] = bus
                for e in entities:
                    if hasattr(e, "set_message_bus"):
                        e.set_message_bus(bus)
            else:
                self.message_buses[agent_type] = None

            for entity in entities:
                entity.wrap_config = self.wrap_config
                if hasattr(entity, "set_hierarchy_context"):
                    entity.set_hierarchy_context(self.hierarchy)
                else:
                    setattr(entity, "hierarchy_context", self.hierarchy)

        logger.info("EntityManager ready with agent groups: %s", list(self.agents.keys()))
        self._initialize_hierarchy_markers()

    # ----------------------------------------------------------------------
    # Initialization
    # ----------------------------------------------------------------------
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

    def initialize(self, random_seed: int, objects: dict):
        """Initialize entities at the beginning of a run."""
        logger.info("Initializing agents with random seed %s", random_seed)
        seed_counter = 0
        placed_shapes = []

        # Move everything far away before placement.
        for (_, entities) in self.agents.values():
            for entity in entities:
                entity.set_position(Vector3D(999, 0, 0), False)

        for (config, entities) in self.agents.values():
            for entity in entities:
                entity_seed = random_seed + seed_counter if random_seed is not None else seed_counter
                seed_counter += 1
                entity.set_random_generator(entity_seed)
                entity.reset()

                # Orientation.
                if not entity.get_orientation_from_dict():
                    rand_angle = Random.uniform(entity.get_random_generator(), 0.0, 360.0)
                    entity.set_start_orientation(Vector3D(0, 0, rand_angle))
                    logger.debug("%s initial orientation randomised to %s", entity.get_name(), rand_angle)
                else:
                    orientation = entity.get_start_orientation()
                    entity.set_start_orientation(orientation)
                    logger.debug("%s initial orientation from config %s", entity.get_name(), orientation.z)

                # Position.
                if not entity.get_position_from_dict():
                    count = 0
                    done = False
                    shape_template = entity.get_shape()
                    radius = self._estimate_entity_radius(shape_template)
                    pad = radius * self.PLACEMENT_MARGIN_FACTOR + self.PLACEMENT_MARGIN_EPS
                    bounds = self._get_entity_xy_bounds(entity, pad=pad)

                    while not done and count < self.PLACEMENT_MAX_ATTEMPTS:
                        done = True
                        entity.to_origin()
                        rand_pos = Vector3D(
                            Random.uniform(entity.get_random_generator(), bounds[0], bounds[2]),
                            Random.uniform(entity.get_random_generator(), bounds[1], bounds[3]),
                            abs(entity.get_shape().min_vert().z),
                        )
                        entity.set_position(rand_pos)
                        shape_n = entity.get_shape()

                        # Check overlap with arena.
                        if shape_n.check_overlap(self.arena_shape)[0]:
                            done = False

                        # Check overlap with other entities (same group).
                        if done:
                            for other_entity in entities:
                                if other_entity is entity:
                                    continue
                                if shape_n.check_overlap(other_entity.get_shape())[0]:
                                    done = False
                                    break

                        # Check overlap with previously placed entities (all groups).
                        if done:
                            for placed in placed_shapes:
                                if shape_n.check_overlap(placed)[0]:
                                    done = False
                                    break

                        # Check overlap with objects.
                        if done:
                            for shapes, _, _, _ in objects.values():
                                for shape_obj in shapes:
                                    if shape_n.check_overlap(shape_obj)[0]:
                                        done = False
                                        break
                                if not done:
                                    break

                        count += 1
                        if done:
                            entity.set_start_position(rand_pos, False)
                            logger.debug("%s placed at %s", entity.get_name(), (rand_pos.x, rand_pos.y, rand_pos.z))

                    if not done:
                        logger.error("Unable to place agent %s after %s attempts", entity.get_name(), count)
                        raise Exception(f"Impossible to place agent {entity.entity()} in the arena")
                else:
                    entity.to_origin()
                    position = entity.get_start_position()
                    adjusted = Vector3D(position.x, position.y, abs(entity.get_shape().min_vert().z))
                    adjusted = self._clamp_vector_to_entity_bounds(entity, adjusted)
                    entity.set_start_position(adjusted)
                    logger.debug(
                        "%s position from config %s",
                        entity.get_name(),
                        (position.x, position.y, position.z),
                    )

                placed_shapes.append(entity.get_shape())
                entity.shape.translate_attachments(entity.orientation.z)
                entity.prepare_for_run(objects, self.get_agent_shapes())
                logger.debug("%s ready for simulation", entity.get_name())
                self._apply_wrap(entity)

    def close(self):
        """Close resources."""
        for agent_type, (config, entities) in self.agents.items():
            bus = self.message_buses.get(agent_type)
            if bus:
                bus.close()
            for entity in entities:
                entity.close()
        self.message_buses.clear()
        logger.info("EntityManager closed all resources")

    # ----------------------------------------------------------------------
    # Geometry helpers
    # ----------------------------------------------------------------------
    @staticmethod
    def _estimate_entity_radius(shape):
        """Estimate a placement radius for the given shape."""
        if not shape:
            return 0.0
        getter = getattr(shape, "get_radius", None)
        if callable(getter):
            try:
                candidate = getter()
                if isinstance(candidate, (int, float)):
                    r = float(candidate)
                    if r > 0:
                        return r
            except Exception:
                pass
        center = shape.center_of_mass()
        try:
            return max(
                (Vector3D(v.x - center.x, v.y - center.y, v.z - center.z).magnitude()
                 for v in shape.vertices_list),
                default=0.05,
            )
        except Exception:
            return 0.05

    def _clamp_vector_to_entity_bounds(self, entity, vector: Vector3D):
        """Clamp the vector to the hierarchy bounds (if any)."""
        if not self.hierarchy:
            return vector
        node_id = getattr(entity, "hierarchy_node", None)
        if not node_id:
            return vector
        clamped_x, clamped_y = self.hierarchy.clamp_point(node_id, vector.x, vector.y)
        if clamped_x == vector.x and clamped_y == vector.y:
            return vector
        return Vector3D(clamped_x, clamped_y, vector.z)

    def _get_entity_xy_bounds(self, entity, pad: float = 0.0):
        """Return xy bounds padded inward by `pad` to keep placements inside walls."""
        if not self.hierarchy:
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
                node = self.hierarchy.get_node(node_id)
                if not node or not node.bounds:
                    if node_id not in self._invalid_hierarchy_nodes:
                        self._invalid_hierarchy_nodes.add(node_id)
                        logger.warning(
                            "%s references unknown hierarchy node '%s'; using arena bounds.",
                            entity.get_name(),
                            node_id,
                        )
                    min_x, min_y, max_x, max_y = (
                        self._global_min.x,
                        self._global_min.y,
                        self._global_max.x,
                        self._global_max.y,
                    )
                else:
                    bounds = node.bounds
                    min_x, min_y, max_x, max_y = (
                        bounds.min_x,
                        bounds.min_y,
                        bounds.max_x,
                        bounds.max_y,
                    )

        padded = (min_x + pad, min_y + pad, max_x - pad, max_y - pad)
        if padded[0] >= padded[2] or padded[1] >= padded[3]:
            cx = (min_x + max_x) * 0.5
            cy = (min_y + max_y) * 0.5
            return (cx, cy, cx, cy)
        return padded

    # ----------------------------------------------------------------------
    # Data extraction for GUI / detector
    # ----------------------------------------------------------------------
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
                group_shapes.append(shape)
            shapes[group_key] = group_shapes
        return shapes

    def get_agent_spins(self) -> dict:
        """Return spin data grouped by entity type."""
        spins = {}
        for _, entities in self.agents.values():
            if not entities:
                continue
            spins[entities[0].entity()] = [entity.get_spin_system_data() for entity in entities]
        return spins

    def get_agent_metadata(self) -> dict:
        """Return per-agent metadata used by the GUI."""
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
                        "detection_range": float(entity.get_detection_range()),
                        "detection_type": getattr(entity, "detection", None),
                        "detection_frequency": float(getattr(entity, "detection_rate_per_sec", math.inf)),
                    }
                )
            metadata[group_key] = items
        return metadata

    def pack_detector_data(self) -> dict:
        """
        Build the payload for the asynchronous CollisionDetector.

        Returns:
            {club: (shapes, velocities, forward_vectors, positions, names)}
        """
        out = {}
        for _, entities in self.agents.values():
            if not entities:
                continue
            shapes = [entity.get_shape() for entity in entities]
            velocities = [entity.get_max_absolute_velocity() for entity in entities]
            vectors = [entity.get_forward_vector() for entity in entities]
            positions = [entity.get_position() for entity in entities]
            names = [entity.get_name() for entity in entities]
            out[entities[0].entity()] = (shapes, velocities, vectors, positions, names)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pack detector data prepared for %d groups", len(out))
        return out

    # ----------------------------------------------------------------------
    # Wrap / clamp
    # ----------------------------------------------------------------------
    def _apply_wrap(self, entity):
        """Apply toroidal wrap, if configured."""
        if not self.wrap_config or self.wrap_config.get("unbounded"):
            return
        origin = self.wrap_config["origin"]
        width = self.wrap_config["width"]
        height = self.wrap_config["height"]
        min_x = origin.x
        min_y = origin.y
        max_x = min_x + width
        max_y = min_y + height
        pos = entity.get_position()
        new_x = ((pos.x - min_x) % width) + min_x
        new_y = ((pos.y - min_y) % height) + min_y
        if min_x <= pos.x <= max_x and min_y <= pos.y <= max_y:
            if new_x == pos.x and new_y == pos.y:
                return
        wrapped = Vector3D(new_x, new_y, pos.z)
        entity.set_position(wrapped)
        try:
            shape = entity.get_shape()
            shape.translate(wrapped)
            shape.translate_attachments(entity.get_orientation().z)
        except Exception:
            pass
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s wrapped to %s", entity.get_name(), (wrapped.x, wrapped.y, wrapped.z))

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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "%s clamped to arena bounds %s",
                    entity.get_name(),
                    (clamped_pos.x, clamped_pos.y, clamped_pos.z),
                )

    # ----------------------------------------------------------------------
    # Main loop
    # ----------------------------------------------------------------------
    def run(
        self,
        num_runs: int,
        time_limit: int,
        arena_queue: mp.Queue,
        agents_queue: mp.Queue,
        dec_agents_in: Optional[mp.Queue],
        dec_agents_out: Optional[mp.Queue],
    ):
        """Run the simulation routine."""
        ticks_per_second = 1
        for (_, entities) in self.agents.values():
            ticks_per_second = entities[0].ticks()
            break
        ticks_limit = time_limit * ticks_per_second + 1 if time_limit > 0 else 0

        run = 1
        logger.info("EntityManager starting for %s runs (time_limit=%s)", num_runs, time_limit)

        while run < num_runs + 1:
            metadata_sent = False
            metadata_snapshot = self.get_agent_metadata()
            reset = False

            data_in = self._blocking_get(arena_queue)
            if data_in is None:
                break

            # Initialisation at start of run.
            if data_in["status"][0] == 0:
                self.initialize(data_in["random_seed"], data_in["objects"])

            for agent_type, (_, entities) in self.agents.items():
                bus = self.message_buses.get(agent_type)
                if bus:
                    bus.reset_mailboxes()
                    bus.sync_agents(entities)

            # First snapshot for GUI.
            agents_data = {
                "status": [0, ticks_per_second],
                "agents_shapes": self.get_agent_shapes(),
                "agents_spins": self.get_agent_spins(),
                "agents_metadata": metadata_snapshot,
            }
            agents_queue.put(agents_data)

            t = 1
            while True:
                if ticks_limit > 0 and t >= ticks_limit:
                    break
                if data_in["status"] == "reset":
                    reset = True
                    break

                # Keep arena and agents roughly in sync in simulated time.
                while data_in["status"][0] / data_in["status"][1] < t / ticks_per_second:
                    new_msg = self._maybe_get(arena_queue, timeout=0.01)
                    if new_msg is not None:
                        data_in = new_msg
                        if data_in["status"] == "reset":
                            reset = True
                            break
                    else:
                        time.sleep(0.001)
                    agents_data = {
                        "status": [t, ticks_per_second],
                        "agents_shapes": self.get_agent_shapes(),
                        "agents_spins": self.get_agent_spins(),
                        "agents_metadata": self.get_agent_metadata(),
                    }
                    if agents_queue.qsize() == 0:
                        agents_queue.put(agents_data)
                if reset:
                    break

                latest = self._maybe_get(arena_queue, timeout=0.0)
                if latest is not None:
                    data_in = latest

                # Synchronize message buses.
                for agent_type, (_, entities) in self.agents.items():
                    bus = self.message_buses.get(agent_type)
                    if bus:
                        bus.sync_agents(entities)

                # Messaging: send then receive.
                for _, entities in self.agents.values():
                    for entity in entities:
                        if getattr(entity, "msg_enable", False) and entity.message_bus:
                            entity.send_message(t)

                for _, entities in self.agents.values():
                    for entity in entities:
                        if getattr(entity, "msg_enable", False) and entity.message_bus:
                            entity.receive_messages(t)
                        # Main agent step.
                        entity.run(t, self.arena_shape, data_in["objects"], self.get_agent_shapes())
                        self._apply_wrap(entity)
                        self._clamp_to_arena(entity)

                # Prepare snapshot for GUI.
                agents_data = {
                    "status": [t, ticks_per_second],
                    "agents_shapes": self.get_agent_shapes(),
                    "agents_spins": self.get_agent_spins(),
                }
                if not metadata_sent:
                    agents_data["agents_metadata"] = metadata_snapshot
                    metadata_sent = True

                # Build payload for collision detector (if enabled).
                detector_data = {
                    "manager_id": self.manager_id,
                    "agents": self.pack_detector_data(),
                }

                agents_queue.put(agents_data)

                # ------------------------------------------------------------------
                # Asynchronous collision corrections.
                # ------------------------------------------------------------------
                dec_data_in: dict = {}

                if self.collisions and dec_agents_in is not None and dec_agents_out is not None:
                    if t % self.snapshot_stride == 0:
                        # Send snapshot.
                        try:
                            dec_agents_in.put(detector_data)
                        except Exception:
                            pass

                        # Try to read corrections (non-blocking with small timeout).
                        dec_data_in = self._maybe_get(dec_agents_out, timeout=0.05) or {}

                # Apply collision corrections (or call post_step(None) if none).
                for _, entities in self.agents.values():
                    if not entities:
                        continue
                    group_key = entities[0].entity()
                    group_corr = dec_data_in.get(group_key, None)

                    if group_corr is not None:
                        for n, entity in enumerate(entities):
                            corr_vec = group_corr[n] if n < len(group_corr) else None
                            entity.post_step(corr_vec)
                            self._apply_wrap(entity)
                            self._clamp_to_arena(entity)
                    else:
                        for entity in entities:
                            entity.post_step(None)
                            self._apply_wrap(entity)
                            self._clamp_to_arena(entity)

                t += 1

            if t < ticks_limit and not reset:
                break

            if run < num_runs:
                # Drain extra arena messages with gentle polling.
                drained = self._maybe_get(arena_queue, timeout=0.01)
                while drained is not None:
                    data_in = drained
                    drained = self._maybe_get(arena_queue, timeout=0.0)
            elif not reset:
                self.close()

            if not reset:
                run += 1

        logger.info("EntityManager completed all runs")
