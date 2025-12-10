"""EntityManager components split across modules."""

from core.main.entity_manager.runtime import EntityManager  # noqa: F401
from core.main.entity_manager.initialize import initialize_entities  # noqa: F401
from core.main.entity_manager.loop import manager_run  # noqa: F401

__all__ = ["EntityManager", "initialize_entities", "manager_run"]
