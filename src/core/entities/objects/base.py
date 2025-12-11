# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Base object entity."""

from __future__ import annotations

from core.entities.base import Entity


class Object(Entity):
    """Base object."""

    def __init__(self, entity_type: str, config_elem: dict, _id: int = 0):
        """Initialize the instance."""
        super().__init__(entity_type, config_elem, _id)
        if config_elem.get("_id") not in ("idle", "interactive"):
            raise ValueError(f"Invalid object type: {self.entity_type}")
