# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Entity factory helper to create agents/objects by type."""

from __future__ import annotations

from core.entities.agents import MovableAgent, StaticAgent
from core.entities.objects import MovableObject, StaticObject
from core.util.logging_util import get_logger

logger = get_logger("entity")


class EntityFactory:
    """Entity factory."""

    @staticmethod
    def create_entity(entity_type: str, config_elem: dict, _id: int = 0):
        """Create entity from type string."""
        check_type = entity_type.split("_")[0] + "_" + entity_type.split("_")[1]
        if check_type == "agent_static":
            entity = StaticAgent(entity_type, config_elem, _id)
        elif check_type == "agent_movable":
            entity = MovableAgent(entity_type, config_elem, _id)
        elif check_type == "object_static":
            entity = StaticObject(entity_type, config_elem, _id)
        elif check_type == "object_movable":
            entity = MovableObject(entity_type, config_elem, _id)
        else:
            raise ValueError(f"Invalid agent type: {entity_type}")
        logger.info("Created entity %s (id=%s)", entity.get_name(), _id)
        return entity
