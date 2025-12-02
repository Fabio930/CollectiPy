# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import math
from plugin_base import MovementModel
from plugin_registry import register_movement_model
from models.movement.common import apply_motion_state
from models.utils import levy, wrapped_cauchy_pp
from logging_utils import get_logger

logger = get_logger("movement.random_walk")

class RandomWalkMovement(MovementModel):
    """Random walk movement."""
    def __init__(self, agent):
        """Initialize the instance."""
        self.agent = agent

    def step(self, agent, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Execute the simulation step."""
        self._update_motion_state(tick)
        apply_motion_state(self.agent)

    def _update_motion_state(self, tick: int) -> None:
        """Update motion state."""
        agent = self.agent
        if agent.motion in (agent.LEFT, agent.RIGHT, agent.STOP):
            if tick > agent.last_motion_tick + agent.turning_ticks:
                agent.last_motion_tick = tick
                agent.motion = agent.FORWARD
                agent.forward_ticks = abs(levy(agent.random_generator, agent.standard_motion_steps, agent.levy_exponent))
                logger.debug("%s begins forward motion for %s ticks", agent.get_name(), agent.forward_ticks)
        elif agent.motion == agent.FORWARD:
            if tick > agent.last_motion_tick + agent.forward_ticks:
                agent.last_motion_tick = tick
                p = agent.get_random_generator().uniform(0, 1)
                agent.motion = agent.LEFT if p < 0.5 else agent.RIGHT
                if agent.crw_exponent == 0:
                    angle = agent.get_random_generator().uniform(0, math.pi)
                else:
                    angle = abs(wrapped_cauchy_pp(agent.random_generator, agent.crw_exponent))
                agent.turning_ticks = int(angle * agent.max_turning_ticks)
                logger.debug("%s starts turning %s for %s ticks", agent.get_name(), agent.motion, agent.turning_ticks)

register_movement_model("random_walk", lambda agent: RandomWalkMovement(agent))
