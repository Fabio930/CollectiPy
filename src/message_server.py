# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Central message server for agent communication."""

from __future__ import annotations

import logging
import queue
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from geometry_utils.vector3D import Vector3D
from geometry_utils.spatialgrid import SpatialGrid
from logging_utils import get_logger,configure_logging

logger = get_logger("message_server")


class _GridAgent:
    """Light wrapper used by the SpatialGrid."""

    __slots__ = ("name", "_pos")

    def __init__(self, name: str, pos: Vector3D) -> None:
        """Initialize the instance."""
        self.name = name
        self._pos = pos

    def get_position(self) -> Vector3D:
        """Return the agent position."""
        return self._pos


class _AgentInfo:
    """Internal snapshot of an agent used for routing."""

    __slots__ = (
        "name",
        "manager_id",
        "pos",
        "comm_range",
        "hierarchy_node",
        "allowed_nodes",
        "msg_type",
        "msg_kind"
    )

    def __init__(
        self,
        name: str,
        manager_id: int,
        pos: Vector3D,
        comm_range: float,
        hierarchy_node: Optional[str],
        allowed_nodes: Optional[Sequence[str]],
        msg_type: Optional[str],
        msg_kind: Optional[str]
    ) -> None:
        """Initialize the instance."""
        self.name = name
        self.manager_id = int(manager_id)
        self.pos = pos
        self.comm_range = float(comm_range)
        self.hierarchy_node = hierarchy_node
        self.allowed_nodes = set(allowed_nodes) if allowed_nodes else None
        self.msg_type = msg_type
        self.msg_kind = msg_kind


