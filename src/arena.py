# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import time, math, random
from typing import Optional, Any
import multiprocessing as mp
from config import Config
from random import Random
from bodies.shapes3D import Shape3DFactory
from entity import EntityFactory
from geometry_utils.vector3D import Vector3D
from dataHandling import DataHandlingFactory
from hierarchy_overlay import HierarchyOverlay, Bounds2D
from logging_utils import get_logger, start_run_logging, shutdown_logging

logger = get_logger("arena")
class ArenaFactory():

    """Arena factory."""
    @staticmethod
    def create_arena(config_elem:Config):
        """Create arena."""
        if config_elem.arena.get("_id") in ("abstract", "none", None):
            return AbstractArena(config_elem)
        elif config_elem.arena.get("_id") == "circle":
            return CircularArena(config_elem)
        elif config_elem.arena.get("_id") == "rectangle":
            return RectangularArena(config_elem)
        elif config_elem.arena.get("_id") == "square":
            return SquareArena(config_elem)
        elif config_elem.arena.get("_id") == "unbounded":
            return UnboundedArena(config_elem)
        else:
            raise ValueError(f"Invalid shape type: {config_elem.arena['_id']} valid types are: none, abstract, circle, rectangle, square, unbounded")

class Arena():
    
    """Arena."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        self.random_generator = Random()
        self._seed_random = random.SystemRandom()
        self.ticks_per_second = int(config_elem.environment.get("ticks_per_second", 3))
        configured_seed = config_elem.arena.get("random_seed")
        if configured_seed is None:
            configured_seed = 0
        self._configured_seed = int(configured_seed)
        self.random_seed = self._configured_seed
        self._id = "none" if config_elem.arena.get("_id") == "abstract" else config_elem.arena.get("_id","none") 
        self.objects = {object_type: (config_elem.environment.get("objects",{}).get(object_type),[]) for object_type in config_elem.environment.get("objects",{}).keys()}
        self.agents_shapes = {}
        self.agents_spins = {}
        self.agents_metadata = {}
        self.data_handling = None
        if len(config_elem.results) > 0 and not len(config_elem.gui) > 0 : self.data_handling = DataHandlingFactory.create_data_handling(config_elem)
        self._hierarchy = None
        self._hierarchy_enabled = "hierarchy" in config_elem.arena
        self._hierarchy_config = config_elem.arena.get("hierarchy") if self._hierarchy_enabled else None
        gui_cfg = config_elem.gui if hasattr(config_elem, "gui") else {}
        throttle_cfg = gui_cfg.get("throttle", {})
        if isinstance(throttle_cfg, (int, float)):
            throttle_cfg = {"max_backlog": throttle_cfg}
        raw_threshold = throttle_cfg.get("max_backlog", gui_cfg.get("max_backlog", 6))
        try:
            threshold = int(raw_threshold)
        except (TypeError, ValueError):
            threshold = 6
        self._gui_backpressure_threshold = max(0, threshold)
        raw_interval = throttle_cfg.get("poll_interval_ms", gui_cfg.get("poll_interval_ms", 8))
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

    def initialize(self):
        """Initialize the component state."""
        self.reset()
        created_counts: dict[str, int] = {}
        for key,(config,entities) in self.objects.items():
            object_count = config["number"]
            logger.info("Creating %s object(s) of type %s", object_count, key)
            for n in range(config["number"]):
                entities.append(EntityFactory.create_entity(entity_type="object_"+key,config_elem=config,_id=n))
            created_counts[key] = object_count

        if created_counts:
            total_created = sum(created_counts.values())
            logger.info("Objects initialized: total=%d breakdown=%s", total_created, created_counts)
        else:
            logger.info("No arena objects configured")
                
    def run(self,num_runs,time_limit, arena_queue:mp.Queue, agents_queue:mp.Queue, gui_in_queue:mp.Queue, dec_arena_in:mp.Queue, gui_control_queue:mp.Queue, render:bool=False):
        """Run the simulation routine."""
        pass

    def reset(self):
        """Reset the component state."""
        self.set_random_seed()

    def close(self):
        """Close the component resources."""
        for (config,entities) in self.objects.values():
            for n in range(len(entities)):
                entities[n].close()
        if self.data_handling is not None: self.data_handling.close(self.agents_shapes)
        return

    def get_wrap_config(self):
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
        depth = int(cfg.get("depth", 0))
        branches = int(cfg.get("branches", 1))
        info_scope_cfg = cfg.get("information_scope")

        try:
            return HierarchyOverlay(
                bounds, # type: ignore
                depth=depth,
                branches=branches,
                owner_id="arena",
                info_scope_config=info_scope_cfg,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid hierarchy configuration: {exc}") from exc



class AbstractArena(Arena):
    
    """Abstract arena."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        logger.info("Abstract arena created successfully")
        self._hierarchy = self._create_hierarchy(None)
    
    def get_shape(self):
        """Return the shape."""
        pass
    
    def close(self):
        """Close the component resources."""
        super().close()

