# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Arena factory."""
from __future__ import annotations

from core.configuration.config import Config
from core.util.logging_util import get_logger
from core.main.arena.shapes import (
    AbstractArena,
    CircularArena,
    RectangularArena,
    SquareArena,
    UnboundedArena,
)


class ArenaFactory:
    """Arena factory."""

    _LOGGER = get_logger("arena.factory")

    @staticmethod
    def create_arena(config_elem: Config):
        """Create arena."""
        arena_id = config_elem.arena.get("_id")
        ArenaFactory._LOGGER.info("Creating arena type %s", arena_id or "<none>")
        if config_elem.arena.get("_id") in ("abstract", "none", None):
            return AbstractArena(config_elem)
        if config_elem.arena.get("_id") == "circle":
            return CircularArena(config_elem)
        if config_elem.arena.get("_id") == "rectangle":
            return RectangularArena(config_elem)
        if config_elem.arena.get("_id") == "square":
            return SquareArena(config_elem)
        if config_elem.arena.get("_id") == "unbounded":
            return UnboundedArena(config_elem)
        msg = f"Invalid shape type: {config_elem.arena['_id']} valid types are: none, abstract, circle, rectangle, square, unbounded"
        raise ValueError(msg)
