# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Message proxy used by EntityManager to communicate with the message server."""

from __future__ import annotations

import queue, time
from typing import Any, Dict, Iterable, List, Optional, Sequence
from core.util.logging_util import get_logger

logger = get_logger("message_proxy")

# Seconds a manager waits for the message server to route the current tick.
ROUND_TIMEOUT = 2.0


def _safe_entity_uid(entity: Any) -> str:
    """Return a stable UID for *entity* compatible with the existing code."""
    if hasattr(entity, "get_name"):
        try:
            return str(entity.get_name())
        except Exception:
            pass
    return "<entity:%d>" % id(entity)


class NullMessageProxy:
    """Proxy implementation that completely disables communication."""

    def __init__(self, agents: Iterable[Any] | None = None):
        """Initialize the instance."""
        self._agents: List[Any] = list(agents or [])

    def reset_mailboxes(self) -> None:
        """Clear all pending messages."""
        return

    def sync_agents(self, agents: Iterable[Any]) -> None:
        """Refresh internal list of agents (no-op for messaging)."""
        self._agents = list(agents)

    def send_message(self, sender: Any, msg: Dict[str, Any]) -> None:
        """Deliver a message produced by `sender` (no-op)."""
        return

    def exchange(self) -> None:
        """Publish/collect the transmissions of the current tick (no-op)."""
        return

    def receive_messages(self, receiver: Any, limit: Optional[int] = None) -> Sequence[Dict[str, Any]]:
        """Return messages queued for `receiver` (always empty)."""
        return ()

    def close(self) -> None:
        """Release any resources retained by the proxy."""
        return



