# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Environment: process-level orchestration of the simulation."""
import psutil, time, gc
import multiprocessing as mp
from pathlib import Path
from multiprocessing.context import BaseContext
from typing import Any, Dict
from config import Config
from entity import EntityFactory
from arena import ArenaFactory
from gui import GuiFactory
from collision_detector import CollisionDetector
from logging_utils import get_logger, shutdown_logging
logger = get_logger("environment")

used_cores = set()

# ---------------------------
# Logging wrappers for processes
# ---------------------------

def _run_arena_process(arena, num_runs, time_limit,
                       arena_queue_list, agents_queue_list,
                       gui_in_queue, dec_arena_in,
                       gui_control_queue, render_enabled,
                       log_specs):
    from logging_utils import configure_logging
    settings, cfg_path, root = log_specs
    configure_logging(settings, cfg_path, root)
    arena.run(
        num_runs, time_limit,
        arena_queue_list, agents_queue_list,
        gui_in_queue, dec_arena_in,
        gui_control_queue, render_enabled
    )

def _run_manager_process(block_filtered, arena_shape, log_specs,
                         wrap_config, hierarchy, snapshot_stride, manager_id,
                         collisions, message_tx, message_rx,
                         num_runs, time_limit,
                         arena_queue, agents_queue,
                         dec_agents_in, dec_agents_out,
                         agent_barrier):
    from logging_utils import configure_logging
    settings, cfg_path, root = log_specs
    configure_logging(settings, cfg_path, root)

    from entityManager import EntityManager
    mgr = EntityManager(
        block_filtered, arena_shape,
        wrap_config=wrap_config,
        hierarchy=hierarchy,
        snapshot_stride=snapshot_stride,
        manager_id=manager_id,
        collisions=collisions,
        message_tx=message_tx,
        message_rx=message_rx
    )
    mgr.run(
        num_runs, time_limit,
        arena_queue, agents_queue,
        dec_agents_in, dec_agents_out,
        agent_barrier
    )

def _run_detector_process(collision_detector, det_in_arg, det_out_arg, dec_arena_in, log_specs):
    from logging_utils import configure_logging
    settings, cfg_path, root = log_specs
    configure_logging(settings, cfg_path, root)
    collision_detector.run(det_in_arg, det_out_arg, dec_arena_in)

def _run_message_server(channels, log_specs, fully_connected):
    from logging_utils import configure_logging
    settings, cfg_path, root = log_specs
    configure_logging(settings, cfg_path, root)
    from message_server import run_message_server
    run_message_server(channels, fully_connected)

def _run_gui_process(config, arena_vertices, arena_color,
                     gui_in_queue, gui_control_queue,
                     log_specs, wrap_config, hierarchy_overlay):
    from logging_utils import configure_logging
    settings, cfg_path, root = log_specs
    configure_logging(settings, cfg_path, root)
    from gui import GuiFactory
    app, gui = GuiFactory.create_gui(
        config, arena_vertices, arena_color,
        gui_in_queue, gui_control_queue,
        wrap_config=wrap_config,
        hierarchy_overlay=hierarchy_overlay
    )
    gui.show()
    app.exec()


def pick_least_used_free_cores(num):
    """
    Selects 'num' cores that are not in used_cores, picking the ones with lower CPU usage.
    """
    global used_cores

    # Sample the current CPU usage (percentage) for all cores
    usage = psutil.cpu_percent(interval=0.1, percpu=True)

    # Ordina i core dal meno usato
    ordered = sorted(range(len(usage)), key=lambda c: usage[c])

    # Filtra quelli non ancora assegnati
    free = [c for c in ordered if c not in used_cores]

    return free[:num]


def set_affinity_safely(proc, num_cores):
    """
    Assigns less used cores wo repetition
    """
    global used_cores
    try:
        selected = pick_least_used_free_cores(num_cores)
        if not selected:
            logger.warning("[WARNING] No free cores: fallback to all cores")
            fallback_count = psutil.cpu_count(logical=True) or 1
            selected = list(range(fallback_count))
        p = psutil.Process(proc.pid)
        p.cpu_affinity(selected)
        used_cores.update(selected)
        # print(f"[AFFINITY] PID {proc.pid} -> {selected}")
    except Exception as e:
        logger.error(f"[AFFINITY ERROR] PID {proc.pid}: {e}")