PLACEMENT_MAX_ATTEMPTS = 200
PLACEMENT_MARGIN_FACTOR = 1.3
PLACEMENT_MARGIN_EPS = 0.002


class SolidArena(Arena):
    
    """Solid arena."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        self._grid_origin = None
        self._grid_cell_size = None
        self.shape = self._build_arena_shape(config_elem)
        self._update_hierarchy_from_shape()

    def _build_arena_shape(self, config_elem:Config):
        """Return the collision shape based on the arena configuration."""
        shape_type = self._arena_shape_type()
        shape_cfg = self._arena_shape_config(config_elem)
        return Shape3DFactory.create_shape("arena", shape_type, shape_cfg)

    def _arena_shape_type(self):
        """Return the default shape id used for the arena."""
        return self._id

    def _arena_shape_config(self, config_elem:Config):
        """Return the arena configuration passed to the shape factory."""
        shape_cfg = dict(config_elem.arena.get("dimensions", {}))
        shape_cfg["color"] = config_elem.arena.get("color", "gray")
        return shape_cfg

    def get_shape(self):
        """Return the shape."""
        return self.shape
    
    def initialize(self):
        """Initialize the component state."""
        super().initialize()
        min_v = self.shape.min_vert()
        max_v = self.shape.max_vert()
        rng = self.random_generator
        self._grid_origin = Vector3D(min_v.x, min_v.y, 0)
        radii_map, max_radius = self._compute_entity_radii()
        self._grid_cell_size = max(max_radius * 2.0, 0.05)
        occupancy = {}
        for (config, entities) in self.objects.values():
            n_entities = len(entities)
            for entity in entities:
                entity.set_position(Vector3D(999, 0, 0), False)
            for n in range(n_entities):
                entity = entities[n]
                if not entity.get_orientation_from_dict():
                    rand_angle = Random.uniform(rng, 0.0, 360.0)
                    entity.set_start_orientation(Vector3D(0, 0, rand_angle))
                position = entity.get_start_position()
                if not entity.get_position_from_dict():
                    placed = self._place_entity_random(
                        entity,
                        radii_map[id(entity)],
                        occupancy,
                        rng,
                        min_v,
                        max_v
                    )
                    if not placed:
                        raise Exception(f"Impossible to place object {entity.entity()} in the arena")
                else:
                    entity.to_origin()
                    target = Vector3D(position.x, position.y, position.z + abs(entity.get_shape().min_vert().z))
                    entity.set_start_position(target)
                    shape = entity.get_shape()
                    if shape.check_overlap(self.shape)[0]:
                        logger.warning(
                            "Configured position for object %s overlaps arena walls; re-sampling position.",
                            entity.entity()
                        )
                        placed = self._place_entity_random(
                            entity,
                            radii_map[id(entity)],
                            occupancy,
                            rng,
                            min_v,
                            max_v
                        )
                        if not placed:
                            raise Exception(f"Impossible to place object {entity.entity()} in the arena")
                    else:
                        self._register_shape_in_grid(shape, target, radii_map[id(entity)], occupancy)

    def pack_objects_data(self) -> dict:
        """Pack objects data."""
        out = {}
        for _,entities in self.objects.values():
            shapes = []
            positions = []
            strengths = []
            uncertainties = []
            for n in range(len(entities)):
                shapes.append(entities[n].get_shape())
                positions.append(entities[n].get_position())
                strengths.append(entities[n].get_strength())
                uncertainties.append(entities[n].get_uncertainty())
            out.update({entities[0].entity():(shapes,positions,strengths,uncertainties)})
        return out

    @staticmethod
    def _format_position(position):
        """Return a readable position string."""
        if position is None:
            return "(unset)"
        try:
            return f"({position.x:.3f},{position.y:.3f},{position.z:.3f})"
        except AttributeError:
            return str(position)

    def _collect_object_positions(self) -> dict:
        """Collect a human-readable description for each object's location."""
        grouped: dict[str, list[str]] = {}
        for _, entities in self.objects.values():
            for entity in entities:
                pos = self._format_position(entity.get_position())
                grouped.setdefault(entity.entity(), []).append(
                    f"{entity.get_name()}={pos}"
                )
        return grouped

    def _log_object_positions(self, run: int, tick_label: str = "tick 0") -> None:
        """Log object positions for the provided run/tick context."""
        grouped = self._collect_object_positions()
        if not grouped:
            logger.info("Run %d %s: no arena objects configured", run, tick_label)
            return
        counts = {key: len(vals) for key, vals in grouped.items()}
        logger.info("Run %d %s object positions summary: %s", run, tick_label, counts)
        for entity_type, entries in grouped.items():
            logger.info(
                "Run %d %s %s positions: %s",
                run,
                tick_label,
                entity_type,
                "; ".join(entries),
            )

    def _compute_entity_radii(self):
        """Compute entity radii."""
        radii = {}
        max_radius = 0.0
        for (_, entities) in self.objects.values():
            for entity in entities:
                entity.to_origin()
                shape = entity.get_shape()
                radius = self._estimate_shape_radius(shape)
                radii[id(entity)] = radius
                max_radius = max(max_radius, radius)
        return radii, max_radius if max_radius > 0 else 0.1

    def _estimate_shape_radius(self, shape):
        """Estimate the shape radius."""
        radius_getter = getattr(shape, "get_radius", None)
        if callable(radius_getter):
            try:
                r = float(radius_getter())
                if r > 0:
                    return r
            except Exception:
                pass
        if shape.vertices_list:
            center = shape.center_of_mass()
            return max((Vector3D(v.x - center.x, v.y - center.y, v.z - center.z).magnitude() for v in shape.vertices_list), default=0.05)
        return 0.05

    def _place_entity_random(self, entity, radius, occupancy, rng, min_v, max_v):
        """Place entity random."""
        attempts = 0
        shape_n = entity.get_shape()
        min_vert_z = abs(shape_n.min_vert().z)
        effective_radius = radius * PLACEMENT_MARGIN_FACTOR + PLACEMENT_MARGIN_EPS
        min_x = min_v.x + effective_radius
        max_x = max_v.x - effective_radius
        min_y = min_v.y + effective_radius
        max_y = max_v.y - effective_radius
        if min_x >= max_x or min_y >= max_y:
            return False
        while attempts < PLACEMENT_MAX_ATTEMPTS:
            rand_pos = Vector3D(
                Random.uniform(rng, min_x, max_x),
                Random.uniform(rng, min_y, max_y),
                min_vert_z
            )
            entity.to_origin()
            entity.set_position(rand_pos)
            shape = entity.get_shape()
            if shape.check_overlap(self.shape)[0]:
                attempts += 1
                continue
            if self._shape_overlaps_grid(shape, rand_pos, radius, occupancy):
                attempts += 1
                continue
            entity.set_start_position(rand_pos)
            self._register_shape_in_grid(shape, rand_pos, radius, occupancy)
            return True
        return False

    def _shape_overlaps_grid(self, shape, position, radius, occupancy):
        """Shape overlaps grid."""
        if not occupancy:
            return False
        cells = self._cells_for_shape(position, radius, pad=1)
        checked = set()
        for cell in cells:
            if cell in checked:
                continue
            checked.add(cell)
            for other_shape, other_radius in occupancy.get(cell, []):
                center_delta = Vector3D(
                    shape.center.x - other_shape.center.x,
                    shape.center.y - other_shape.center.y,
                    0
                )
                if center_delta.magnitude() >= (radius + other_radius):
                    continue
                if shape.check_overlap(other_shape)[0]:
                    return True
        return False

    def _register_shape_in_grid(self, shape, position, radius, occupancy):
        """Register shape in grid."""
        cells = self._cells_for_shape(position, radius)
        for cell in cells:
            occupancy.setdefault(cell, []).append((shape, radius))

    def _cells_for_shape(self, position, radius, pad: int = 0):
        """Cells for shape."""
        if self._grid_cell_size is None or self._grid_cell_size <= 0:
            return [(0, 0)]
        origin = self._grid_origin or Vector3D()
        cell_size = self._grid_cell_size
        min_x = int(math.floor((position.x - radius - origin.x) / cell_size)) - pad
        max_x = int(math.floor((position.x + radius - origin.x) / cell_size)) + pad
        min_y = int(math.floor((position.y - radius - origin.y) / cell_size)) - pad
        max_y = int(math.floor((position.y + radius - origin.y) / cell_size)) + pad
        cells = []
        for cx in range(min_x, max_x + 1):
            for cy in range(min_y, max_y + 1):
                cells.append((cx, cy))
        return cells
    
    def pack_detector_data(self) -> dict:
        """Pack detector data."""
        out = {}
        for _,entities in self.objects.values():
            shapes = []
            positions = []
            for n in range(len(entities)):
                shapes.append(entities[n].get_shape())
                positions.append(entities[n].get_position())
            out.update({entities[0].entity():(shapes,positions)})
        return out
    
    def _apply_gui_backpressure(self, gui_in_queue: mp.Queue):
        """Pause the simulation loop when the GUI cannot keep up with rendering."""
        if not self._gui_backpressure_enabled or gui_in_queue is None:
            return
        threshold = self._gui_backpressure_threshold
        if threshold <= 0:
            return
        try:
            backlog = gui_in_queue.qsize()
        except (NotImplementedError, AttributeError, OSError):
            return
        if backlog < threshold:
            self._gui_backpressure_active = False
            return
        if not self._gui_backpressure_active:
            logger.warning("GUI rendering is %s frames behind; slowing down ticks", backlog)
            self._gui_backpressure_active = True
        while True:
            try:
                backlog = gui_in_queue.qsize()
            except (NotImplementedError, AttributeError, OSError):
                break
            if backlog < threshold:
                break
            time.sleep(self._gui_backpressure_interval)
        self._gui_backpressure_active = False
        
    def run(self,num_runs,time_limit, arena_queue: Any, agents_queue: Any, gui_in_queue: Any,dec_arena_in: Any, gui_control_queue: Any,render:bool=False, log_context: dict | None = None, dec_control_queue: Any = None):
        """Function to run the arena in a separate process (supports multiple agent queues)."""
        arena_queues = arena_queue if isinstance(arena_queue, list) else [arena_queue]
        agents_queues = agents_queue if isinstance(agents_queue, list) else [agents_queue]
        n_managers = len(agents_queues)

        def _combine_agent_snapshots(snapshots, cached_shapes, cached_spins, cached_metadata):
            """
            Merge per-manager snapshots; when the same group key appears in multiple
            managers (e.g., split of the same agent type), combine them for the
            current tick. Shapes/spins are rebuilt every merge to avoid
            duplicating entries across ticks; metadata is preserved from cache
            unless a snapshot provides an update.
            """
            shapes: dict = {}
            spins: dict = {}
            metadata = {k: list(v) for k, v in cached_metadata.items()}
            for snap in snapshots:
                if not snap:
                    continue
                for grp, vals in snap.get("agents_shapes", {}).items():
                    shapes.setdefault(grp, []).extend(vals)
                for grp, vals in snap.get("agents_spins", {}).items():
                    spins.setdefault(grp, []).extend(vals)
                for grp, vals in snap.get("agents_metadata", {}).items():
                    metadata.setdefault(grp, []).extend(vals)
            # If no metadata arrived in this batch, keep cached metadata.
            return shapes, spins, metadata

        ticks_limit = time_limit*self.ticks_per_second + 1 if time_limit > 0 else 0
        tick_interval = 1.0 / max(1, self.ticks_per_second)
        run = 1
        log_context = log_context or {}
        log_specs = log_context.get("log_specs")
        process_name = log_context.get("process_name", "arena")
        while run < num_runs + 1:
            start_run_logging(log_specs, process_name, run)
            try:
                logger.info(f"Run number {run} started")
                self._log_object_positions(run, "tick 0")
                initial_objects = self.pack_objects_data()
                arena_data = {
                    "status": [0, self.ticks_per_second],
                    "objects": initial_objects
                }
                detector_payload = {"objects": initial_objects, "run": run}
                if dec_arena_in is not None:
                    try:
                        while dec_arena_in.poll(0.0):
                            dec_arena_in.get()
                    except Exception:
                        pass
                    dec_arena_in.put(detector_payload)
                if dec_control_queue is not None:
                    try:
                        dec_control_queue.put({"kind": "run_start", "run": run})
                    except Exception:
                        pass
                if render:
                    gui_in_queue.put({**arena_data, "agents_shapes": self.agents_shapes, "agents_spins": self.agents_spins, "agents_metadata": self.agents_metadata})
                    self._apply_gui_backpressure(gui_in_queue)
                for q in arena_queues:
                    q.put({**arena_data, "random_seed": self.random_seed})

                latest_agent_data = [None] * n_managers
                for idx, q in enumerate(agents_queues):
                    latest_agent_data[idx] = self._maybe_get(q, timeout=1.0)
                if any(d is None for d in latest_agent_data):
                    break
                self.agents_shapes, self.agents_spins, self.agents_metadata = _combine_agent_snapshots(
                    latest_agent_data,
                    self.agents_shapes,
                    self.agents_spins,
                    self.agents_metadata
                )
                initial_tick_rate = latest_agent_data[0].get("status", [0, self.ticks_per_second])[1]
                if self.data_handling is not None:
                    self.data_handling.new_run(
                        run,
                        self.agents_shapes,
                        self.agents_spins,
                        self.agents_metadata,
                        initial_tick_rate
                    )
                t = 1
                running = False if render else True
                step_mode = False
                reset = False
                last_snapshot_info = None
                while True:
                    if ticks_limit > 0 and t >= ticks_limit: break
                    if render:
                        cmd = self._maybe_get(gui_control_queue, timeout=0.0)
                        while cmd is not None:
                            if cmd == "start":
                                running = True
                            elif cmd == "stop":
                                running = False
                            elif cmd == "step":
                                running = False
                                step_mode = True
                            elif cmd == "reset":
                                running = False
                                reset = True
                            elif isinstance(cmd, (list, tuple)) and len(cmd) == 2 and cmd[0] == "speed":
                                try:
                                    self._speed_multiplier = max(1.0, float(cmd[1]))
                                except Exception:
                                    self._speed_multiplier = 1.0
                            cmd = self._maybe_get(gui_control_queue, timeout=0.0)
                    arena_data = {
                        "status": [t,self.ticks_per_second],
                        "objects": self.pack_objects_data()
                    }
                    if running or step_mode:
                        if not render and not getattr(self, "quiet", False):
                            print(f"\rrun {run} arena_ticks {t}", end='', flush=True)
                        for q in arena_queues:
                            q.put(arena_data)
                        ready = [False] * n_managers
                        while not all(ready):
                            for idx, q in enumerate(agents_queues):
                                candidate = self._maybe_get(q, timeout=0.01)
                                if candidate is not None:
                                    latest_agent_data[idx] = candidate
                            for idx, snap in enumerate(latest_agent_data):
                                ready[idx] = bool(snap and snap["status"][0]/snap["status"][1] >= t/self.ticks_per_second)
                            detector_data = {
                                "objects": self.pack_detector_data(),
                                "run": run
                            }
                            if all(q.qsize()==0 for q in arena_queues):
                                for q in arena_queues:
                                    q.put(arena_data)
                                if dec_arena_in is not None:
                                    dec_arena_in.put(detector_data)
                            time.sleep(0.0001)

                        for idx, q in enumerate(agents_queues):
                            latest = self._maybe_get(q, timeout=0.0)
                            if latest is not None:
                                latest_agent_data[idx] = latest
                        self.agents_shapes, self.agents_spins, self.agents_metadata = _combine_agent_snapshots(
                            latest_agent_data,
                            self.agents_shapes,
                            self.agents_spins,
                            self.agents_metadata
                        )
                        if self.data_handling is not None:
                            tick_stamp = arena_data.get("status", [t, self.ticks_per_second])[0]
                            tick_rate = arena_data.get("status", [tick_stamp, self.ticks_per_second])[1]
                            self.data_handling.save(
                                self.agents_shapes,
                                self.agents_spins,
                                self.agents_metadata,
                                tick_stamp,
                                tick_rate
                            )
                            last_snapshot_info = (tick_stamp, tick_rate)
                        if render:
                            gui_in_queue.put({**arena_data, "agents_shapes": self.agents_shapes, "agents_spins": self.agents_spins, "agents_metadata": self.agents_metadata})
                            self._apply_gui_backpressure(gui_in_queue)
                        if self._speed_multiplier > 1.0:
                            time.sleep(tick_interval * (self._speed_multiplier - 1.0))
                        step_mode = False
                        t += 1
                    elif reset:
                        break
                    else: time.sleep(0.0005)
                if self.data_handling is not None and last_snapshot_info:
                    self.data_handling.save(
                        self.agents_shapes,
                        self.agents_spins,
                        self.agents_metadata,
                        last_snapshot_info[0],
                        last_snapshot_info[1],
                        force=True
                    )
                if t < ticks_limit and not reset: break
                if run < num_runs:
                    if not reset:
                        run += 1
                        self.increment_seed()
                    else:
                        self.randomize_seed()
                    self.reset()
                    if reset:
                        arena_data = {
                                    "status": "reset",
                                    "objects": self.pack_objects_data()
                        }
                        for q in arena_queues:
                            q.put(arena_data)
                    if not render: print("")
                elif not reset:
                    run += 1
                    self.close()
                    if not render: print("")
                else:
                    self.randomize_seed()
                    self.reset()
                    arena_data = {
                                "status": "reset",
                                "objects": self.pack_objects_data()
                    }
                    for q in arena_queues:
                        q.put(arena_data)


            finally:
                shutdown_logging()
    def reset(self):
        """Reset the component state."""
        super().reset()
        min_v = self.shape.min_vert()
        max_v = self.shape.max_vert()
        rng = self.random_generator
        if self.data_handling is not None: self.data_handling.close(self.agents_shapes)
        for (config, entities) in self.objects.values():
            n_entities = len(entities)
            for entity in entities:
                entity.set_position(Vector3D(999, 0, 0), False)
            for n in range(n_entities):
                entity = entities[n]
                entity.set_start_orientation(entity.get_start_orientation())
                if not entity.get_orientation_from_dict():
                    rand_angle = Random.uniform(rng, 0.0, 360.0)
                    entity.set_start_orientation(Vector3D(0, 0, rand_angle))
                position = entity.get_start_position()
                if not entity.get_position_from_dict():
                    count = 0
                    done = False
                    shape_n = entity.get_shape()
                    shape_type_n = entity.get_shape_type()
                    while not done and count < 500:
                        done = True
                        rand_pos = Vector3D(
                            Random.uniform(rng, min_v.x, max_v.x),
                            Random.uniform(rng, min_v.y, max_v.y),
                            position.z
                        )
                        entity.to_origin()
                        entity.set_position(rand_pos)
                        shape_n = entity.get_shape()
                        if shape_n.check_overlap(self.shape)[0]:
                            done = False
                        if done:
                            for m in range(n_entities):
                                if m == n:
                                    continue
                                other_entity = entities[m]
                                other_shape = other_entity.get_shape()
                                other_shape_type = other_entity.get_shape_type()
                                if shape_type_n == other_shape_type and shape_n.check_overlap(other_shape)[0]:
                                    done = False
                                    break
                        count += 1
                        if done:
                            entity.set_start_position(rand_pos)
                    if not done:
                        raise Exception(f"Impossible to place object {entity.entity()} in the arena")
                else:
                    entity.to_origin()
                    entity.set_start_position(Vector3D(position.x, position.y, position.z + abs(entity.get_shape().min_vert().z)))

    def close(self):
        """Close the component resources."""
        super().close()

    def _update_hierarchy_from_shape(self):
        """Update hierarchy from shape."""
        bounds = None
        if hasattr(self, "shape") and self.shape is not None:
            min_v = self.shape.min_vert()
            max_v = self.shape.max_vert()
            bounds = Bounds2D(min_v.x, min_v.y, max_v.x, max_v.y)
        self._hierarchy = self._create_hierarchy(bounds)
        if hasattr(self, "shape") and self.shape is not None and hasattr(self.shape, "metadata"):
            self.shape.metadata["hierarchy"] = self._hierarchy
            if self._hierarchy:
                self.shape.metadata["hierarchy_colors"] = getattr(self._hierarchy, "level_colors", {})
                self.shape.metadata["hierarchy_node_numbers"] = {
                    node_id: node.order for node_id, node in self._hierarchy.nodes.items()
                }

