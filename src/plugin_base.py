# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""
Core plugin base classes used by the simulator.

This module introduces a minimal plugin API so that behaviours such as
agent movement and arena logic can be extended from external modules
without modifying the core code.

The aim is to keep backward compatibility with the original project:
if no plugins are configured, the simulator behaves exactly as before.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, Sequence
import numpy as np

class MovementModel(Protocol):
    """
    Interface for movement models used by agents.

    A movement model is responsible for updating the state of a single
    agent during a simulation tick. Implementations are free to use
    any logic; they typically call existing methods on the agent.
    """
    def step(self, agent: Any, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Advance `agent` by one tick."""

class LogicModel(Protocol):
    """
    Interface for optional logic models executed before movement.

    Logic models can update agent internal state (state machines,
    perception buffers, decision making, etc.) prior to movement.
    """
    def step(self, agent: Any, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Update agent's internal logic for the current tick."""

class DetectionModel(Protocol):
    """
    Interface for perception/detection components.

    Detection plugins convert world state into a perception vector
    that can be consumed by other models (e.g., movement models).
    """
    def sense(
        self,
        agent: Any,
        objects: dict,
        agents: dict,
        arena_shape = None
    ) -> Mapping[str, np.ndarray] | np.ndarray:
        """Return the perception produced for `agent`."""

class MessageBusModel(Protocol):
    """
    Interface for message-bus implementations.

    Buses coordinate message routing among a fixed set of agents and can
    decide how to deliver payloads (spatial neighbours, global broadcast,
    custom logic, etc.).
    """
    def reset_mailboxes(self) -> None:
        """Clear all pending messages."""

    def sync_agents(self, agents: Iterable[Any]) -> None:
        """
        Update internal state based on the current world snapshot.

        Implementations use this hook to rebuild spatial indices or any
        other acceleration structure before routing messages.
        """

    def send_message(self, sender: Any, msg: dict) -> None:
        """Deliver a message produced by `sender`."""

    def receive_messages(self, receiver: Any, limit: int | None = None) -> Sequence[dict]:
        """Return up to `limit` messages queued for `receiver`."""

    def close(self) -> None:
        """Release any resources retained by the bus."""

class PluginBase:
    """
    Base class for more complex plugins (if needed in the future).
    Currently kept minimal to not interfere with the original design.
    """
    def __init__(self, name: str = "", version: str = "0.0") -> None:
        """Initialize the instance."""
        self.name = name
        self.version = version

    def setup(self, config: dict | None = None) -> None:
        """Optional configuration hook."""
        self.config = config or {}


class MotionModel(Protocol):
    """
    Interface for kinematic motion models.

    These models take the motion commands prepared by the movement plugins
    (linear/rotational velocities) and integrate them to update the agent's
    pose. Implementations can represent different vehicle dynamics (unicycle,
    bicycle, Ackermann steering, etc.).
    """

    def step(self, agent: Any, tick: int) -> None:
        """Integrate the motion for ``agent`` over one simulation tick."""