def set_shared_affinity(processes, num_cores):
    """
    Assigns a shared set of cores to multiple processes, avoiding overlapping with already used cores.
    """
    global used_cores
    try:
        selected = pick_least_used_free_cores(num_cores)
        if not selected:
            # If no free cores, fall back to all cores (system may handle distribution)
            fallback_count = psutil.cpu_count(logical=True) or 1
            selected = list(range(fallback_count))

        for proc in processes:
            if proc is None:
                continue
            p = psutil.Process(proc.pid)
            p.cpu_affinity(selected)

        used_cores.update(selected)
        # print(f"[AFFINITY] Shared -> {selected}")
    except Exception as e:
        logger.error(f"[AFFINITY ERROR] shared for {[p.pid for p in processes if p]}: {e}")


class _PipeQueue:
    """Single-producer/single-consumer queue backed by Pipe with poll()."""

    def __init__(self, ctx: BaseContext):
        self._recv, self._send = ctx.Pipe(duplex=False)

    def put(self, item):
        self._send.send(item)

    def get(self):
        return self._recv.recv()

    def poll(self, timeout: float = 0.0):
        return self._recv.poll(timeout)

    def qsize(self):
        return 1 if self._recv.poll(0) else 0

    def empty(self):
        return not self._recv.poll(0)


class EnvironmentFactory:
    """Environment factory."""

    @staticmethod
    def create_environment(config_elem: Config, config_path):
        """Create environment."""
        if config_elem.environment:
            return Environment(config_elem,config_path)
        else:
            raise ValueError(
                f"Invalid environment configuration: "
                f"{config_elem.environment['parallel_experiments']} "
                f"{config_elem.environment['render']}"
            )