class MessageServer:
    """Core routing logic for the message server process."""

    def __init__(
        self,
        channels: Sequence[Tuple[Any, Any]],
        specs,
        fully_connected: bool = False,
        cell_size: float = 1.0
    ):
        """
        Initialize the instance.

        :param channels: list of ``(uplink, downlink)`` pairs, one per manager.
        :param fully_connected: if True, the network is fully connected and
                                SpatialGrid is not used for range filtering.
        :param cell_size: SpatialGrid cell size when ``fully_connected`` is False.
        """
        configure_logging(
            settings = specs[0],
            config_path = specs[1],
            project_root = specs[2],
        )
        self.channels = list(channels)
        self.fully_connected = bool(fully_connected)

        self._agents: Dict[str, _AgentInfo] = {}
        self._grid = SpatialGrid(cell_size)

        self._running = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Request a graceful shutdown."""
        self._running = False

    def run(self) -> None:
        """Main server loop."""
        logger.info(
            "Message server started with %d manager channels (fully_connected=%s)",
            len(self.channels),
            self.fully_connected
        )
        while self._running:
            any_packet = False
            for manager_id, (uplink, _) in enumerate(self.channels):
                processed = self._process_uplink(manager_id, uplink)
                any_packet = any_packet or processed

            if not any_packet:
                # Avoid busy waiting.
                time.sleep(0.001)

        logger.info("Message server shutting down")
        self._grid.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _process_uplink(self, manager_id: int, uplink: Any) -> bool:
        """Drain packets from a single manager uplink."""
        processed_any = False
        while True:
            try:
                packet = uplink.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break

            if not isinstance(packet, dict):
                continue

            kind = packet.get("kind")
            if kind == "shutdown":
                self.stop()
                processed_any = True
                continue
            if kind == "agents_snapshot":
                self._handle_agents_snapshot(packet)
                processed_any = True
            elif kind == "tx":
                self._handle_tx(packet)
                processed_any = True
        return processed_any

    def _handle_agents_snapshot(self, packet: Dict[str, Any]) -> None:
        """Update agent registry from a snapshot packet."""
        agents = packet.get("agents") or []
        manager_id = int(packet.get("manager_id", 0))

        logger.debug(
            "[MS] snapshot from manager %d: %d agents: %s",
            manager_id,
            len(agents),
            [str(a.get("uid")) for a in agents],
        )
        # Update internal registry.
        for info in agents:
            name = str(info.get("uid"))
            if not name:
                continue

            x = float(info.get("x", 0.0))
            y = float(info.get("y", 0.0))
            pos = Vector3D(x, y, 0.0)

            comm_range = float(info.get("range", 0.0))
            node = info.get("node")
            allowed_nodes = info.get("allowed_nodes")
            msg_type = info.get("msg_type")
            msg_kind = info.get("msg_kind")

            self._agents[name] = _AgentInfo(
                name,
                manager_id,
                pos,
                comm_range,
                node,
                allowed_nodes,
                msg_type,
                msg_kind
            )

        # Rebuild spatial index if we are not fully connected.
        if not self.fully_connected:
            self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        """Populate the SpatialGrid with the current agents."""
        self._grid.clear()
        for info in self._agents.values():
            self._grid.insert(_GridAgent(info.name, info.pos))

    def _handle_tx(self, packet: dict[str, Any]) -> None:
        """Route a TX packet to all compatible receivers."""
        sender_uid = str(packet.get("sender_uid"))
        payload = packet.get("payload")
        if not sender_uid or payload is None:
            return

        sender_info = self._agents.get(sender_uid)
        if sender_info is None:
            logger.debug("[MS] TX from %s ignored: sender not in registry", sender_uid)
            return


        # Se la rete è fully connected → tutti tranne il mittente
        if self.fully_connected:
            candidates = [
                info
                for name, info in self._agents.items()
                if name != sender_uid
            ]
        else:
            # Usiamo il wrapper _GridAgent per parlare col SpatialGrid
            grid_agent = _GridAgent(sender_info.name, sender_info.pos)
            candidates: list[_AgentInfo] = []

            # neighbors() restituisce _GridAgent (con .name e get_position)
            for neighbor in self._grid.neighbors(grid_agent, sender_info.comm_range):
                # Per sicurezza saltiamo il mittente
                if neighbor.name == sender_uid:
                    continue
                info = self._agents.get(neighbor.name)
                if info is not None:
                    candidates.append(info)

        logger.debug(
            "[MS] TX from %s (mgr %d) candidates: %s",
            sender_uid,
            sender_info.manager_id,
            [(c.name, c.manager_id) for c in candidates],
        )
        # Loop finale: filtro gerarchico + consegna
        for target in candidates:
            # (opzionale, ma sicuro) salta self e snapshot incompleti
            if target is sender_info:
                continue
            if target.pos is None:
                continue

            # SOLO filtro gerarchico simulator-level (se usi overlay)
            if not self._hierarchy_compatible(sender_info, target):
                continue
            
            logger.debug(
                "[MS] delivering to %s (mgr %d)",
                target.name,
                target.manager_id,
            )
            # Consegna al target
            self._deliver_to_target(target, payload)



    def _deliver_to_target(self, target: _AgentInfo, payload: Dict[str, Any]) -> None:
        """Send a message to a single target agent."""
        try:
            _, downlink = self.channels[target.manager_id]
        except IndexError:
            logger.warning("Invalid manager_id %s for agent %s", target.manager_id, target.name)
            return

        packet = {
            "kind": "rx",
            "receiver_uid": target.name,
            "payload": dict(payload)
        }
        try:
            logger.debug("[MS] RX packet enqueued for %s -> mgr %d", target.name, target.manager_id)
            downlink.put(packet)
        except Exception as exc:
            logger.warning("Failed to deliver message to target %s: %s", target.name, exc)

    @staticmethod
    def _protocols_compatible(
        msg_type: str | None,
        msg_kind: str | None,
        sender: _AgentInfo,
        target: _AgentInfo,
    ) -> bool:
        """Return True if sender and target are allowed to communicate by protocol."""
        sender_type = (msg_type or sender.msg_type or "").lower()
        target_type = (target.msg_type or "").lower()
        sender_kind = (msg_kind or sender.msg_kind or "").lower()
        target_kind = (target.msg_kind or "").lower()

        # Default: both missing info → allowed
        if not sender_type and not target_type:
            return True

        # Separate domains: handshake vs broadcast/rebroadcast
        handshake_sender = sender_type == "hand_shake"
        handshake_target = target_type == "hand_shake"
        if handshake_sender != handshake_target:
            return False

        # Anonymous vs id_aware
        # If one or both are unspecified, assume compatible.
        if sender_kind and target_kind and sender_kind != target_kind:
            return False

        return True
    
    def _hierarchy_compatible(self, sender: _AgentInfo, target: _AgentInfo) -> bool:
        """
        Return True if hierarchy/overlay-based restrictions allow communication.

        We rely on per-agent allowed_nodes sets computed on the Entity side
        using the hierarchy overlay + information_scope:
        - sender.allowed_nodes: nodes that the sender is allowed to talk across
        - target.allowed_nodes: nodes that the target is allowed to accept from

        Policy:
        - if neither agent defines allowed_nodes -> no restriction
        - if only one defines allowed_nodes    -> no restriction (one-sided policy)
        - if both define allowed_nodes         -> intersection must be non-empty
        """
        s = sender.allowed_nodes
        t = target.allowed_nodes
        if not s and not t:
            # No hierarchy restrictions provided.
            return True
        if not s or not t:
            # Only one side restricts itself; treat as unilateral filtering done
            # inside the agent logic (e.g. discarding messages), not here.
            return True

        # Both sides provide allowed_nodes: require non-empty intersection.
        if s.intersection(t):
            return True

        return False


def run_message_server(channels: Iterable[Tuple[Any, Any]], specs,fully_connected: bool = False, cell_size: float = 1.0) -> None:
    """
    Convenience function used as a multiprocessing target.

    :param channels: iterable of (uplink, downlink) queues, one per EntityManager.
    :param fully_connected: True to skip spatial filtering (typical for abstract arenas).
    :param cell_size: SpatialGrid cell size for non-abstract arenas.
    """
    server = MessageServer(list(channels), specs, fully_connected=fully_connected, cell_size=cell_size)
    server.run()
