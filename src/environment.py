# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Environment: process-level orchestration of the simulation."""
import logging, psutil, gc, time
import multiprocessing as mp
from multiprocessing.context import BaseContext
from typing import Any, Dict
from config import Config
from entity import EntityFactory
from arena import ArenaFactory
from gui import GuiFactory
from entityManager import EntityManager
from collision_detector import CollisionDetector
used_cores = set()

def pick_least_used_free_cores(num):
    """
    Ritorna 'num' core meno usati che NON sono in used_cores.
    """
    # Snapshot del carico CPU
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
            logging.warning("[WARNING] No free cores: fallback to all cores")
            fallback_count = psutil.cpu_count(logical=True) or 1
            selected = list(range(fallback_count))
        p = psutil.Process(proc.pid)
        p.cpu_affinity(selected)
        used_cores.update(selected)
        # print(f"[AFFINITY] PID {proc.pid} -> {selected}")
    except Exception as e:
        logging.error(f"[AFFINITY ERROR] PID {proc.pid}: {e}")

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

class EnvironmentFactory():
    """Environment factory."""
    @staticmethod
    def create_environment(config_elem:Config):
        """Create environment."""
        if config_elem.environment:
            return Environment(config_elem)
        else:
            raise ValueError(f"Invalid environment configuration: {config_elem.environment['parallel_experiments']} {config_elem.environment['render']}")

