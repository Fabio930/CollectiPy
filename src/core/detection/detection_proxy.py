# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Detection proxy used by EntityManager to gather cross-process perception data."""

from __future__ import annotations

import queue
from typing import Any, Dict, Iterable, List, Optional
from core.util.logging_util import get_logger
from core.messaging.message_proxy import _safe_entity_uid

logger = get_logger("detection_proxy")


class DetectionProxy:
    """
    Proxy object that connects local entities to the detection server.

    Managers send lightweight snapshots of their agents; the detection server
    merges them and broadcasts the global list back to every manager.
    """

    def __init__(self, agents: Iterable[Any], detection_tx: Any, detection_rx: Any, manager_id: int = 0):
        """Initialize the instance."""
        self._agents: List[Any] = list(agents)
        self._tx = detection_tx
        self._rx = detection_rx
        self._manager_id = int(manager_id)
        self._snapshot: Optional[List[Dict[str, Any]]] = None

    def sync_agents(self, agents: Iterable[Any]) -> None:
        """
        Refresh internal agent registry and send a snapshot to the detection server.
        """
        self._agents = list(agents)
        self._send_agents_snapshot()
        self._drain_from_server()

    def get_snapshot(self) -> Optional[List[Dict[str, Any]]]:
        """Return the latest merged detection snapshot, if available."""
        self._drain_from_server()
        return self._snapshot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _send_agents_snapshot(self) -> None:
        """Send a lightweight snapshot of all local agents to the server."""
        if self._tx is None:
            return

        snapshot: List[Dict[str, Any]] = []
        for agent in self._agents:
            uid = _safe_entity_uid(agent)
            try:
                pos = agent.get_position()
                x = float(getattr(pos, "x", 0.0))
                y = float(getattr(pos, "y", 0.0))
                z = float(getattr(pos, "z", 0.0))
            except Exception:
                x = y = z = 0.0
            hierarchy_node = getattr(agent, "hierarchy_node", None)
            try:
                detection_range = float(agent.get_detection_range())
            except Exception:
                detection_range = float("inf")
            ent_attr = getattr(agent, "entity", None)
            if callable(ent_attr):
                try:
                    entity_val = ent_attr()
                except Exception:
                    entity_val = None
            else:
                entity_val = ent_attr
            snapshot.append(
                {
                    "uid": uid,
                    "manager_id": self._manager_id,
                    "entity": entity_val,
                    "x": x,
                    "y": y,
                    "z": z,
                    "hierarchy_node": hierarchy_node,
                    "detection_range": detection_range,
                }
            )

        packet = {
            "kind": "agents_snapshot",
            "manager_id": self._manager_id,
            "agents": snapshot
        }
        try:
            logger.debug(
                "[DP %d] sending snapshot with %d agents: %s",
                self._manager_id,
                len(snapshot),
                [a["uid"] for a in snapshot],
            )
            self._tx.put(packet)
        except Exception as exc:
            logger.warning("Failed to send detection snapshot to server: %s", exc)

    def _drain_from_server(self) -> None:
        """Pull pending snapshots from the detection server."""
        if self._rx is None:
            return

        while True:
            try:
                packet = self._rx.get_nowait()
            except queue.Empty:
                break
            except Exception as exc:
                logger.warning("Error while reading from detection server: %s", exc)
                break

            if not isinstance(packet, dict):
                continue
            if packet.get("kind") != "detection_snapshot":
                continue
            agents = packet.get("agents")
            if isinstance(agents, list):
                self._snapshot = agents
