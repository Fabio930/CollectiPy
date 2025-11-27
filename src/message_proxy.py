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

import queue
from typing import Any, Dict, Iterable, List, Optional, Sequence


from logging_utils import get_logger

logger = get_logger("message_proxy")


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

    The proxy maintains per-entity inboxes in this process. Higher-level
    protocol logic and message lifetime are handled by the Entity itself.
    """

    def __init__(self, agents: Iterable[Any], message_tx: Any, message_rx: Any, manager_id: int = 0):
        """Initialize the instance."""
        self._agents: List[Any] = list(agents)
        self._uid_to_agent: Dict[str, Any] = {}
        self._inboxes: Dict[str, List[Dict[str, Any]]] = {}

        self._tx = message_tx
        self._rx = message_rx
        self._manager_id = int(manager_id)

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
        Refresh internal agent registry and send a snapshot to the server.
        """
        self._agents = list(agents)
        self._update_agent_index()
        self._send_agents_snapshot()

    def send_message(self, sender: Any, msg: Dict[str, Any]) -> None:
        """Forward a message from *sender* to the message server."""
        if self._tx is None:
            return

        sender_uid = _safe_entity_uid(sender)
        payload = dict(msg or {})
        payload.setdefault("_sender_uid", sender_uid)

        msg_type = getattr(sender, "msg_type", None)
        msg_kind = getattr(sender, "msg_kind", None)

        packet = {
            "kind": "tx",
            "manager_id": self._manager_id,
            "sender_uid": sender_uid,
            "msg_type": msg_type,
            "msg_kind": msg_kind,
            "payload": payload
        }
        try:
            logger.debug("[MP %d] TX from %s to server: %s", self._manager_id, sender_uid, payload)
            self._tx.put(packet)
        except Exception as exc:
            logger.warning("Failed to send message to server: %s", exc)

    def receive_messages(self, receiver: Any, limit: Optional[int] = None) -> Sequence[Dict[str, Any]]:
        """
        Pull all pending packets from the server into local inboxes,
        then return messages for *receiver*.
        """
        self._drain_from_server()
        uid = _safe_entity_uid(receiver)
        inbox = self._inboxes.get(uid)
        if not inbox:
            return ()
        if limit is not None and limit >= 0:
            selected = inbox[:limit]
            del inbox[:limit]
        else:
            selected = list(inbox)
            inbox.clear()
        return selected

    def close(self) -> None:
        """Release any resources retained by the proxy."""
        return

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _update_agent_index(self) -> None:
        """Rebuild internal UID→agent and inbox mappings."""
        self._uid_to_agent.clear()
        old_inboxes = self._inboxes
        self._inboxes = {}
        for agent in self._agents:
            uid = _safe_entity_uid(agent)
            self._uid_to_agent[uid] = agent
            self._inboxes[uid] = old_inboxes.get(uid, [])

    def _get_inbox(self, uid: str) -> List[Dict[str, Any]]:
        """Return the inbox list associated with *uid*, creating it if needed."""
        inbox = self._inboxes.get(uid)
        if inbox is None:
            inbox = []
            self._inboxes[uid] = inbox
        return inbox

    def _send_agents_snapshot(self) -> None:
        """Send a lightweight snapshot of all local agents to the server."""
        if self._tx is None:
            return

        snapshot: List[Dict[str, Any]] = []
        for agent in self._agents:
            uid = _safe_entity_uid(agent)

            # Position: expected get_position().x / .y; fall back to (0,0).
            try:
                pos = agent.get_position()
                x = float(getattr(pos, "x", 0.0))
                y = float(getattr(pos, "y", 0.0))
            except Exception:
                x = 0.0
                y = 0.0

            # Communication range: optional attribute.
            comm_range = float(getattr(agent, "msg_comm_range", 0.1))

            # Hierarchy / overlay-related fields, optional.
            node = getattr(agent, "hierarchy_node", None)
            allowed_nodes = getattr(agent, "allowed_nodes", None)
            msg_type = getattr(agent, "msg_type", None)
            msg_kind = getattr(agent, "msg_kind", None)

            snapshot.append(
                {
                    "uid": uid,
                    "manager_id": self._manager_id,
                    "x": x,
                    "y": y,
                    "range": comm_range,
                    "node": node,
                    "allowed_nodes": list(allowed_nodes) if isinstance(allowed_nodes, (set, list, tuple)) else None,
                    "msg_type": msg_type,
                    "msg_kind": msg_kind
                }
            )

        packet = {
            "kind": "agents_snapshot",
            "manager_id": self._manager_id,
            "agents": snapshot
        }
        try:
            logger.debug(
                "[MP %d] sending snapshot with %d agents: %s",
                self._manager_id,
                len(snapshot),
                [a["uid"] for a in snapshot],
            )
            self._tx.put(packet)
        except Exception as exc:
            logger.warning("Failed to send agents snapshot to server: %s", exc)

    def _drain_from_server(self) -> None:
        """Move all pending packets from the server into local inboxes."""
        if self._rx is None:
            return

        while True:
            try:
                packet = self._rx.get_nowait()
            except queue.Empty:
                break
            except Exception as exc:
                logger.warning("Error while reading from message server: %s", exc)
                break

            if not isinstance(packet, dict):
                continue
            if packet.get("kind") != "rx":
                continue

            receiver_uid = packet.get("receiver_uid")
            payload = packet.get("payload")
            if receiver_uid is None or payload is None:
                continue
            
            logger.debug(
                "[MP %d] RX for %s: %s",
                self._manager_id,
                receiver_uid,
                payload,
            )
            inbox = self._get_inbox(str(receiver_uid))
            inbox.append(dict(payload))
