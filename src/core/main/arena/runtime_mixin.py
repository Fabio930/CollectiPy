# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Runtime loop and logging helpers for arenas."""
from __future__ import annotations

import time
from typing import Any, cast

from core.util.logging_util import start_run_logging, shutdown_logging

from core.util.logging_util import get_logger

logger = get_logger("arena")


class RuntimeMixin:
    """Mixin implementing the main arena run loop and logging helpers."""

    def pack_objects_data(self) -> dict:
        """Pack objects data."""
        out = {}
        for _, entities in self.objects.values():
            shapes = []
            positions = []
            strengths = []
            uncertainties = []
            for n in range(len(entities)):
                shapes.append(entities[n].get_shape())
                positions.append(entities[n].get_position())
                strengths.append(entities[n].get_strength())
                uncertainties.append(entities[n].get_uncertainty())
            out.update({entities[0].entity(): (shapes, positions, strengths, uncertainties)})
        return out

    def _format_position(self, position):
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
                grouped.setdefault(entity.entity(), []).append(f"{entity.get_name()}={pos}")
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
            logger.info("Run %d %s %s positions: %s", run, tick_label, entity_type, "; ".join(entries))

    def pack_detector_data(self) -> dict:
        """Pack detector data."""
        out = {}
        for _, entities in self.objects.values():
            shapes = []
            positions = []
            for n in range(len(entities)):
                shapes.append(entities[n].get_shape())
                positions.append(entities[n].get_position())
            out.update({entities[0].entity(): (shapes, positions)})
        return out

    def _apply_gui_backpressure(self, gui_in_queue):
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

    def run(
        self,
        num_runs,
        time_limit,
        arena_queue: Any,
        agents_queue: Any,
        gui_in_queue: Any,
        dec_arena_in: Any,
        gui_control_queue: Any,
        render: bool = False,
        log_context: dict | None = None,
        dec_control_queue: Any = None,
    ):
        """Function to run the arena in a separate process (supports multiple agent queues)."""
        arena_queues = arena_queue if isinstance(arena_queue, list) else [arena_queue]
        agents_queues = agents_queue if isinstance(agents_queue, list) else [agents_queue]
        n_managers = len(agents_queues)

        shutdown_requested = False
        shutdown_notified = False

        def _is_shutdown_command(cmd: Any) -> bool:
            """Return True if the GUI requested a shutdown."""
            if cmd == "shutdown":
                return True
            if isinstance(cmd, (list, tuple)) and len(cmd) > 0 and cmd[0] == "shutdown":
                return True
            return False

        def _signal_shutdown(reason: str = "gui_request"):
            """Notify managers/GUI/detector that we are stopping."""
            nonlocal shutdown_requested, shutdown_notified
            shutdown_requested = True
            if shutdown_notified:
                return
            shutdown_notified = True
            payload = {"status": "shutdown", "reason": reason}
            for q in arena_queues:
                if q is None:
                    continue
                try:
                    q.put(payload)
                except Exception:
                    pass
            if gui_in_queue is not None:
                try:
                    gui_in_queue.put(payload)
                except Exception:
                    pass
            if dec_control_queue is not None:
                try:
                    dec_control_queue.put({"kind": "shutdown"})
                except Exception:
                    pass

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
<<<<<<< Updated upstream
            metadata = {k: list(v) for k, v in cached_metadata.items()}
=======
            # Rebuild metadata for this tick from manager snapshots to
            # preserve per-manager ordering (same order used for shapes/spins).
            # Fallback to cached metadata only for groups that did not produce
            # any snapshot in this batch.
            metadata = {}
>>>>>>> Stashed changes
            for snap in snapshots:
                if not snap:
                    continue
                for grp, vals in snap.get("agents_shapes", {}).items():
                    shapes.setdefault(grp, []).extend(vals)
                for grp, vals in snap.get("agents_spins", {}).items():
                    spins.setdefault(grp, []).extend(vals)
                for grp, vals in snap.get("agents_metadata", {}).items():
                    metadata.setdefault(grp, []).extend(vals)
