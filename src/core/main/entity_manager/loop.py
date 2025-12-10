# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Main run loop for EntityManager, extracted for readability."""

from __future__ import annotations

import math, time
from typing import Any, Optional
import multiprocessing as mp
from core.util.logging_util import start_run_logging, shutdown_logging
from core.util.logging_util import get_logger

logger = get_logger("entity_manager")


def manager_run(
    manager,
    num_runs: int,
    time_limit: int,
    arena_queue: mp.Queue,
    agents_queue: mp.Queue,
    dec_agents_in: Optional[mp.Queue],
    dec_agents_out: Optional[mp.Queue],
    agent_barrier=None,
    log_context: dict | None = None,
):
    """Execute the main EntityManager loop."""
    ticks_per_second = 1
    for (_, entities) in manager.agents.values():
        if not entities:
            continue
        ent = entities[0]
        if hasattr(ent, "ticks"):
            try:
                ticks_per_second = int(ent.ticks())
            except Exception:
                ticks_per_second = 1
        else:
            try:
                ticks_per_second = int(getattr(ent, "ticks_per_second", 1))
            except Exception:
                ticks_per_second = 1
        break
    ticks_limit = time_limit * ticks_per_second + 1 if time_limit > 0 else 0
    shutdown_requested = False
    debug_wait_cycles = 0

    run = 1
    log_context = log_context or {}
    log_specs = log_context.get("log_specs")
    process_name = log_context.get("process_name", f"manager_{manager.manager_id}")
    logger.info("EntityManager starting for %s runs (time_limit=%s)", num_runs, time_limit)

    def _is_shutdown_status(payload: dict | None) -> bool:
        """Return True when the arena asks managers to exit."""
        if not isinstance(payload, dict):
            return False
        status = payload.get("status")
        if status == "shutdown":
            return True
        if isinstance(status, (list, tuple)) and status and status[0] == "shutdown":
            return True
        return False

    while run < num_runs + 1:
        start_run_logging(log_specs, process_name, run)
        manager._configure_cross_detection_scheduler()
        manager._cached_detection_agents = None
        if manager.manager_id == 0 and manager.message_tx is not None:
            try:
                manager.message_tx.put({"kind": "run_start", "run": int(run)})
            except Exception as exc:
                logger.warning("Failed to notify message server about run %s: %s", run, exc)
        if manager.manager_id == 0 and manager.detection_tx is not None:
            try:
                manager.detection_tx.put({"kind": "run_start", "run": int(run)})
            except Exception as exc:
                logger.warning("Failed to notify detection server about run %s: %s", run, exc)
        try:
            metadata_cache = manager.get_agent_metadata()
            reset = False

            data_in = manager._blocking_get(arena_queue)
            while data_in is not None:
                if _is_shutdown_status(data_in):
                    shutdown_requested = True
                    break
                status = data_in.get("status")
                if isinstance(status, list) and len(status) >= 1 and status[0] == 0:
                    break
                data_in = manager._blocking_get(arena_queue)
            if data_in is None or shutdown_requested:
                break

            # Initialisation at start of run.
            if _is_shutdown_status(data_in):
                shutdown_requested = True
                break
            if "objects" not in data_in:
                shutdown_requested = True
                break
            if data_in["status"][0] == 0:
                manager.initialize(data_in["random_seed"], data_in["objects"])

            if manager._message_proxy is not None:
                all_entities = []
                for _, (_, entities) in manager.agents.items():
                    all_entities.extend(entities)
                manager._message_proxy.reset_mailboxes()
                manager._message_proxy.sync_agents(all_entities)
            if manager._detection_proxy is not None:
                all_entities = []
                for _, (_, entities) in manager.agents.items():
                    all_entities.extend(entities)
                manager._detection_proxy.sync_agents(all_entities)

            # First snapshot for GUI (before t=1).
            initial_snapshot = {
                "status": [0, ticks_per_second],
                "agents_shapes": manager.get_agent_shapes(),
                "agents_spins": manager.get_agent_spins(),
                "agents_metadata": metadata_cache,
            }
            agents_queue.put(initial_snapshot)

            t = 1
            while True:
                if ticks_limit > 0 and t >= ticks_limit:
                    break
                if data_in["status"] == "reset":
                    reset = True
                    break
                if _is_shutdown_status(data_in):
                    shutdown_requested = True
                    break

                # Keep arena and agents roughly in sync in simulated time.
                while data_in["status"][0] / data_in["status"][1] < t / ticks_per_second:
                    new_msg = manager._maybe_get(arena_queue, timeout=0.01)
                    if new_msg is not None:
                        data_in = new_msg
                        if data_in["status"] == "reset":
                            reset = True
                            break
                        if _is_shutdown_status(data_in):
                            shutdown_requested = True
                            break
                        if "objects" not in data_in:
                            shutdown_requested = True
                            break
                    else:
                        time.sleep(0.00005)
                    debug_wait_cycles += 1
                    if debug_wait_cycles % 500 == 0:
                        try:
                            backlog = arena_queue.qsize()
                        except Exception:
                            backlog = "n/a"
                        logger.debug(
                            "[MGR WAIT] mgr=%s run=%s t=%s arena_status=%s backlog=%s shutdown=%s",
                            manager.manager_id,
                            run,
                            t,
                            data_in.get("status"),
                            backlog,
                            shutdown_requested,
                        )

                    # Optional GUI update while waiting (only if queue is empty).
                    sync_payload = {
                        "status": [t, ticks_per_second],
                        "agents_shapes": manager.get_agent_shapes(),
                        "agents_spins": manager.get_agent_spins(),
                    }
                    if agents_queue.qsize() == 0:
                        agents_queue.put(sync_payload)
                if reset:
                    break
                if shutdown_requested:
                    break

                latest = manager._maybe_get(arena_queue, timeout=0.0)
                if latest is not None:
                    data_in = latest
                    if _is_shutdown_status(data_in):
                        shutdown_requested = True
                        break
                    if "objects" not in data_in:
                        shutdown_requested = True
                        break
                if shutdown_requested:
                    break

                agents_snapshot = manager._gather_detection_agents(t)

                # Synchronize message proxy with updated agent positions.
                if manager._message_proxy is not None:
                    all_entities = []
                    for _, (_, entities) in manager.agents.items():
                        all_entities.extend(entities)
                    manager._message_proxy.sync_agents(all_entities)
                if manager._detection_proxy is not None:
                    all_entities = []
                    for _, (_, entities) in manager.agents.items():
                        all_entities.extend(entities)
                    manager._detection_proxy.sync_agents(all_entities)

                # Messaging: send then receive, then main agent step.
                for _, entities in manager.agents.values():
                    for entity in entities:
                        if getattr(entity, "msg_enable", False) and entity.message_bus:
                            entity.send_message(t)

                for _, entities in manager.agents.values():
                    for entity in entities:
                        if getattr(entity, "msg_enable", False) and entity.message_bus:
                            entity.receive_messages(t)
                        if shutdown_requested:
                            break
                        if "objects" not in data_in:
                            shutdown_requested = True
                            break
                        entity.run(t, manager.arena_shape, data_in["objects"], agents_snapshot)
                    if agent_barrier is not None:
                        agent_barrier.wait()

                # Collision detector snapshot and corrections.
                dec_data_in: dict[str, Any] = {}

                if manager.collisions and dec_agents_in is not None and dec_agents_out is not None:
                    if t % manager.snapshot_stride == 0:
                        detector_data = {"manager_id": manager.manager_id, "agents": manager.pack_detector_data()}
                        try:
                            dec_agents_in.put(detector_data)
                        except Exception:
                            pass

                        dec_data_candidate = manager._blocking_get(dec_agents_out)
                        dec_data_in = dec_data_candidate if isinstance(dec_data_candidate, dict) else {}

                # Apply collision corrections (or call post_step(None) if none).
                for _, entities in manager.agents.values():
                    if not entities:
                        continue
                    group_key = entities[0].entity()
                    group_corr = dec_data_in.get(group_key, None)  # list of corrections or None

                    if isinstance(group_corr, list):
                        for idx, entity in enumerate(entities):
                            corr_vec = group_corr[idx] if idx < len(group_corr) else None
                            entity.post_step(corr_vec)
                            manager._apply_wrap(entity)
                            manager._clamp_to_arena(entity)
                    else:
                        for entity in entities:
                            entity.post_step(None)
                            manager._apply_wrap(entity)
                            manager._clamp_to_arena(entity)
                    if agent_barrier is not None:
                        agent_barrier.wait()

                # GUI snapshot AFTER collision corrections.
                if shutdown_requested:
                    break

                agents_data = {
                    "status": [t, ticks_per_second],
                    "agents_shapes": manager.get_agent_shapes(),
                    "agents_spins": manager.get_agent_spins(),
                }
                # Always include up-to-date per-agent metadata so data handlers
                # can access per-agent `snapshot_metrics` (e.g., heading).
                try:
                    metadata_snapshot = manager.get_agent_metadata()
                    metadata_cache = metadata_snapshot
                    agents_data["agents_metadata"] = metadata_snapshot
                except Exception:
                    if metadata_cache is not None:
                        agents_data["agents_metadata"] = metadata_cache

                agents_queue.put(agents_data)
                t += 1

            if t < ticks_limit and not reset:
                break
            if shutdown_requested:
                break

            if run < num_runs:
                drained = manager._maybe_get(arena_queue, timeout=0.01)
                while drained is not None:
                    data_in = drained
                    drained = manager._maybe_get(arena_queue, timeout=0.0)
            elif not reset:
                manager.close()

            if not reset:
                run += 1
            if shutdown_requested:
                break

        finally:
            shutdown_logging()
    logger.info("EntityManager completed all runs")