class Environment:
    """Environment."""

    def __init__(self, config_elem: Config,config_path:Path):
        """Initialize the instance."""
        self.experiments = tuple(config_elem.parse_experiments())
        self.num_runs = int(config_elem.environment.get("num_runs", 1))
        self.time_limit = int(config_elem.environment.get("time_limit", 0))
        gui_id = config_elem.gui.get("_id", "2D")
        self.gui_id = gui_id
        self.quiet = bool(config_elem.environment.get("quiet", False))
        default_stride = 5 if config_elem.environment.get("collisions", False) else 1
        self.snapshot_stride = max(1, int(config_elem.environment.get("snapshot_stride", default_stride)))
        # Automatic agent process estimation target (agents per process).
        self.auto_agents_per_proc_target = max(
            1, int(config_elem.environment.get("auto_agents_per_proc_target", 5))
        )
        base_gui_cfg = dict(config_elem.gui) if len(config_elem.gui) > 0 else {}
        if gui_id in ("none", "off", None) or not base_gui_cfg:
            self.render = [False, {}]
        else:
            self.render = [True, base_gui_cfg]
        self.collisions = config_elem.environment.get("collisions", False)
        if not self.render[0] and self.time_limit == 0:
            raise Exception("Invalid configuration: infinite experiment with no GUI.")
        self._log_set = config_elem.environment.get("logging")
        self._log_path = config_path.expanduser().resolve()
        self._log_root = Path(__file__).resolve().parents[1]
        self.log_specs = (self._log_set,self._log_path,self._log_root)
        logger.info("Environment created successfully")

    def arena_init(self, exp: Config,specs):
        """Arena init."""
        arena = ArenaFactory.create_arena(exp)
        if self.num_runs > 1 and arena.get_seed() < 0:
            arena.reset_seed()
        arena.initialize()
        return arena

    def agents_init(self, exp: Config,specs):
        """Agents init."""
        agents_cfg = exp.environment.get("agents") or {}
        if not isinstance(agents_cfg, dict):
            raise ValueError("Invalid agents configuration: expected a dictionary.")
        agents: Dict[str, tuple[Dict[str, Any], list]] = {
            agent_type: (cfg, []) for agent_type, cfg in agents_cfg.items()
        }

        for agent_type, (config, entities) in agents.items():
            if not isinstance(config, dict):
                raise ValueError(f"Invalid agent configuration for {agent_type}")
            number_raw = config.get("number", 0)
            try:
                number = int(number_raw)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid number of agents for {agent_type}: {number_raw}")
            if number <= 0:
                raise ValueError(f"Agent group {agent_type} must have a positive 'number' of agents")
            for n in range(number):
                entities.append(
                    EntityFactory.create_entity(
                        entity_type="agent_" + agent_type,
                        config_elem=config,
                        _id=n
                    )
                )
        totals = {name: len(ents) for name, (_, ents) in agents.items()}
        logger.info("Agents initialized: total=%s groups=%s", sum(totals.values()), totals)
        return agents

    def _split_agents(
        self,
        agents: Dict[str, tuple[Dict[str, Any], list]],
        num_blocks: int,
    ) -> list[Dict[str, tuple[Dict[str, Any], list]]]:
        """Split agents into nearly even blocks."""
        if num_blocks <= 1:
            return [agents]

        # Flatten agents into a list of (type, config, entity)
        flat = []
        for agent_type, (cfg, entities) in agents.items():
            for entity in entities:
                flat.append((agent_type, cfg, entity))

        total = len(flat)
        num_blocks = max(1, min(num_blocks, total))
        blocks: list[Dict[str, tuple[Dict[str, Any], list]]] = [dict() for _ in range(num_blocks)]

        # Distribute entities round-robin among blocks
        for idx, (agent_type, cfg, entity) in enumerate(flat):
            target = idx % num_blocks
            if agent_type not in blocks[target]:
                blocks[target][agent_type] = (cfg, [])
            blocks[target][agent_type][1].append(entity)

        # Remove empty blocks from final list
        blocks = [b for b in blocks if any(len(v[1]) for v in b.values())]
        return blocks

    @staticmethod
    def _count_agents(
        agents: Dict[str, tuple[Dict[str, Any], list]]
    ) -> int:
        """Count total agents."""
        total = 0
        for _, (_, entities) in agents.items():
            total += len(entities)
        return total

    def _estimate_agents_per_process(
        self,
        agents: Dict[str, tuple[Dict[str, Any], list]],
    ) -> int:
        """
        Derive the desired number of agents per process based on workload.

        Heavy behavior -> fewer agents per process.
        Lighter behavior -> more agents per process.
        """
        has_spin = False
        has_messages = False
        has_fast_detection = False

        for cfg, entities in agents.values():
            behavior = str(cfg.get("moving_behavior", "") or "").lower()
            if behavior == "spin_model":
                has_spin = True

            if cfg.get("messages"):
                has_messages = True

            det_cfg = cfg.get("detection", {}) or {}
            try:
                acq_rate = float(det_cfg.get("acquisition_per_second", det_cfg.get("rx_per_second", 1)))
                if acq_rate > 1:
                    has_fast_detection = True
            except Exception:
                pass

        # Heuristic:
        if has_spin:
            return 6
        if has_messages or has_fast_detection:
            return 10
        return 20

    def _compute_agent_processes(
        self,
        agents: Dict[str, tuple[Dict[str, Any], list]],
    ) -> int:
        """
        Compute number of agent manager processes with internal heuristics.
        """
        available_cores = psutil.cpu_count(logical=True) or 1
        total_agents = self._count_agents(agents)
        if total_agents <= 0:
            return 1
        target = self._estimate_agents_per_process(agents)
        target = max(5, min(30, target))

        import math
        n_procs = math.ceil(total_agents / target)

        reserved = 3 + (1 if self.render and self.render[0] else 0)
        max_for_agents = max(1, available_cores - reserved)
        return max(1, min(8, n_procs, max_for_agents))

    def run_gui(
        self,
        config: dict,
        arena_vertices: list,
        arena_color: str,
        gui_in_queue,
        gui_control_queue,
        wrap_config=None,
        hierarchy_overlay=None
    ):
        """Run the gui."""
        app, gui = GuiFactory.create_gui(
            config,
            arena_vertices,
            arena_color,
            gui_in_queue,
            gui_control_queue,
            wrap_config=wrap_config,
            hierarchy_overlay=hierarchy_overlay
        )
        gui.show()
        app.exec()

    def start(self):
        """Start the process."""
        ctx = mp.get_context("fork")
        # Reset affinity bookkeeping for each run to match the current machine state.
        used_cores.clear()
        total_cores = psutil.cpu_count(logical=True) or 1
        # Reserve a dedicated core for the environment/main process so workers use different ones.
        try:
            env_core = pick_least_used_free_cores(1)
            if env_core:
                psutil.Process().cpu_affinity(env_core)
                used_cores.update(env_core)
        except Exception as e:
            logger.warning("Could not set environment CPU affinity: %s", e)

        for exp in self.experiments:

            def _safe_terminate(proc):
                if proc and proc.is_alive():
                    proc.terminate()

            def _safe_join(proc, timeout=None):
                if proc and proc.pid is not None:
                    proc.join(timeout=timeout)

            dec_arena_in = _PipeQueue(ctx)
            gui_in_queue = _PipeQueue(ctx)
            gui_control_queue = _PipeQueue(ctx)
            arena = self.arena_init(exp,self.log_specs)
            try:
                arena.quiet = self.quiet
            except Exception:
                pass
            agents = self.agents_init(exp,self.log_specs)
            render_enabled = self.render[0]
            n_agent_procs = self._compute_agent_processes(agents)
            logger.info(
                "Agent process auto-split: total_...=%d -> processes=%d",
                self._count_agents(agents),
                n_agent_procs
            )
            agent_blocks = self._split_agents(agents, n_agent_procs)
            n_blocks = len(agent_blocks)
            agent_barrier = None
            if n_blocks > 1:
                agent_barrier = ctx.Barrier(n_blocks)
            # Detector input/output queues
            dec_agents_in_list = [_PipeQueue(ctx) for _ in range(n_blocks)] if self.collisions else [None] * n_blocks
            dec_agents_out_list = [_PipeQueue(ctx) for _ in range(n_blocks)] if self.collisions else [None] * n_blocks
            # Per-manager arena/agents queues
            arena_queue_list = [_PipeQueue(ctx) for _ in range(n_blocks)]
            agents_queue_list = [_PipeQueue(ctx) for _ in range(n_blocks)]
            arena_shape = arena.get_shape()
            if arena_shape is None:
                raise ValueError("Arena shape was not initialized; cannot start environment.")
            arena_id = arena.get_id()
            wrap_config = arena.get_wrap_config()
            arena_hierarchy = arena.get_hierarchy()
            collision_detector = CollisionDetector(arena_shape, self.collisions, wrap_config=wrap_config)
            arena_process = mp.Process(
            target=_run_arena_process,
            args=(
                arena,
                self.num_runs,
                self.time_limit,
                arena_queue_list,
                agents_queue_list,
                gui_in_queue,
                dec_arena_in,
                gui_control_queue,
                render_enabled,
                self.log_specs
            )
        )
            # Managers
            manager_processes = []

            message_channels = []
            for _ in range(n_blocks):
                message_tx = ctx.Queue()
                message_rx = ctx.Queue()
                message_channels.append((message_tx, message_rx))

            for idx_block, block in enumerate(agent_blocks):
                block_filtered = {k: v for k, v in block.items() if len(v[1]) > 0}
                proc = mp.Process(
                    target=_run_manager_process,
                    args=(
                        block_filtered,
                        arena_shape,
                        self.log_specs,
                        wrap_config,
                        arena_hierarchy,
                        self.snapshot_stride,
                        idx_block,
                        self.collisions,
                        message_channels[idx_block][0],
                        message_channels[idx_block][1],
                        self.num_runs,
                        self.time_limit,
                        arena_queue_list[idx_block],
                        agents_queue_list[idx_block],
                        dec_agents_in_list[idx_block],
                        dec_agents_out_list[idx_block],
                        agent_barrier,
                    )
                )

                manager_processes.append(proc)
            # Message server process (one per environment).
            fully_connected = True #arena_id in ("abstract", "none", None)
            message_server_process = mp.Process(
                target=_run_message_server,
                args=(message_channels, self.log_specs, fully_connected),
            )

            # Prepare detector input/output arguments.
            # If collisions are disabled → the detector should not receive any queue.
            if not self.collisions:
                det_in_arg = None
                det_out_arg = None
            else:
                # Collisions active:
                # - If multiple managers → pass list of queues (one per manager)
                # - If single manager  → pass the single queue directly
                det_in_arg = dec_agents_in_list if n_blocks > 1 else dec_agents_in_list[0]
                det_out_arg = dec_agents_out_list if n_blocks > 1 else dec_agents_out_list[0]

            detector_process = mp.Process(
                target=_run_detector_process,
                args=(collision_detector, det_in_arg, det_out_arg, dec_arena_in, self.log_specs)
            )

            pattern = {
                "arena": 2,
                "agents": 3,
                "detector": 3,
                "gui": 2,
                "messages": 2,
            }
            killed = 0
            if render_enabled:
                render_config = dict(self.render[1])
                render_config["_id"] = "abstract" if arena_id in (None, "none") else self.gui_id
                hierarchy_overlay = arena_hierarchy.to_rectangles() if arena_hierarchy else None
                gui_process = mp.Process(
                    target=_run_gui_process,
                    args=(
                        render_config,
                        arena_shape.vertices(),
                        arena_shape.color(),
                        gui_in_queue,
                        gui_control_queue,
                        self.log_specs,
                        wrap_config,
                        hierarchy_overlay
                    )
                )
                gui_process.start()
                message_server_process.start()
                if detector_process and arena_id not in ("abstract", "none", None):
                    detector_process.start()
                for proc in manager_processes:
                    proc.start()
                arena_process.start()

                set_affinity_safely(arena_process, pattern["arena"])
                # Agent processes share a capped core set (2 cores per proc)...
                available_remaining = max(1, total_cores - len(used_cores))
                agent_core_budget = min(n_blocks * 2, available_remaining)
                agent_core_budget = max(agent_core_budget, 1)
                set_shared_affinity(manager_processes, agent_core_budget)
                if detector_process:
                    set_affinity_safely(detector_process, pattern["detector"])
                set_affinity_safely(gui_process, pattern["gui"])
                set_affinity_safely(message_server_process, pattern["messages"])

                # Supervision loop
                while True:
                    exit_failure = next(
                        (p for p in [arena_process] + [message_server_process] + manager_processes + [detector_process] if p.exitcode not in (None, 0)),
                        None
                    )
                    arena_alive = arena_process.is_alive()
                    gui_alive = gui_process.is_alive()
                    if exit_failure:
                        killed = 1
                        _safe_terminate(arena_process)
                        for proc in manager_processes:
                            _safe_terminate(proc)
                        _safe_terminate(detector_process)
                        _safe_terminate(gui_process)
                        _safe_terminate(message_server_process)
                        break
                    if not arena_alive or not gui_alive:
                        if arena_alive:
                            _safe_terminate(arena_process)
                        for proc in manager_processes:
                            _safe_terminate(proc)
                        _safe_terminate(detector_process)
                        _safe_terminate(gui_process)
                        _safe_terminate(message_server_process)
                        break
                    time.sleep(0.5)
                # Join all processes
                _safe_join(arena_process)
                for proc in manager_processes:
                    _safe_join(proc)
                _safe_join(detector_process)
                _safe_join(gui_process)
                _safe_join(message_server_process)
            else:
                message_server_process.start()
                if detector_process and arena_id not in ("abstract", "none", None):
                    detector_process.start()
                for proc in manager_processes:
                    proc.start()
                arena_process.start()
                set_affinity_safely(arena_process,   pattern["arena"])
                available_remaining = max(1, total_cores - len(used_cores))
                agent_core_budget = min(n_blocks * 2, available_remaining)
                agent_core_budget = max(agent_core_budget, 1)
                set_shared_affinity(manager_processes, agent_core_budget)
                if detector_process:
                    set_affinity_safely(detector_process, pattern["detector"])
                set_affinity_safely(message_server_process, pattern["messages"])
                killed = 0
                # Supervision loop
                while True:
                    exit_failure = next(
                        (p for p in [arena_process] + [message_server_process] + manager_processes + [detector_process] if p.exitcode not in (None, 0)),
                        None
                    )
                    arena_alive = arena_process.is_alive()
                    if exit_failure:
                        killed = 1
                        _safe_terminate(arena_process)
                        for proc in manager_processes:
                            _safe_terminate(proc)
                        _safe_terminate(detector_process)
                        _safe_terminate(message_server_process)
                        break
                    if not arena_alive:
                        for proc in manager_processes:
                            _safe_terminate(proc)
                        _safe_terminate(detector_process)
                        _safe_terminate(message_server_process)
                        break
                    time.sleep(0.5)
                # Join all processes
                _safe_join(arena_process)
                for proc in manager_processes:
                    _safe_join(proc)
                _safe_join(detector_process)
                _safe_join(message_server_process)
                if killed == 1:
                    raise RuntimeError("A subprocess exited unexpectedly.")
            shutdown_logging()
            gc.collect()
        logger.info("All experiments completed successfully")