<<<<<<< Updated upstream
=======
            # For any group that did not appear in this batch, keep the
            # previously cached metadata so downstream code still has
            # something to work with.
            for k, v in cached_metadata.items():
                if k not in metadata:
                    metadata[k] = list(v)
>>>>>>> Stashed changes
            # If no metadata arrived in this batch, keep cached metadata.
            return shapes, spins, metadata

        ticks_limit = time_limit * self.ticks_per_second + 1 if time_limit > 0 else 0
        tick_interval = 1.0 / max(1, self.ticks_per_second)
        run = 1
        log_context = log_context or {}
        log_specs = log_context.get("log_specs")
        process_name = log_context.get("process_name", "arena")
        debug_wait_cycles = 0
        while run < num_runs + 1:
            start_run_logging(log_specs, process_name, run)
            try:
                logger.info(f"Run number {run} started")
                self._log_object_positions(run, "tick 0")
                initial_objects = self.pack_objects_data()
                arena_data = {
                    "status": [0, self.ticks_per_second],
                    "objects": initial_objects,
                    "run": run,
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
                for q in arena_queues:
                    q.put({**arena_data, "random_seed": self.random_seed})

                latest_agent_data: list[dict[str, Any] | None] = [None] * n_managers
                for idx, q in enumerate(agents_queues):
                    latest_agent_data[idx] = self._maybe_get(q, timeout=1.0)
                if any(d is None for d in latest_agent_data):
                    break
                first_entry = latest_agent_data[0]
                if not isinstance(first_entry, dict):
                    break
                self.agents_shapes, self.agents_spins, self.agents_metadata = _combine_agent_snapshots(
                    latest_agent_data,
                    self.agents_shapes,
                    self.agents_spins,
                    self.agents_metadata,
                )
                if render:
                    gui_in_queue.put(
                        {
                            **arena_data,
                            "agents_shapes": self.agents_shapes,
                            "agents_spins": self.agents_spins,
                            "agents_metadata": self.agents_metadata,
                        }
                    )
                    self._apply_gui_backpressure(gui_in_queue)
                violation = self._find_float_limit_violation(self.agents_shapes, initial_objects)
                if violation:
                    kind, group, idx, component, coords, margin, radius = violation
                    logger.critical(
                        "Detected coordinates near float limit for %s %s[%s] (%s=%s, margin=%.4e, radius=%.4e); requesting shutdown",
                        kind,
                        group,
                        idx,
                        component,
                        coords,
                        margin,
                        radius,
                    )
                    _signal_shutdown("float_limit_violation")
                    shutdown_requested = True
                    break
                initial_tick_rate = cast(dict[str, Any], first_entry).get("status", [0, self.ticks_per_second])[1]
                if self.data_handling is not None:
                    self.data_handling.new_run(
                        run,
                        self.agents_shapes,
                        self.agents_spins,
                        self.agents_metadata,
                        initial_tick_rate,
                    )
                t = 1
                running = False if render else True
                step_mode = False
                reset = False
                last_snapshot_info = None
                while True:
                    if ticks_limit > 0 and t >= ticks_limit:
                        break
                    if render:
                        cmd = self._maybe_get(gui_control_queue, timeout=0.0)
                        while cmd is not None:
                            if _is_shutdown_command(cmd):
                                _signal_shutdown("gui_command")
                                running = False
                                step_mode = False
                                reset = False
                                break
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
                        if shutdown_requested:
                            break
                    arena_data = {
                        "status": [t, self.ticks_per_second],
                        "objects": self.pack_objects_data(),
                        "run": run,
                    }
                    if running or step_mode:
                        if not render and not getattr(self, "quiet", False):
                            print(f"\rrun {run} arena_ticks {t}", end="", flush=True)
                        for q in arena_queues:
                            q.put(arena_data)
                        ready = [False] * n_managers
                        while not all(ready):
                            if shutdown_requested:
                                break
                            debug_wait_cycles += 1
                            if debug_wait_cycles % 500 == 0:
                                try:
                                    backlogs = [q.qsize() for q in agents_queues]
                                except Exception:
                                    backlogs = []
                                logger.debug(
                                    "[ARENA WAIT] run=%s t=%s ready=%s q_backlog=%s shutdown=%s",
                                    run,
                                    t,
                                    ready,
                                    backlogs,
                                    shutdown_requested,
                                )
                            for idx, q in enumerate(agents_queues):
                                candidate = self._maybe_get(q, timeout=0.01)
                                if candidate is not None:
                                    latest_agent_data[idx] = candidate
                            for idx, snap in enumerate(latest_agent_data):
                                ready[idx] = bool(snap and snap["status"][0] / snap["status"][1] >= t / self.ticks_per_second)
                            if shutdown_requested:
                                break
                            detector_data = {
                                "objects": self.pack_detector_data(),
                                "run": run,
                            }
                            if all(q.qsize() == 0 for q in arena_queues):
                                for q in arena_queues:
                                    q.put(arena_data)
                                if dec_arena_in is not None:
                                    dec_arena_in.put(detector_data)
                            time.sleep(0.00005)
                        if shutdown_requested:
                            break

                        for idx, q in enumerate(agents_queues):
                            latest = self._maybe_get(q, timeout=0.0)
                            if latest is not None:
                                latest_agent_data[idx] = latest
                        self.agents_shapes, self.agents_spins, self.agents_metadata = _combine_agent_snapshots(
                            latest_agent_data,
                            self.agents_shapes,
                            self.agents_spins,
                            self.agents_metadata,
                        )
                        violation = self._find_float_limit_violation(self.agents_shapes, arena_data.get("objects"))
                        if violation:
                            kind, group, idx, component, coords, margin, radius = violation
                            logger.critical(
                                "Detected coordinates near float limit for %s %s[%s] (%s=%s, margin=%.4e, radius=%.4e); requesting shutdown",
                                kind,
                                group,
                                idx,
                                component,
                                coords,
                                margin,
                                radius,
                            )
                            _signal_shutdown("float_limit_violation")
                            shutdown_requested = True
                            break
                        if self.data_handling is not None:
                            tick_stamp = arena_data.get("status", [t, self.ticks_per_second])[0]
                            tick_rate = arena_data.get("status", [tick_stamp, self.ticks_per_second])[1]
                            self.data_handling.save(
                                self.agents_shapes,
                                self.agents_spins,
                                self.agents_metadata,
                                tick_stamp,
                                tick_rate,
                            )
                            last_snapshot_info = (tick_stamp, tick_rate)
                        if render:
                            gui_in_queue.put(
                                {**arena_data, "agents_shapes": self.agents_shapes, "agents_spins": self.agents_spins, "agents_metadata": self.agents_metadata}
                            )
                            self._apply_gui_backpressure(gui_in_queue)
                        if self._speed_multiplier > 1.0:
                            time.sleep(tick_interval * (self._speed_multiplier - 1.0))
                        step_mode = False
                        t += 1
                    elif reset:
                        break
                    elif shutdown_requested:
                        break
                    else:
                        time.sleep(0.00025)
                if shutdown_requested:
                    break
                if self.data_handling is not None and last_snapshot_info:
                    self.data_handling.save(
                        self.agents_shapes,
                        self.agents_spins,
                        self.agents_metadata,
                        last_snapshot_info[0],
                        last_snapshot_info[1],
                        force=True,
                    )
                if shutdown_requested:
                    break
                if t < ticks_limit and not reset:
                    break
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
                            "objects": self.pack_objects_data(),
                            "run": run,
                        }
                        for q in arena_queues:
                            q.put(arena_data)
                    if not render:
                        print("")
                elif not reset:
                    run += 1
                    self.close()
                    if not render:
                        print("")
                else:
                    self.randomize_seed()
                    self.reset()
                    arena_data = {
                        "status": "reset",
                        "objects": self.pack_objects_data(),
                        "run": run,
                    }
                    for q in arena_queues:
                        q.put(arena_data)

            finally:
                shutdown_logging()
