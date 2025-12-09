# ------------------------------------------------------------------------------
#  CollectiPy
# ------------------------------------------------------------------------------

"""Unicycle kinematic model."""

import math
from core.util.geometry_utils.vector3D import Vector3D
from models.utility_functions import normalize_angle
from core.configuration.plugin_base import MotionModel
from core.configuration.plugin_registry import register_motion_model


class UnicycleMotionModel(MotionModel):
    """Integrate a standard unicycle model (x, y, yaw)."""

    def __init__(self, agent):
        self.agent = agent

    def step(self, agent, tick: int) -> None:
        """Integrate the velocity commands over a single tick."""
        linear_cmd = float(getattr(agent, "linear_velocity_cmd", 0.0))
        angular_cmd = float(getattr(agent, "angular_velocity_cmd", 0.0))
        prev_orientation = agent.orientation
        new_heading = normalize_angle(prev_orientation.z + angular_cmd)
        delta_orientation = Vector3D(0, 0, angular_cmd)
        angle_rad = math.radians(new_heading)
        dx = linear_cmd * math.cos(angle_rad)
        dy = -linear_cmd * math.sin(angle_rad)
        translation = Vector3D(dx, dy, 0)
        agent.delta_orientation = delta_orientation
        agent.forward_vector = translation
        agent.orientation = Vector3D(prev_orientation.x, prev_orientation.y, new_heading)
        agent.position = agent.position + translation


register_motion_model("unicycle", lambda agent: UnicycleMotionModel(agent))
