# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Environment: process-level orchestration of the simulation."""
from __future__ import annotations

import gc, json, psutil, time
import multiprocessing as mp
from multiprocessing.context import BaseContext
from pathlib import Path
from typing import Any, Dict

from core.configuration.config import Config
from core.main.arena import ArenaFactory
from core.main.environment.affinity import (
    pick_least_used_free_cores,
    set_affinity_safely,
    set_shared_affinity,
    used_cores,
)
from core.main.environment.agents import (
    agents_init,
    compute_agent_processes,
    _count_agents,
    _split_agents,
)
from core.main.environment.process_wrappers import (
    _run_arena_process,
    _run_collision_detector_process,
    _run_detection_server,
    _run_gui_process,
    _run_manager_process,
    _run_message_server,
)
from core.util.folder_util import (
    derive_experiment_folder_basename,
    generate_shared_unique_folder_name,
    resolve_base_dirs,
    resolve_result_specs,
)
from core.util.logging_util import (
    get_logger,
    is_file_logging_enabled,
    is_logging_enabled,
    shutdown_logging,
)
from core.collision.collision_detector import CollisionDetector
from core.gui import GuiFactory

logger = get_logger("environment")


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


class Environment:
    """Environment orchestrates arenas, managers, GUI, and optional services."""

    def __init__(self, config_elem: Config, config_path: Path, log_root: Path | None = None):
        """Initialize the instance."""
        self.experiments = tuple(config_elem.parse_experiments())
        self.num_runs = int(config_elem.environment.get("num_runs", 1))
        self.time_limit = int(config_elem.environment.get("time_limit", 0))
        gui_id = config_elem.gui.get("_id", "2D")
        self.gui_id = gui_id
        self.quiet = bool(config_elem.environment.get("quiet", False))
        default_stride = 1
        self.snapshot_stride = max(1, int(config_elem.environment.get("snapshot_stride", default_stride)))
        self.auto_agents_per_proc_target = max(1, int(config_elem.environment.get("auto_agents_per_proc_target", 5)))
        base_gui_cfg = dict(config_elem.gui) if len(config_elem.gui) > 0 else {}
        if gui_id in ("none", "off", None) or not base_gui_cfg:
            self.render = [False, {}]
        else:
            self.render = [True, base_gui_cfg]
        self.collisions = config_elem.environment.get("collisions", False)
        if not self.render[0] and self.time_limit == 0:
            logger.warning("Running infinite experiment with no GUI; ensure you have a stop condition.")
        self._log_set = config_elem.environment.get("logging")
        self._logging_enabled = is_logging_enabled(self._log_set)
        self._file_logging_enabled = is_file_logging_enabled(self._log_set)
        self._log_path = config_path.expanduser().resolve()
        self._log_root = Path(__file__).resolve().parents[1]
        self._session_log_root = log_root
        self._base_log_specs = {
            "settings": self._log_set,
            "config_path": self._log_path,
            "project_root": self._log_root,
        }
        logger.info("Environment created successfully")

    def arena_init(self, exp: Config, specs):
        """Arena init."""
        arena = ArenaFactory.create_arena(exp)
        if self.num_runs > 1 and arena.get_seed() < 0:
            arena.reset_seed()
        arena.initialize()
        return arena

    def agents_init(self, exp: Config, specs):
        """Agents init (delegated to helper)."""
        return agents_init(exp, logger)

    def _compute_agent_processes(self, agents: Dict[str, tuple[Dict[str, Any], list]]) -> int:
        """Compute number of agent manager processes with internal heuristics."""
        render_enabled = self.render[0]
        return compute_agent_processes(agents, render_enabled)

    def start(self):
        """Start the process."""
        ctx = mp.get_context("fork")
        used_cores.clear()
        total_cores = psutil.cpu_count(logical=True) or 1
        logging_enabled = self._logging_enabled
        file_logging_enabled = self._file_logging_enabled
        session_logs_root = (
            Path(self._session_log_root).expanduser().resolve()
            if self._session_log_root and file_logging_enabled
            else None
        )
        if session_logs_root is not None:
            session_logs_root.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Environment start: experiments=%d logging=%s file_logging=%s",
            len(self.experiments),
            logging_enabled,
            file_logging_enabled,
        )
        def _create_queue(label: str):
            """Try to create an IPC queue, falling back to _PipeQueue on permission failures."""
            try:
                return ctx.Queue()
            except PermissionError as exc:
                logger.critical(
                    "Permission denied creating %s; falling back to PipeQueue: %s",
                    label,
                    exc,
                )
                try:
                    return _PipeQueue(ctx)
                except Exception as exc2:
                    logger.critical(
                        "PipeQueue fallback failed for %s: %s",
                        label,
                        exc2,
                    )
                    raise
        try:
            env_core = pick_least_used_free_cores(1)
            if env_core:
                psutil.Process().cpu_affinity(env_core)
                used_cores.update(env_core)
        except Exception as e:
            logger.warning("Could not set environment CPU affinity: %s", e)

        def _kill_child_processes(note: str = ""):
            """Force kill all child processes of this environment."""
            try:
                parent = psutil.Process()
                children = parent.children(recursive=True)
                if children:
                    logger.critical("Killing %d child processes%s", len(children), f" ({note})" if note else "")
                for proc in children:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                time.sleep(0.1)
                for proc in children:
                    if proc.is_running():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                for proc in children:
                    try:
                        proc.wait(timeout=0.5)
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Failed to kill child processes: %s", exc)

        def _brutal_kill_all_children(note: str = ""):
            """Immediately kill all child processes (no grace)."""
            try:
                parent = psutil.Process()
                children = parent.children(recursive=True)
                if children:
                    try:
                        targets = ", ".join(f"{c.pid}:{c.name()}" for c in children)
                    except Exception:
                        targets = ", ".join(str(c.pid) for c in children)
                    logger.info(
                        "BRUTAL KILL %d child processes%s -> [%s]",
                        len(children),
                        f" ({note})" if note else "",
                        targets,
                    )
                for proc in children:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                for proc in children:
                    try:
                        proc.wait(timeout=0.5)
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Failed brutal kill of children: %s", exc)

        for exp in self.experiments:
            results_cfg = exp.environment.get("results", {}) or {}
            agent_specs, group_specs = resolve_result_specs(results_cfg)
            results_enabled = bool(results_cfg)
            results_root = default_logs_root = logs_root = None
            if logging_enabled or results_enabled:
                results_root, default_logs_root = resolve_base_dirs(
                    self._log_set if logging_enabled else {},
                    results_cfg if results_enabled else {},
                )
            if file_logging_enabled:
                logs_root = session_logs_root or default_logs_root

            if file_logging_enabled and logs_root:
                logs_root.mkdir(parents=True, exist_ok=True)
            if results_enabled and results_root:
                results_root.mkdir(parents=True, exist_ok=True)

            folder_name = None
            if logging_enabled or results_enabled:
                folder_base = derive_experiment_folder_basename(exp, agent_specs, group_specs)
                base_paths = tuple(
                    p
                    for p in (
                        logs_root if file_logging_enabled else None,
                        results_root if results_enabled else None,
                    )
                    if p
                )
                folder_name = generate_shared_unique_folder_name(base_paths, folder_base)
                exp.output_folder_name = folder_name
            else:
                exp.output_folder_name = None

            runs_root = None
            experiment_folder = None
            if file_logging_enabled and logs_root and folder_name:
                experiment_folder = logs_root / folder_name
                experiment_folder.mkdir(parents=True, exist_ok=True)
                config_path = experiment_folder / "config.json"
                with open(config_path, "w", encoding="utf-8") as cfg_file:
                    json.dump(exp.data, cfg_file, indent=4, default=str)
                runs_root = experiment_folder
            exp_log_specs = {
                **self._base_log_specs,
                "log_folder": experiment_folder,
                "runs_root": runs_root,
            }
            assigned_worker_cores = set()

            def _safe_terminate(proc):
                if proc and proc.is_alive():
                    proc.terminate()

            def _safe_kill(proc):
                if proc and proc.is_alive():
                    try:
                        proc.kill()
                    except Exception as exc:
                        logger.warning("Failed to kill %s: %s", getattr(proc, "pid", "?"), exc)

            def _safe_join(proc, *, label: str = "", timeout: float | None = None):
                """Join a process with a timeout, then terminate/kill if still alive."""
                if proc is None or proc.pid is None:
                    return
                try:
                    proc.join(timeout=timeout)
                    if proc.is_alive():
                        logger.warning(
                            "Process %s did not exit after %.2fs; forcing terminate",
                            label or proc.pid,
                            0 if timeout is None else timeout,
                        )
                        proc.terminate()
                        proc.join(timeout=1.0)
                    if proc.is_alive():
                        logger.warning("Process %s still alive; killing", label or proc.pid)
                        _safe_kill(proc)
                        proc.join(timeout=0.5)
                        if proc.is_alive():
                            logger.warning("Process %s still alive after kill attempt", label or proc.pid)
                except Exception as exc:
                    logger.warning("Failed to join %s: %s", label or proc.pid, exc)

            process_names: dict[mp.Process, str] = {}

            def _register_process(label: str, proc: mp.Process | None):
                if proc is not None:
                    process_names[proc] = label

            def _process_label(proc: mp.Process | None) -> str:
                if proc is None:
                    return "<none>"
                return process_names.get(proc, f"pid={proc.pid}")

            def _log_process_status(stage: str, label: str, proc: mp.Process | None):
                if proc is None:
                    logger.info("[%s] %s: not started", stage, label)
                    return
                try:
                    logger.info(
                        "[%s] %s pid=%s exitcode=%s alive=%s",
                        stage,
                        label,
                        proc.pid,
                        proc.exitcode,
                        proc.is_alive(),
                    )
                except Exception as exc:
                    logger.warning("[%s] failed to log status for %s: %s", stage, label, exc)

            def _wait_for_exit(proc: mp.Process | None, label: str, timeout: float = 1.0) -> bool:
                """Wait briefly for a process to exit, returning True if it stopped."""
                if proc is None:
                    return True
                deadline = time.time() + timeout
                while proc.is_alive() and time.time() < deadline:
                    time.sleep(0.02)
                if proc.is_alive():
                    logger.warning("%s still alive after %.2fs", label, timeout)
                    return False
                return True

            dec_arena_in = _PipeQueue(ctx) if self.collisions else None
            gui_in_queue = _PipeQueue(ctx)
            gui_control_queue = _PipeQueue(ctx)
            dec_control_queue = _PipeQueue(ctx) if self.collisions else None
            arena = self.arena_init(exp, exp_log_specs)
            try:
                arena.quiet = self.quiet
            except Exception:
                pass
            agents = self.agents_init(exp, exp_log_specs)
            render_enabled = self.render[0]
            total_agents = _count_agents(agents)
            n_agent_procs = self._compute_agent_processes(agents)
            logger.info(
                "Agent process auto-split: total_...=%d -> processes=%d",
                total_agents,
                n_agent_procs,
            )
            agent_blocks = _split_agents(agents, n_agent_procs)
            n_blocks = len(agent_blocks)
            agent_barrier = None
            if n_blocks > 1:
                try:
                    agent_barrier = ctx.Barrier(n_blocks)
                except PermissionError:
                    logger.warning(
                        "Falling back to single process: semaphore/barrier creation denied (likely /dev/shm)."
                    )
                    n_agent_procs = 1
                    agent_blocks = [agents]
                    n_blocks = 1
                    agent_barrier = None
            any_messages = any(cfg.get("messages") for cfg, _ in agents.values())
            detection_server_needed = n_blocks > 1
            dec_agents_in_list = [_PipeQueue(ctx) for _ in range(n_blocks)] if self.collisions else [None] * n_blocks
            dec_agents_out_list = [_PipeQueue(ctx) for _ in range(n_blocks)] if self.collisions else [None] * n_blocks
            arena_queue_list = [_PipeQueue(ctx) for _ in range(n_blocks)]
            agents_queue_list = [_PipeQueue(ctx) for _ in range(n_blocks)]
            arena_shape = arena.get_shape()
            if arena_shape is None:
                raise ValueError("Arena shape was not initialized; cannot start environment.")
            arena_id = arena.get_id()
            wrap_config = arena.get_wrap_config()
            arena_hierarchy = arena.get_hierarchy()
            collision_detector = CollisionDetector(arena_shape, self.collisions, wrap_config=wrap_config) if self.collisions else None
            arena_log_specs = {
                **exp_log_specs,
                "process_folder": "",
                "log_file_prefix": "arena",
            }
            collision_log_specs = None
            if collision_detector:
                collision_log_specs = {
                    **exp_log_specs,
                    "process_folder": "",
                    "log_file_prefix": "collision",
                }
            message_server_log_specs = {
                **exp_log_specs,
                "process_folder": "",
                "log_file_prefix": "message_server",
            } if any_messages else None
            detection_server_log_specs = {
                **exp_log_specs,
                "process_folder": "",
                "log_file_prefix": "detection_server",
            } if detection_server_needed else None
            gui_log_specs = {
                **exp_log_specs,
                "process_folder": "",
                "log_file_prefix": "gui",
            }
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
                    arena_log_specs,
                    dec_control_queue,
                ),
            )
            manager_processes = []
            _register_process("arena", arena_process)

            try:
                message_channels = []
                detection_channels = []
                for idx_block in range(n_blocks):
                    if any_messages:
                        message_tx = _create_queue(f"message_tx_{idx_block}")
                        message_rx = _create_queue(f"message_rx_{idx_block}")
                    else:
                        message_tx = None
                        message_rx = None
                    if detection_server_needed:
                        detection_tx = _create_queue(f"detection_tx_{idx_block}")
                        detection_rx = _create_queue(f"detection_rx_{idx_block}")
                    else:
                        detection_tx = None
                        detection_rx = None
                    message_channels.append((message_tx, message_rx))
                    detection_channels.append((detection_tx, detection_rx))

                for idx_block, block in enumerate(agent_blocks):
                    block_filtered = {k: v for k, v in block.items() if len(v[1]) > 0}
                    proc = mp.Process(
                        target=_run_manager_process,
                        args=(
                            block_filtered,
                            arena_shape,
                            exp_log_specs,
                            wrap_config,
                            arena_hierarchy,
                            self.snapshot_stride,
                            idx_block,
                            self.collisions,
                            message_channels[idx_block][0],
                            message_channels[idx_block][1],
                            detection_channels[idx_block][0],
                            detection_channels[idx_block][1],
                            self.num_runs,
                            self.time_limit,
                            arena_queue_list[idx_block],
                            agents_queue_list[idx_block],
                            dec_agents_in_list[idx_block],
                            dec_agents_out_list[idx_block],
                            agent_barrier,
                        ),
                    )

                    manager_processes.append(proc)
                    _register_process(f"manager_{idx_block}", proc)
                fully_connected = True
                message_server_process = None
                detection_server_process = None
                if any_messages:
                    message_server_process = mp.Process(
                        target=_run_message_server,
                        args=(message_channels, message_server_log_specs, fully_connected),
                    )
                if detection_server_needed:
                    detection_server_process = mp.Process(
                        target=_run_detection_server,
                        args=(detection_channels, detection_server_log_specs),
                    )
            except Exception:
                logger.critical(
                    "Environment failed to bootstrap subprocesses; forcing logging shutdown"
                )
                shutdown_logging()
                raise
            gui_process = None
            _register_process("message_server", message_server_process)
            _register_process("detection_server", detection_server_process)

            def _signal_message_server_shutdown():
                """Request the message server to stop via its queues."""
                if message_server_process is None:
                    return
                shutdown_packet = {"kind": "shutdown"}
                for tx, _ in message_channels:
                    if tx is None:
                        continue
                    try:
                        tx.put(shutdown_packet)
                    except Exception:
                        continue

            def _signal_detection_server_shutdown():
                """Request the detection server to stop via its queues."""
                if detection_server_process is None:
                    return
                shutdown_packet = {"kind": "shutdown"}
                for tx, _ in detection_channels:
                    if tx is None:
                        continue
                    try:
                        tx.put(shutdown_packet)
                    except Exception:
                        continue

            def _stop_message_server_gracefully(timeout: float = 1.0):
                """Signal shutdown, wait briefly, then terminate if still alive."""
                if message_server_process is None:
                    return
                _signal_message_server_shutdown()
                logger.info("SHUTDOWN: waiting for message_server to exit")
                deadline = time.time() + timeout
                while message_server_process.is_alive() and time.time() < deadline:
                    time.sleep(0.01)
                if message_server_process.is_alive():
                    logger.warning("Message server did not exit in %.2fs; terminating", timeout)
                    _safe_terminate(message_server_process)
                    time.sleep(0.05)
                if message_server_process.is_alive():
                    logger.warning("Message server still alive; killing")
                    _safe_kill(message_server_process)
                else:
                    logger.info("Message server exited gracefully after shutdown request")
                logger.info("SHUTDOWN: message_server alive=%s exitcode=%s", message_server_process.is_alive(), message_server_process.exitcode)

            def _stop_detection_server_gracefully(timeout: float = 1.0):
                """Signal shutdown, wait briefly, then terminate if still alive."""
                if detection_server_process is None:
                    return
                _signal_detection_server_shutdown()
                logger.info("SHUTDOWN: waiting for detection_server to exit")
                deadline = time.time() + timeout
                while detection_server_process.is_alive() and time.time() < deadline:
                    time.sleep(0.01)
                if detection_server_process.is_alive():
                    logger.warning("Detection server did not exit in %.2fs; terminating", timeout)
                    _safe_terminate(detection_server_process)
                    time.sleep(0.05)
                if detection_server_process.is_alive():
                    logger.warning("Detection server still alive; killing")
                    _safe_kill(detection_server_process)
                else:
                    logger.info("Detection server exited gracefully after shutdown request")
                logger.info("SHUTDOWN: detection_server alive=%s exitcode=%s", detection_server_process.is_alive(), detection_server_process.exitcode)

            def _signal_gui_shutdown():
                """Request the GUI process to stop via its input queue."""
                if gui_in_queue is None:
                    return
                try:
                    gui_in_queue.put({"status": "shutdown"})
                except Exception:
                    pass
                try:
                    gui_control_queue.put("shutdown")
                except Exception:
                    pass

            def _stop_gui_gracefully(timeout: float = 1.0):
                """Signal shutdown and wait for the GUI to exit."""
                nonlocal gui_process
                if gui_process is None:
                    return
                _signal_gui_shutdown()
                deadline = time.time() + timeout
                while gui_process.is_alive() and time.time() < deadline:
                    time.sleep(0.01)
                if gui_process.is_alive():
                    logger.warning("GUI did not exit in %.2fs; terminating", timeout)
                    _safe_terminate(gui_process)

            def _request_arena_shutdown(timeout: float = 1.0, terminate_after: bool = True):
                """Ask arena to stop via the GUI control channel and wait briefly."""
                if arena_process is None:
                    return
                try:
                    gui_control_queue.put("shutdown")
                    logger.info("Requested arena shutdown via control channel")
                except Exception as exc:
                    logger.warning("Failed to request arena shutdown: %s", exc)
                exited = _wait_for_exit(arena_process, "arena", timeout=timeout)
                if not exited and terminate_after:
                    _safe_terminate(arena_process)

            def _broadcast_manager_shutdown():
                """Push shutdown packets to all manager inbound queues."""
                for q in arena_queue_list:
                    if q is None:
                        continue
                    try:
                        q.put({"status": "shutdown"})
                        logger.info("Sent shutdown to manager queue")
                    except Exception:
                        pass

            if not self.collisions:
                det_in_arg = None
                det_out_arg = None
            else:
                det_in_arg = dec_agents_in_list if n_blocks > 1 else dec_agents_in_list[0]
                det_out_arg = dec_agents_out_list if n_blocks > 1 else dec_agents_out_list[0]

            collision_detector_process = None
            if collision_detector:
                collision_detector_process = mp.Process(
                    target=_run_collision_detector_process,
                    args=(collision_detector, det_in_arg, det_out_arg, dec_arena_in, collision_log_specs, dec_control_queue),
                )
            _register_process("collision_detector", collision_detector_process)

            def _signal_detector_shutdown():
                """Request the collision detector to stop."""
                if dec_control_queue is None:
                    return
                shutdown_packet = {"kind": "shutdown"}
                try:
                    dec_control_queue.put(shutdown_packet)
                except Exception:
                    pass

            def _stop_detector_gracefully(timeout: float = 1.0):
                """Signal shutdown and wait for the detector to exit."""
                if collision_detector_process is None:
                    return
                _signal_detector_shutdown()
                logger.info("SHUTDOWN: waiting for detector to exit")
                deadline = time.time() + timeout
                while collision_detector_process.is_alive() and time.time() < deadline:
                    time.sleep(0.0001)
                if collision_detector_process.is_alive():
                    logger.warning("Detector did not exit in %.2fs; terminating", timeout)
                    _safe_terminate(collision_detector_process)
                    time.sleep(0.05)
                if collision_detector_process.is_alive():
                    logger.warning("Detector still alive; killing")
                    _safe_kill(collision_detector_process)
                logger.info("SHUTDOWN: detector alive=%s exitcode=%s", collision_detector_process.is_alive(), collision_detector_process.exitcode)

            pattern = {
                "arena": 2,
                "agents": 2,
                "collision": 2,
                "gui": 2,
                "messages": 2,
                "detection": 2,
            }
            if total_agents >= 100:
                extra_load = total_agents // 100
                pattern["agents"] = 3 + extra_load
                pattern["collision"] = 3 + extra_load
            killed = 0
            force_exit = False
            try:
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
                            gui_log_specs,
                            wrap_config,
                            hierarchy_overlay,
                        ),
                    )
                    gui_process.start()
                    _register_process("gui", gui_process)
                    if message_server_process:
                        message_server_process.start()
                    if detection_server_process:
                        detection_server_process.start()
                    if collision_detector_process and arena_id not in ("abstract", "none", None):
                        collision_detector_process.start()
                    for proc in manager_processes:
                        proc.start()
                    arena_process.start()

                    assigned_worker_cores.update(set_affinity_safely(arena_process, pattern["arena"]))
                    available_remaining = max(1, total_cores - len(used_cores))
                    agent_core_budget = min(n_blocks * 2, available_remaining)
                    agent_core_budget = max(agent_core_budget, 1)
                    assigned_worker_cores.update(set_shared_affinity(manager_processes, agent_core_budget))
                    if collision_detector_process:
                        assigned_worker_cores.update(set_affinity_safely(collision_detector_process, pattern["collision"]))
                    assigned_worker_cores.update(set_affinity_safely(gui_process, pattern["gui"]))
                    if message_server_process:
                        assigned_worker_cores.update(set_affinity_safely(message_server_process, pattern["messages"]))
                    if detection_server_process:
                        assigned_worker_cores.update(set_affinity_safely(detection_server_process, pattern["detection"]))

                    force_exit = False
                    while True:
                        processes_to_watch = [arena_process, message_server_process, detection_server_process, collision_detector_process] + manager_processes
                        exit_failure = next(
                            (p for p in processes_to_watch if p is not None and p.exitcode not in (None, 0)),
                            None,
                        )
                        arena_alive = arena_process.is_alive()
                        gui_alive = gui_process.is_alive()
                        if exit_failure:
                            logger.error(
                                "Process %s exited unexpectedly (exitcode=%s, alive=%s)",
                                _process_label(exit_failure),
                                exit_failure.exitcode,
                                exit_failure.is_alive(),
                            )
                            killed = 1
                            _request_arena_shutdown(timeout=0.5, terminate_after=True)
                            _safe_terminate(arena_process)
                            _safe_terminate(message_server_process)
                            _safe_terminate(detection_server_process)
                            if arena_process.is_alive():
                                _safe_kill(arena_process)
                            if message_server_process and message_server_process.is_alive():
                                _safe_kill(message_server_process)
                            if detection_server_process and detection_server_process.is_alive():
                                _safe_kill(detection_server_process)
                            for proc in manager_processes:
                                _wait_for_exit(proc, _process_label(proc), timeout=0.5)
                            for proc in manager_processes:
                                if proc.is_alive():
                                    _safe_terminate(proc)
                                if proc.is_alive():
                                    _safe_kill(proc)
                            _stop_detector_gracefully()
                            _stop_gui_gracefully()
                            if gui_process.is_alive():
                                _safe_terminate(gui_process)
                                if gui_process.is_alive():
                                    _safe_kill(gui_process)
                            _stop_message_server_gracefully()
                            break
                        if not arena_alive or not gui_alive:
                            logger.info(
                                "Process exit detected (arena_alive=%s gui_alive=%s), starting shutdown",
                                arena_alive,
                                gui_alive,
                            )
                            if gui_alive is False and arena_alive:
                                _brutal_kill_all_children("gui dead -> hard stop")
                                force_exit = True
                                break
                            _request_arena_shutdown(timeout=0.2, terminate_after=False)
                            _broadcast_manager_shutdown()
                            _stop_detector_gracefully()
                            _stop_gui_gracefully()
                            _stop_message_server_gracefully()
                            _kill_child_processes("arena dead (render)")
                            force_exit = True
                            break
                        time.sleep(0.05)
                    if not force_exit:
                        _stop_detector_gracefully()
                        _stop_gui_gracefully()
                        _stop_message_server_gracefully()
                        logger.info("SHUTDOWN: joining processes (render branch)")
                        _safe_join(arena_process, label="arena", timeout=1.0)
                        for proc in manager_processes:
                            _safe_join(proc, label=_process_label(proc), timeout=1.0)
                        _safe_join(collision_detector_process, label="collision_detector", timeout=1.0)
                        _safe_join(gui_process, label="gui", timeout=1.0)
                        _safe_join(message_server_process, label="message_server", timeout=1.0) if message_server_process else None
                        _safe_join(detection_server_process, label="detection_server", timeout=1.0) if detection_server_process else None
                        _kill_child_processes("after render shutdown")
                else:
                    if message_server_process:
                        message_server_process.start()
                    if detection_server_process:
                        detection_server_process.start()
                    if collision_detector_process and arena_id not in ("abstract", "none", None):
                        collision_detector_process.start()
                    for proc in manager_processes:
                        proc.start()
                    arena_process.start()
                    assigned_worker_cores.update(set_affinity_safely(arena_process, pattern["arena"]))
                    available_remaining = max(1, total_cores - len(used_cores))
                    agent_core_budget = min(n_blocks * 2, available_remaining)
                    agent_core_budget = max(agent_core_budget, 1)
                    assigned_worker_cores.update(set_shared_affinity(manager_processes, agent_core_budget))
                    if collision_detector_process:
                        assigned_worker_cores.update(set_affinity_safely(collision_detector_process, pattern["collision"]))
                    if message_server_process:
                        assigned_worker_cores.update(set_affinity_safely(message_server_process, pattern["messages"]))
                    if detection_server_process:
                        assigned_worker_cores.update(set_affinity_safely(detection_server_process, pattern["detection"]))
                    killed = 0
                    while True:
                        processes_to_watch = [arena_process, message_server_process, detection_server_process, collision_detector_process] + manager_processes
                        exit_failure = next(
                            (p for p in processes_to_watch if p is not None and p.exitcode not in (None, 0)),
                            None,
                        )
                        arena_alive = arena_process.is_alive()
                        if exit_failure:
                            logger.error(
                                "Process %s exited unexpectedly (exitcode=%s, alive=%s)",
                                _process_label(exit_failure),
                                exit_failure.exitcode,
                                exit_failure.is_alive(),
                            )
                            killed = 1
                            _request_arena_shutdown(timeout=0.5, terminate_after=True)
                            _safe_terminate(arena_process)
                            if arena_process.is_alive():
                                _safe_kill(arena_process)
                            for proc in manager_processes:
                                _safe_terminate(proc)
                                if proc.is_alive():
                                    _safe_kill(proc)
                            _stop_detector_gracefully()
                            _stop_message_server_gracefully()
                            _stop_detection_server_gracefully()
                            break
                        if not arena_alive:
                            _request_arena_shutdown(timeout=0.5, terminate_after=True)
                            _safe_terminate(arena_process)
                            for proc in manager_processes:
                                _safe_terminate(proc)
                            _stop_detector_gracefully()
                            _stop_message_server_gracefully()
                            _stop_detection_server_gracefully()
                            break
                        time.sleep(0.5)
                    _stop_detector_gracefully()
                    _stop_message_server_gracefully()
                    _stop_detection_server_gracefully()
                    logger.info("SHUTDOWN: joining processes (headless branch)")
                    _safe_join(arena_process, label="arena", timeout=1.0)
                    for proc in manager_processes:
                        _safe_join(proc, label=_process_label(proc), timeout=1.0)
                    _safe_join(collision_detector_process, label="collision_detector", timeout=1.0)
                    _safe_join(message_server_process, label="message_server", timeout=1.0) if message_server_process else None
                    _safe_join(detection_server_process, label="detection_server", timeout=1.0) if detection_server_process else None
                    if killed == 1:
                        raise RuntimeError("A subprocess exited unexpectedly.")
                    _kill_child_processes("after headless shutdown")
            finally:
                if force_exit:
                    _brutal_kill_all_children("force_exit cleanup")
                else:
                    _stop_detector_gracefully()
                    _stop_gui_gracefully()
                    _stop_message_server_gracefully()
                    _stop_detection_server_gracefully()
                    _safe_terminate(arena_process)
                    _safe_terminate(collision_detector_process)
                    _safe_terminate(gui_process)
                    _safe_terminate(message_server_process) if message_server_process else None
                    _safe_terminate(detection_server_process) if detection_server_process else None
                    for proc in manager_processes:
                        _safe_terminate(proc)
                    _request_arena_shutdown(timeout=0.2)
                    _safe_join(arena_process, label="arena", timeout=2.0)
                    for proc in manager_processes:
                        _safe_join(proc, label=_process_label(proc), timeout=2.0)
                    _safe_join(collision_detector_process, label="collision_detector", timeout=2.0)
                    _safe_join(gui_process, label="gui", timeout=2.0)
                    _safe_join(message_server_process, label="message_server", timeout=2.0) if message_server_process else None
                    _safe_join(detection_server_process, label="detection_server", timeout=2.0) if detection_server_process else None
                    _kill_child_processes("final cleanup")
                    for label, proc in [
                        ("arena", arena_process),
                        ("gui", gui_process),
                        ("message_server", message_server_process),
                        ("detection_server", detection_server_process),
                        ("collision_detector", collision_detector_process),
                    ]:
                        _log_process_status("post_join", label, proc)
                    for idx, proc in enumerate(manager_processes):
                        _log_process_status("post_join", f"manager_{idx}", proc)
            logger.critical("Environment final cleanup: invoking shutdown_logging()")
            shutdown_logging()
            gc.collect()
            used_cores.difference_update(assigned_worker_cores)
        logger.info("All experiments completed successfully")