class MessageProxy:
    """
    Proxy object that connects local entities to the central message server.

    The proxy relies on two IPC channels provided by the Environment /
    EntityManager:

        - message_tx: queue-like object used to send packets to the server;
        - message_rx: queue-like object used to receive packets from the server.

    The medium is transient: every tick the proxy publishes the positions and the
    transmissions of its agents in one packet (`exchange`), and gets back what each
    local agent can hear during that tick. Whatever is not picked up before the
    next exchange is lost. What an agent keeps of a received message, and for how
    long, is handled by the Entity itself.
    """

    def __init__(self, agents: Iterable[Any], message_tx: Any, message_rx: Any, manager_id: int = 0):
        """Initialize the instance."""
        self._agents: List[Any] = list(agents)
        self._inboxes: Dict[str, List[Dict[str, Any]]] = {}
        # Per-agent fields of the position snapshot that never change during a run.
        self._static_rows: List[Dict[str, Any]] = []

        self._tx = message_tx
        self._rx = message_rx
        self._manager_id = int(manager_id)
        # Staged for the next exchange: positions of the local agents and their transmissions.
        self._snapshot: List[Dict[str, Any]] = []
        self._outbox: List[Dict[str, Any]] = []
        self._seq = 0
        self._sync_warned = False

        if self._tx is None or self._rx is None:
            logger.warning(
                "MessageProxy created without valid IPC channels; "
                "communication will be disabled for this manager."
            )

        self._update_agent_index()

    # ------------------------------------------------------------------
    # Public API used by Entity / EntityManager
    # ------------------------------------------------------------------
    def reset_mailboxes(self) -> None:
        """Clear all pending messages."""
        for uid in self._inboxes:
            self._inboxes[uid].clear()

    def sync_agents(self, agents: Iterable[Any]) -> None:
        """
        Refresh internal agent registry and stage the positions for the next exchange.
        """
        agents = list(agents)
        if len(agents) != len(self._agents) or any(a is not b for a, b in zip(agents, self._agents)):
            self._agents = agents
            self._update_agent_index()
        self._snapshot = self._build_agents_snapshot()

    def send_message(self, sender: Any, msg: Dict[str, Any]) -> None:
        """Stage a message from *sender*; it goes on air at the next exchange."""
        if self._tx is None:
            return

        sender_uid = _safe_entity_uid(sender)
        payload = dict(msg or {})
        payload.setdefault("_sender_uid", sender_uid)
        self._outbox.append(
            {
                "sender_uid": sender_uid,
                "msg_type": getattr(sender, "msg_type", None),
                "msg_kind": getattr(sender, "msg_kind", None),
                "payload": payload,
            }
        )

    def exchange(self, wait_timeout: float = ROUND_TIMEOUT) -> None:
        """
        Put this tick's positions and transmissions on air and collect what the
        local agents can hear. Messages of the previous tick are gone by now.
        """
        self.reset_mailboxes()
        outbox, self._outbox = self._outbox, []
        if self._tx is None or self._rx is None:
            return
        self._seq += 1
        try:
            self._tx.put(
                {
                    "kind": "round",
                    "manager_id": self._manager_id,
                    "seq": self._seq,
                    "agents": self._snapshot,
                    "tx": outbox,
                }
            )
        except Exception as exc:
            logger.warning("Failed to reach the message server: %s", exc)
            return

        deadline = time.monotonic() + wait_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if not self._sync_warned:
                    self._sync_warned = True
                    logger.warning(
                        "[MP %d] message server did not answer within %.1fs; this tick's messages are lost",
                        self._manager_id,
                        wait_timeout,
                    )
                return
            try:
                packet = self._rx.get(timeout=remaining)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.warning("Error while reading from message server: %s", exc)
                return
            if not isinstance(packet, dict) or packet.get("kind") != "rx_round":
                continue
            if int(packet.get("ack", 0)) < self._seq:
                # Late answer to a round we stopped waiting for.
                continue
            for receiver_uid, payload in packet.get("rx", ()):
                inbox = self._inboxes.get(receiver_uid)
                if inbox is not None:
                    inbox.append(payload)
            return

    def receive_messages(self, receiver: Any, limit: Optional[int] = None) -> Sequence[Dict[str, Any]]:
        """
        Return the messages currently on air for *receiver* (at most `limit`).
        They are removed from the medium either way.
        """
        inbox = self._inboxes.get(_safe_entity_uid(receiver))
        if not inbox:
            return ()
        selected = list(inbox) if limit is None or limit < 0 else inbox[:limit]
        inbox.clear()
        return selected

    def close(self) -> None:
        """Release any resources retained by the proxy."""
        return


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _update_agent_index(self) -> None:
        """Rebuild the inboxes and the constant part of each agent's snapshot row."""
        old_inboxes = self._inboxes
        self._inboxes = {}
        self._static_rows = []
        for agent in self._agents:
            uid = _safe_entity_uid(agent)
            self._inboxes[uid] = old_inboxes.get(uid, [])

            # Hierarchy / overlay-related fields, optional.
            allowed_nodes = getattr(agent, "allowed_nodes", None)
            entity_val = getattr(agent, "entity", None)
            if callable(entity_val):
                try:
                    entity_val = entity_val()
                except Exception:
                    entity_val = None
            self._static_rows.append(
                {
                    "uid": uid,
                    "manager_id": self._manager_id,
                    "range": float(getattr(agent, "msg_comm_range", 0.1)),
                    "node": getattr(agent, "hierarchy_node", None),
                    "allowed_nodes": list(allowed_nodes) if isinstance(allowed_nodes, (set, list, tuple)) else None,
                    "msg_type": getattr(agent, "msg_type", None),
                    "msg_kind": getattr(agent, "msg_kind", None),
                    "entity": entity_val,
                }
            )

    def _build_agents_snapshot(self) -> List[Dict[str, Any]]:
        """Return a lightweight snapshot of all local agents for the server."""
        snapshot: List[Dict[str, Any]] = []
        for agent, static_row in zip(self._agents, self._static_rows):
            # Position: expected get_position().x / .y; fall back to (0,0).
            try:
                pos = agent.get_position()
                x = float(getattr(pos, "x", 0.0))
                y = float(getattr(pos, "y", 0.0))
                z = float(getattr(pos, "z", 0.0))
            except Exception:
                x = 0.0
                y = 0.0
                z = 0.0
            snapshot.append({**static_row, "x": x, "y": y, "z": z})
        return snapshot
