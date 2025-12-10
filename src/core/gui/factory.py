# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""GUI factory helpers."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QApplication

from core.gui.gui_2d import GUI_2D
from core.util.logging_util import get_logger


logger = get_logger("gui.factory")


class GuiFactory:
    """Factory that instantiates the configured GUI implementation."""

    @staticmethod
    def create_gui(
        config_elem: Any,
        arena_vertices: list,
        arena_color: str,
        gui_in_queue,
        gui_control_queue,
        wrap_config=None,
        hierarchy_overlay=None,
        log_context=None,
    ):
        """Create the GUI matching the requested `_id`."""
        gui_id = config_elem.get("_id")
        logger.info("Creating GUI type %s", gui_id or "<none>")
        if gui_id in ("2D", "abstract"):
            return QApplication([]), GUI_2D(
                config_elem,
                arena_vertices,
                arena_color,
                gui_in_queue,
                gui_control_queue,
                wrap_config=wrap_config,
                hierarchy_overlay=hierarchy_overlay,
                log_context=log_context,
            )
        msg = f"Invalid gui type: {gui_id} valid types are '2D' or 'abstract'"
        raise ValueError(msg)