class UnboundedArena(SolidArena):
    
    """Unbounded arena rendered as a large square without wrap-around."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        dims = config_elem.arena.get("dimensions", {})
        raw = dims.get("diameter", None)
        try:
            self.diameter = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            self.diameter = None
        if not self.diameter or self.diameter <= 0:
            self.diameter = self._estimate_initial_diameter(config_elem)
        if self.diameter <= 0:
            raise ValueError("UnboundedArena could not derive a positive initial diameter")
        super().__init__(config_elem)
        logger.info(
            "Unbounded arena created (diameter=%.3f, square side=%.3f)",
            self.diameter,
            self.diameter
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
            num = cfg.get("number", 0)
            if isinstance(num, (list, tuple)) and num:
                try:
                    num = int(num[0])
                except Exception:
                    num = 0
            try:
                num_int = int(num)
            except Exception:
                num_int = 0
            total += max(num_int, 0)
            try:
                diam = float(cfg.get("diameter", max_diam))
                if diam > max_diam:
                    max_diam = diam
            except Exception:
                pass
        if total <= 0:
            return 2.0
        agent_radius = max_diam * 0.5
        # Spread agents on a disk with comfortable spacing; convert to square side.
        import math
        disk_radius = max(agent_radius * 4.0, agent_radius * math.sqrt(total) * 2.5, 0.5)
        return max(disk_radius * 2.0, 1.0)

    def _arena_shape_type(self):
        """Use a special unbounded footprint."""
        return "unbounded"

    def _arena_shape_config(self, config_elem:Config):
        """Adapt the configuration parameters for the unbounded factory."""
        return {
            "color": config_elem.arena.get("color", "gray"),
            "side": self.diameter
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
            "initial_half": half
        }

class CircularArena(SolidArena):
    
    """Circular arena."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        dims = config_elem.arena.get("dimensions", {})
        self.height = dims.get("height", 1)
        self.radius = dims.get("radius", 1)
        self.color = config_elem.arena.get("color", "white")
        logger.info("Circular arena created successfully")
    

class RectangularArena(SolidArena):
    
    """Rectangular arena."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        dims = config_elem.arena.get("dimensions", {})
        self.height = dims.get("height", 1)
        self.width = dims.get("width", 1)
        self.depth = dims.get("depth", 1)
        self.length = self.width
        self.color = config_elem.arena.get("color", "white")
        logger.info("Rectangular arena created successfully")
    
class SquareArena(SolidArena):
    
    """Square arena."""
    def __init__(self, config_elem:Config):
        """Initialize the instance."""
        super().__init__(config_elem)
        dims = config_elem.arena.get("dimensions", {})
        self.height = dims.get("height", 1)
        self.side = dims.get("side", 1)
        self.color = config_elem.arena.get("color", "white")
        logger.info("Square arena created successfully")
    
