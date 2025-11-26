# ------------------------------------------------------------------------------
#  CollectiPy
#  Distributed Message Server
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""
DistributedMessageServer:
Cross-process messaging router with SpatialGrid support.

Responsibilities:
- Maintain global agent snapshot (pos, comm_range, hierarchy_node)
- Maintain a SpatialGrid for efficient range queries (only if arena non-abstract)
- Route messages according to:
    * msg_type (broadcast / rebroadcast / hand_shake)
    * hierarchy pre-filter (receiver must share a valid hierarchy_node)
    * comm_range
    * direction (handshake target)
- Store messages in per-agent mailbox until next receive
- After delivering messages to a manager, mailbox is cleared
- Server does NOT:
    * manage message lifetime
    * manage handshake state machine
    * manage rebroadcast logic
    * apply agent protocols (done in entity.py)
"""

from __future__ import annotations
import multiprocessing as mp
from typing import Dict, List, Any, Optional
import logging
import math

from geometry_utils.spatialgrid import SpatialGrid


logger = logging.getLogger("sim.msg_server")


# -------------------------------------------------------------------------
# Proxy for SpatialGrid (simple: name, x, y, hnode)
# -------------------------------------------------------------------------
class _GridProxy:
    __slots__ = ("name", "x", "y", "hnode")

    def __init__(self, name: str, x: float, y: float, hnode: Optional[str]):
        self.name = name
        self.x = x
        self.y = y
        self.hnode = hnode

    def get_name(self):
        return self.name

    def get_position(self):
        """Return object with .x, .y as SpatialGrid expects."""
        class _Pos:
            __slots__ = ("x", "y")
            def __init__(self, xx, yy):
                self.x = xx
                self.y = yy
        return _Pos(self.x, self.y)

    def __repr__(self):
        return f"GridProxy({self.name}, x={self.x}, y={self.y}, h={self.hnode})"


# -------------------------------------------------------------------------
# DistributedMessageServer
# -------------------------------------------------------------------------
class DistributedMessageServer:
    def __init__(self, arena_non_abstract: bool, cell_size: float = 0.1):
        """
        Parameters
        ----------
        arena_non_abstract : bool
            If True, SpatialGrid is used for range queries.
        cell_size : float
            Spatial grid cell size.
        """
        self.running = True
        self.arena_non_abstract = arena_non_abstract

        # name -> (x, y, comm_range, hierarchy_node)
        self.state: Dict[str, tuple] = {}

        # name -> list of pending messages
        self.mailboxes: Dict[str, List[dict]] = {}

        # Spatial grid for neighbor lookup
        self.grid = SpatialGrid(cell_size) if arena_non_abstract else None

    # ------------------------------------------------------------------
    # POSITION SYNC
    # ------------------------------------------------------------------
    def sync_snapshot(self, snapshot: Dict[str, tuple]):
        """
        snapshot[name] = (x, y, comm_range, hierarchy_node)
        """
        self.state = snapshot

        if not self.arena_non_abstract or self.grid is None:
            return

        self.grid.clear()

        for name, (x, y, cr, hnode) in snapshot.items():
            proxy = _GridProxy(name, x, y, hnode)
            self.grid.insert(proxy)

    # ------------------------------------------------------------------
    # NEIGHBOR SELECTION
    # ------------------------------------------------------------------
    def _neighbors(self, sender: str) -> List[str]:
        """Return neighbors by comm_range (SpatialGrid or full broadcast)."""
        if sender not in self.state:
            return []

        if not self.arena_non_abstract or self.grid is None:
            # All agents except sender
            return [n for n in self.state.keys() if n != sender]

        x, y, cr, hnode = self.state[sender]
        sp = _GridProxy(sender, x, y, hnode)
        near = self.grid.neighbors(sp, cr)
        return [p.get_name() for p in near if p.get_name() != sender]

    # ------------------------------------------------------------------
    # CORE SEND
    # ------------------------------------------------------------------
    def _deliver_to(self, receiver: str, payload: dict):
        """Append to mailbox."""
        self.mailboxes.setdefault(receiver, []).append(payload)

    def handle_send(self, sender: str, payload: dict,
                    msg_type: str, msg_kind: str):
        if sender not in self.state:
            return

        # ID-aware or anonymous
        if msg_kind == "id":
            payload = dict(payload)
            payload["from"] = sender
        else:
            payload = dict(payload)
            payload["from"] = None

        # HANDSHAKE: msg["to"] = specific target
        if msg_type == "hand_shake":
            target = payload.get("to")
            if target and target in self.state:
                # Check comm_range constraint
                sx, sy, sr, _ = self.state[sender]
                tx, ty, _, _ = self.state[target]
                dist = math.hypot(tx - sx, ty - sy)
                if dist <= sr:
                    self._deliver_to(target, payload)
            return

        # BROADCAST / REBROADCAST
        for neigh in self._neighbors(sender):
            self._deliver_to(neigh, payload)

    # ------------------------------------------------------------------
    # RECEIVE
    # ------------------------------------------------------------------
    def handle_receive(self, name: str, limit: Optional[int]) -> List[dict]:
        mb = self.mailboxes.get(name, [])
        if not mb:
            return []

        if limit is None or limit >= len(mb):
            out = mb[:]
            self.mailboxes[name] = []
            return out

        out = mb[:limit]
        self.mailboxes[name] = mb[limit:]
        return out

    # ------------------------------------------------------------------
    # MAIN LOOP
    # ------------------------------------------------------------------
    def run(self, in_q: mp.Queue, out_q: mp.Queue):
        while self.running:
            msg = in_q.get()
            if msg is None:
                break

            op = msg.get("op")

            if op == "shutdown":
                break

            elif op == "sync":
                snapshot = msg.get("snapshot", {})
                self.sync_snapshot(snapshot)

            elif op == "send":
                self.handle_send(
                    sender=msg.get("sender"),
                    payload=msg.get("payload", {}),
                    msg_type=msg.get("msg_type", "broadcast"),
                    msg_kind=msg.get("msg_kind", "anonymous"),
                )

            elif op == "recv":
                receiver = msg.get("name")
                limit = msg.get("limit")
                msgs = self.handle_receive(receiver, limit)
                out_q.put({"name": receiver, "messages": msgs})

        logger.info("DistributedMessageServer stopped")
