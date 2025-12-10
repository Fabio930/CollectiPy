# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Process entrypoints for environment-managed subprocesses."""
from __future__ import annotations


def _run_arena_process(
    arena,
    num_runs,
    time_limit,
    arena_queue_list,
    agents_queue_list,
    gui_in_queue,
    dec_arena_in,
    gui_control_queue,
    render_enabled,
    log_specs,
    dec_control_queue,
):
    from core.util.logging_util import initialize_process_console_logging

    settings = log_specs.get("settings")
    cfg_path = log_specs.get("config_path")
    root = log_specs.get("project_root")
    initialize_process_console_logging(settings, cfg_path, root)
    arena.run(
        num_runs,
        time_limit,
        arena_queue_list,
        agents_queue_list,
        gui_in_queue,
        dec_arena_in,
        gui_control_queue,
        render_enabled,
        log_context={
            "log_specs": log_specs,
            "process_name": "arena",
        },
        dec_control_queue=dec_control_queue,
    )


def _run_manager_process(
    block_filtered,
    arena_shape,
    log_specs,
    wrap_config,
    hierarchy,
    snapshot_stride,
    manager_id,
    collisions,
    message_tx,
    message_rx,
    detection_tx,
    detection_rx,
    num_runs,
    time_limit,
    arena_queue,
    agents_queue,
    dec_agents_in,
    dec_agents_out,
    agent_barrier,
):
    from core.util.logging_util import initialize_process_console_logging

    settings = log_specs.get("settings")
    cfg_path = log_specs.get("config_path")
    root = log_specs.get("project_root")
    initialize_process_console_logging(settings, cfg_path, root)

    from core.main.entity_manager import EntityManager

    mgr = EntityManager(
        block_filtered,
        arena_shape,
        wrap_config=wrap_config,
        hierarchy=hierarchy,
        snapshot_stride=snapshot_stride,
        manager_id=manager_id,
        collisions=collisions,
        message_tx=message_tx,
        message_rx=message_rx,
        detection_tx=detection_tx,
        detection_rx=detection_rx,
    )
    mgr.run(
        num_runs,
        time_limit,
        arena_queue,
        agents_queue,
        dec_agents_in,
        dec_agents_out,
        agent_barrier,
        log_context={
            "log_specs": log_specs,
            "process_name": f"manager_{manager_id}",
        },
    )


def _run_collision_detector_process(collision_detector, det_in_arg, det_out_arg, dec_arena_in, log_specs, dec_control_queue):
    from core.util.logging_util import initialize_process_console_logging

    settings = log_specs.get("settings")
    cfg_path = log_specs.get("config_path")
    root = log_specs.get("project_root")
    initialize_process_console_logging(settings, cfg_path, root)
    collision_detector.run(
        det_in_arg,
        det_out_arg,
        dec_arena_in,
        dec_control_queue,
        log_context={
            "log_specs": log_specs,
            "process_name": "collision",
        },
    )


def _run_message_server(channels, log_specs, fully_connected):
    from core.util.logging_util import initialize_process_console_logging

    settings = log_specs.get("settings")
    cfg_path = log_specs.get("config_path")
    root = log_specs.get("project_root")
    initialize_process_console_logging(settings, cfg_path, root)
    from core.messaging.message_server import run_message_server

    run_message_server(channels, log_specs, fully_connected)


def _run_detection_server(channels, log_specs):
    from core.util.logging_util import initialize_process_console_logging

    settings = log_specs.get("settings")
    cfg_path = log_specs.get("config_path")
    root = log_specs.get("project_root")
    initialize_process_console_logging(settings, cfg_path, root)
    from core.detection.detection_server import run_detection_server

    run_detection_server(channels, log_specs)


def _run_gui_process(config, arena_vertices, arena_color, gui_in_queue, gui_control_queue, log_specs, wrap_config, hierarchy_overlay):
    from core.util.logging_util import initialize_process_console_logging, shutdown_logging

    settings = log_specs.get("settings")
    cfg_path = log_specs.get("config_path")
    root = log_specs.get("project_root")
    initialize_process_console_logging(settings, cfg_path, root)
    from core.gui import GuiFactory

    app, gui = GuiFactory.create_gui(
        config,
        arena_vertices,
        arena_color,
        gui_in_queue,
        gui_control_queue,
        wrap_config=wrap_config,
        hierarchy_overlay=hierarchy_overlay,
        log_context={
            "log_specs": log_specs,
            "process_name": "gui",
        },
    )
    gui.show()
    try:
        app.exec()
    finally:
        shutdown_logging()
