"""
Core package entrypoint, re-exporting the main simulation components.
"""

from core.collision import CollisionDetector
from core.detection import DetectionProxy, DetectionServer, run_detection_server
from core.messaging import MessageProxy, NullMessageProxy, MessageServer, run_message_server
from core.processes import ArenaFactory, EntityManager, Environment

__all__ = [
    "ArenaFactory",
    "CollisionDetector",
    "DetectionProxy",
    "DetectionServer",
    "EntityManager",
    "Environment",
    "MessageProxy",
    "MessageServer",
    "NullMessageProxy",
    "run_detection_server",
    "run_message_server",
]
