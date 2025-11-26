# ------------------------------------------------------------------------------
#  CollectiPy
#  Message Proxy (EntityManager-side) for Distributed Server
#  Copyright (c) 2025 Fabio
# ------------------------------------------------------------------------------

"""
MessageProxy:
- Lives inside each EntityManager process
- Acts as a bridge between local agents and the distributed message server
- Handles:
    * sync of agent snapshot (pos, range, hierarchy_node)
    * send_message → push to server
    * receive_messages → pull from server
- Does NOT implement message lifetime, handshake logic, or rebroadcast logic.
"""

from __future__ import annotations
import multiprocessing as mp
from typing import Dict
import logging

logger = logging.getLogger("sim.message_proxy")


class MessageProxy:
    def __init__(self, in_q: mp.Queue, out_q: mp.Queue):
        self._in = in_q
        self._out = out_q

    # ----------------------------------------------------------
    # SYNC: Called by EntityManager periodically
    # agents: list[Entity]
    # ----------------------------------------------------------
    def sync_agents(self, agents):
        snapshot = {}
        for ag in agents:
            if not getattr(ag, "msg_enable", False):
                continue
            pos = ag.get_position()
            snapshot[ag.get_name()] = (
                pos.x,
                pos.y,
                getattr(ag, "msg_comm_range", 0.0),
                getattr(ag, "hierarchy_node", None),
            )

        self._in.put({"op": "sync", "snapshot": snapshot})

    # ----------------------------------------------------------
    # SEND
    # Called by Agent.send_message()
    # ----------------------------------------------------------
    def send_message(self, agent, payload: dict):
        self._in.put({
            "op": "send",
            "sender": agent.get_name(),
            "payload": payload,
            "msg_type": getattr(agent, "msg_type", "broadcast"),
            "msg_kind": getattr(agent, "msg_kind", "anonymous"),
        })

    # ----------------------------------------------------------
    # RECEIVE
    # EntityManager asks batches for its agents
    # ----------------------------------------------------------
    def receive_messages(self, agent, limit: int):
        name = agent.get_name()
        self._in.put({
            "op": "recv",
            "name": name,
            "limit": limit,
        })

        resp = self._out.get()
        return resp.get("messages", [])