class Environment():
    """Environment."""
    def __init__(self,config_elem:Config):
        """Initialize the instance."""
        # Freeze experiments to avoid external mutation.
        self.experiments = tuple(config_elem.parse_experiments())
        self.num_runs = int(config_elem.environment.get("num_runs",1))
        self.time_limit = int(config_elem.environment.get("time_limit",0))
        gui_id = config_elem.gui.get("_id","2D")
        self.gui_id = gui_id
        self.quiet = bool(config_elem.environment.get("quiet", False))
        self.snapshot_stride = max(1, int(config_elem.environment.get("snapshot_stride", 1) or 1))
        self.auto_agents_per_proc_target = max(1, int(config_elem.environment.get("auto_agents_per_proc_target", 20) or 20))
        base_gui_cfg = dict(config_elem.gui) if len(config_elem.gui) > 0 else {}
        if gui_id in ("none", "off", None) or not base_gui_cfg:
            self.render = [False, {}]
        else:
            self.render = [True, base_gui_cfg]
        self.collisions = config_elem.environment.get("collisions",False)
        if not self.render[0] and self.time_limit==0:
            raise Exception("Invalid configuration: infinite experiment with no GUI.")
        logging.info("Environment created successfully")

    def arena_init(self,exp:Config):
        """Arena init."""
        arena = ArenaFactory.create_arena(exp)
        if self.num_runs > 1 and arena.get_seed() < 0:
            arena.reset_seed()
        arena.initialize()
        return arena

    def agents_init(self,exp:Config):
        """Agents init."""
        agents_cfg = exp.environment.get("agents") or {}
        if not isinstance(agents_cfg, dict):
            raise ValueError("Invalid agents configuration: expected a dictionary.")
        agents: Dict[str, tuple[Dict[str, Any], list]] = {
            agent_type: (cfg, []) for agent_type, cfg in agents_cfg.items()
        }
        for key,(config,entities) in agents.items():
            if not isinstance(config, dict):
                raise ValueError(f"Invalid agent configuration for {key}")
            number_raw = config.get("number", 0)
            try:
                number = int(number_raw)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid number of agents for {key}: {number_raw}")
            for n in range(number):
                entities.append(EntityFactory.create_entity(entity_type="agent_"+key,config_elem=config,_id=n))
        logging.info(f"Agents initialized: {list(agents.keys())}")
        return agents

    def _split_agents(self, agents: Dict[str, tuple[Dict[str, Any], list]], num_blocks: int) -> list[Dict[str, tuple[Dict[str, Any], list]]]:
        """Split agents into nearly even blocks."""
        if num_blocks <= 1:
            return [agents]
        flat = []
        for agent_type, (cfg, entities) in agents.items():
            for entity in entities:
                flat.append((agent_type, cfg, entity))
        total = len(flat)
        num_blocks = max(1, min(num_blocks, total))
        blocks: list[Dict[str, tuple[Dict[str, Any], list]]] = [dict() for _ in range(num_blocks)]
        for idx, (agent_type, cfg, entity) in enumerate(flat):
            target = idx % num_blocks
            if agent_type not in blocks[target]:
                blocks[target][agent_type] = (cfg, [])
            blocks[target][agent_type][1].append(entity)
        return blocks

    @staticmethod
    def _count_agents(agents: Dict[str, tuple[Dict[str, Any], list]]) -> int:
        """Count total agents."""
        total = 0
        for _, (_, entities) in agents.items():
            total += len(entities)
        return total

    def run_gui(self, config:dict, arena_vertices:list, arena_color:str, gui_in_queue, gui_control_queue, wrap_config=None, hierarchy_overlay=None):
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
        for exp in self.experiments:
            def _safe_terminate(proc):
                if proc and proc.is_alive():
                    proc.terminate()

            def _safe_join(proc, timeout=None):
                if proc and proc.pid is not None:
                    proc.join(timeout=timeout)

            arena_queue = _PipeQueue(ctx)
            agents_queue = _PipeQueue(ctx)
            dec_arena_in = _PipeQueue(ctx)
            gui_in_queue = _PipeQueue(ctx)
            gui_control_queue = _PipeQueue(ctx)
            arena = self.arena_init(exp)
            try:
                arena.quiet = self.quiet
            except Exception:
                pass
            agents = self.agents_init(exp)
            # Multiprocess agent splitting is temporarily forced to 1 to keep queues single-consumer.
            # Temporary safeguard: single agent process to avoid queue corruption.
            processes_requested = 1
            agent_blocks = self._split_agents(agents, processes_requested)
            n_blocks = len(agent_blocks)
            # Detector input/output queues
            dec_agents_in_list = [_PipeQueue(ctx) for _ in range(n_blocks)]
            dec_agents_out_list = [_PipeQueue(ctx) for _ in range(n_blocks)]
            arena_shape = arena.get_shape()
            if arena_shape is None:
                raise ValueError("Arena shape was not initialized; cannot start environment.")
            arena_id = arena.get_id()
            render_enabled = self.render[0]
            wrap_config = arena.get_wrap_config()
            arena_hierarchy = arena.get_hierarchy()
            collision_detector = CollisionDetector(arena_shape, self.collisions, wrap_config=wrap_config)
            arena_process = mp.Process(target=arena.run, args=(self.num_runs, self.time_limit, arena_queue, agents_queue, gui_in_queue, dec_arena_in, gui_control_queue, render_enabled))
            # Managers
            manager_processes = []
            for idx_block, block in enumerate(agent_blocks):
                block_filtered = {k: v for k, v in block.items() if len(v[1]) > 0}
                entity_manager = EntityManager(
                    block_filtered,
                    arena_shape,
                    wrap_config=wrap_config,
                    hierarchy=arena_hierarchy,
                    snapshot_stride=self.snapshot_stride,
                    manager_id=idx_block
                )
                proc = mp.Process(
                    target=entity_manager.run,
                    args=(
                        self.num_runs,
                        self.time_limit,
                        arena_queue,
                        agents_queue,
                        dec_agents_in_list[idx_block],
                        dec_agents_out_list[idx_block]
                )
                )
                manager_processes.append(proc)
            det_in_arg = dec_agents_in_list if n_blocks > 1 else dec_agents_in_list[0]
            det_out_arg = dec_agents_out_list if n_blocks > 1 else dec_agents_out_list[0]
            detector_process = mp.Process(target=collision_detector.run, args=(det_in_arg, det_out_arg, dec_arena_in))
            pattern = {
                "arena": 1,
                "agents": 2,
                "detector": 1,
                "gui": 2
            }
            killed = 0
            if render_enabled:
                render_config = dict(self.render[1])
                render_config["_id"] = "abstract" if arena_id in (None, "none") else self.gui_id
                hierarchy_overlay = arena_hierarchy.to_rectangles() if arena_hierarchy else None
                gui_process = mp.Process(
                    target=self.run_gui,
                    args=(
                        render_config,
                        arena_shape.vertices(),
                        arena_shape.color(),
                        gui_in_queue,
                        gui_control_queue,
                        wrap_config,
                        hierarchy_overlay
                    )
                )
                gui_process.start()
                if detector_process and arena_id not in ("abstract", "none", None):
                    detector_process.start()
                for proc in manager_processes:
                    proc.start()
                arena_process.start()
                set_affinity_safely(arena_process,   pattern["arena"])
                for proc in manager_processes:
                    set_affinity_safely(proc,  pattern["agents"])
                if detector_process:
                    set_affinity_safely(detector_process, pattern["detector"])
                set_affinity_safely(gui_process, pattern["gui"])

                all_processes = [arena_process] + manager_processes
                if detector_process:
                    all_processes.append(detector_process)
                all_processes.append(gui_process)

                while True:
                    exit_failure = next((p for p in all_processes if p.exitcode not in (None, 0)), None)
                    arena_alive = arena_process.is_alive()
                    if exit_failure:
                        killed = 1
                        for proc in all_processes:
                            _safe_terminate(proc)
                        break
                    if not arena_alive:
                        for proc in all_processes:
                            if proc is arena_process:
                                continue
                            _safe_terminate(proc)
                        break
                    if render_enabled and gui_process and not gui_process.is_alive():
                        killed = 1
                        for proc in all_processes:
                            _safe_terminate(proc)
                        break
                    # Zombie/Dead GUI process
                    if render_enabled and gui_process and gui_process.pid is not None:
                        try:
                            gui_status = psutil.Process(gui_process.pid).status()
                            if gui_status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                                killed = 1
                                for proc in all_processes:
                                    _safe_terminate(proc)
                                break
                        except psutil.NoSuchProcess:
                            killed = 1
                            for proc in all_processes:
                                _safe_terminate(proc)
                            break
                    gc.collect()
                    time.sleep(0.01)
                # Join all processes
                _safe_join(arena_process)
                for proc in manager_processes:
                    _safe_join(proc)
                _safe_join(detector_process)
                _safe_join(gui_process)
            else:
                if detector_process and arena_id not in ("abstract", "none", None):
                    detector_process.start()
                for proc in manager_processes:
                    proc.start()
                arena_process.start()
                set_affinity_safely(arena_process,   pattern["arena"])
                for proc in manager_processes:
                    set_affinity_safely(proc,  pattern["agents"])
                if detector_process:
                    set_affinity_safely(detector_process, pattern["detector"])
                while arena_process.is_alive() and all(proc.is_alive() for proc in manager_processes):
                    _safe_join(arena_process, timeout=0.1)
                    for proc in manager_processes:
                        _safe_join(proc, timeout=0.1)
                killed = 0
                if arena_process.exitcode not in (None, 0):
                    killed = 1
                    for proc in manager_processes:
                        _safe_terminate(proc)
                    _safe_terminate(detector_process)
                elif any(proc.exitcode not in (None, 0) for proc in manager_processes):
                    killed = 1
                    if arena_process.is_alive(): arena_process.terminate()
                    _safe_terminate(detector_process)
                # Join all processes
                _safe_join(arena_process)
                for proc in manager_processes:
                    _safe_join(proc)
                if detector_process:
                    _safe_terminate(detector_process)
                    _safe_join(detector_process)
                arena.close()
                if killed == 1:
                    raise RuntimeError("A subprocess exited unexpectedly.")
            gc.collect()
        logging.info("All experiments completed successfully")
