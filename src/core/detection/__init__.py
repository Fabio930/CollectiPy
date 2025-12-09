"""
Detection aggregation and cross-process proxy helpers.
"""

from core.detection.detection_proxy import DetectionProxy
from core.detection.detection_server import DetectionServer, run_detection_server

__all__ = [
    "DetectionProxy",
    "DetectionServer",
    "run_detection_server",
]
