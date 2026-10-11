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

import queue, time
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
        # Uploads sent so far / latest upload already merged in the snapshot we hold.
        self._seq = 0
        self._acked_seq = 0
        self._sync_warned = False

    def sync_agents(self, agents: Iterable[Any]) -> None:
        """
        Refresh internal agent registry and send a snapshot to the detection server.
        """
        self._agents = list(agents)
        self._send_agents_snapshot()
        self._drain_from_server()

    def get_snapshot(self, wait_timeout: float = 0.0) -> Optional[List[Dict[str, Any]]]:
        """
        Return the latest merged detection snapshot, if available.

        With `wait_timeout` > 0 the call waits until the server has merged our
        last upload, so every manager perceives the same, current world state.
        """
        self._drain_from_server()
        deadline = time.monotonic() + wait_timeout
        while self._acked_seq < self._seq:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if wait_timeout > 0 and not self._sync_warned:
                    self._sync_warned = True
                    logger.warning(
                        "[DP %d] detection server did not answer within %.1fs; using the last snapshot",
                        self._manager_id,
                        wait_timeout,
                    )
                break
            self._drain_from_server(wait=remaining)
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
            "seq": self._seq + 1,
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
            self._seq += 1
        except Exception as exc:
            logger.warning("Failed to send detection snapshot to server: %s", exc)

    def _drain_from_server(self, wait: float = 0.0) -> None:
        """Pull pending snapshots from the detection server (blocking up to `wait` for the first)."""
        if self._rx is None:
            return

        while True:
            try:
                packet = self._rx.get(timeout=wait) if wait > 0 else self._rx.get_nowait()
                wait = 0.0
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
                self._acked_seq = max(self._acked_seq, int(packet.get("ack", 0)))
