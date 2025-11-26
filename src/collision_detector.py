# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Collision detection utilities (asynchronous, all-to-all)."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from bodies.shapes3D import Shape
from geometry_utils.vector3D import Vector3D
from geometry_utils.spatialgrid import SpatialGrid

logger = logging.getLogger("sim.collision")

# Tuple exchanged between EntityManager and CollisionDetector for each group.
AgentCollisionPayload = Tuple[
    List[Shape],        # shapes
    List[float],        # max velocities (currently unused in response)
    List[Vector3D],     # forward vectors
    List[Vector3D],     # positions
    List[str]           # agent names
]


class _GridItem:
    """Light wrapper used by the SpatialGrid."""

    __slots__ = ("index", "_pos", "radius")

    def __init__(self, index: int, pos: Vector3D, radius: float) -> None:
        self.index = index
        self._pos = pos
        self.radius = radius

    def get_position(self) -> Vector3D:
        return self._pos


class CollisionDetector:
    """
    Asynchronous collision detector.

    - When enabled (`collisions=True` in the Environment), it receives agent
      snapshots from all EntityManagers and an object description from the arena.
    - It resolves:
        * agent–agent collisions across ALL managers (all-to-all);
        * agent–object collisions;
    - It does NOT handle arena boundary collisions: those are handled in
      EntityManager._clamp_to_arena(), which stays active regardless of the
      collisions flag.
    """

    def __init__(self, arena_shape: Shape, collisions: bool, wrap_config: Optional[dict] = None) -> None:
        """Initialize the instance."""
        self.arena_shape = arena_shape
        self.collisions = collisions
        self.wrap_config = wrap_config

        # Latest snapshot of all agents (flattened across managers).
        self.agents: Dict[int, Dict[str, AgentCollisionPayload]] = {}
        # Objects: {obj_id: (shapes, positions)}
        self.objects: Dict[str, Tuple[List[Shape], List[Vector3D]]] = {}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _poll(self, q: Any, timeout: float = 0.0) -> bool:
        """Safe poll for Queue/Pipe or lists of queues."""
        if isinstance(q, (list, tuple)):
            return any(self._poll(elem, timeout) for elem in q if elem is not None)

        poll_fn = getattr(q, "poll", None)
        if callable(poll_fn):
            try:
                return bool(poll_fn(timeout))
            except Exception:
                return False

        get_fn = getattr(q, "get", None)
        if not callable(get_fn):
            return False

        # Last resort: try a blocking get with timeout and push back.
        try:
            item = q.get(timeout=timeout)
            q.put(item)
            return True
        except Exception:
            return False

    @staticmethod
    def _shape_radius(shape: Shape) -> float:
        """Best-effort radius for broad-phase checks."""
        getter = getattr(shape, "get_radius", None)
        if callable(getter):
            try:
                r = float(getter())
                if r > 0:
                    return r
            except Exception:
                pass

        center = shape.center_of_mass()
        try:
            return max(
                (Vector3D(v.x - center.x, v.y - center.y, v.z - center.z).magnitude()
                 for v in shape.vertices_list),
                default=0.0
            )
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Core run loop
    # ------------------------------------------------------------------
    def run(
        self,
        dec_agents_in: Any,
        dec_agents_out: Any,
        dec_arena_in: Any
    ) -> None:
        """
        Main loop: wait for updates from the arena and the entity managers,
        compute collision responses, and send corrections back.

        dec_agents_in:
            - single queue or list of queues
            - each manager sends:
              {"manager_id": int, "agents": {club: (shapes, vels, fwd, pos, names)}}

        dec_agents_out:
            - single queue or list of queues
            - for manager i, we send:
              {club: [Vector3D | None, ...]} (one list entry per entity)

        dec_arena_in:
            - queue where the arena publishes objects:
              {"objects": {obj_id: (shapes, positions)}}
        """
        logger.info("CollisionDetector started (collisions=%s)", self.collisions)

        # Normalise queues to lists for ease of indexing.
        agent_inputs = dec_agents_in if isinstance(dec_agents_in, (list, tuple)) else [dec_agents_in]
        manager_outputs = dec_agents_out if isinstance(dec_agents_out, (list, tuple)) else [dec_agents_out]

        # Latest snapshot per manager_id.
        latest_agents: Dict[int, Dict[str, AgentCollisionPayload]] = {}

        while True:
            idle = True

            # 1) Pull latest objects description from arena.
            if dec_arena_in and self._poll(dec_arena_in, 0.0):
                try:
                    payload = dec_arena_in.get()
                    if payload:
                        # Expected format: {"objects": {id: (shapes, positions)}}
                        self.objects = payload.get("objects", {}) or {}
                        logger.debug("CollisionDetector: objects updated (%d groups)", len(self.objects))
                        idle = False
                except EOFError:
                    pass

            # 2) Pull latest agent snapshots from all managers.
            updated = False
            for q in agent_inputs:
                if q is None:
                    continue
                if self._poll(q, 0.0):
                    try:
                        payload = q.get()
                    except EOFError:
                        payload = None
                        continue
                    if not payload:
                        continue
                    manager_id = int(payload.get("manager_id", 0))
                    agents_payload = payload.get("agents", {}) or {}
                    latest_agents[manager_id] = agents_payload
                    updated = True

            # 3) If we have new agent data, compute collisions all-to-all.
            if updated and self.collisions:
                idle = False
                try:
                    corrections = self._compute_all_corrections(latest_agents)
                except Exception as exc:
                    logger.exception("CollisionDetector: error in collision computation: %s", exc)
                    corrections = {}

                # 4) Send per-manager corrections to the appropriate queues.
                for manager_id, mgr_corr in corrections.items():
                    if manager_id < 0 or manager_id >= len(manager_outputs):
                        # Fallback: send to first queue if indexing is out of range.
                        target_q = manager_outputs[0] if manager_outputs else None
                    else:
                        target_q = manager_outputs[manager_id]
                    if target_q is None:
                        continue
                    try:
                        target_q.put(mgr_corr)
                    except Exception:
                        # The manager might have died; avoid crashing the detector.
                        logger.debug("CollisionDetector: failed to send corrections to manager %d", manager_id)

            if idle:
                time.sleep(0.001)

    # ------------------------------------------------------------------
    # Collision computation (broad-phase via SpatialGrid, narrow-phase via shapes)
    # ------------------------------------------------------------------
    def _compute_all_corrections(
        self,
        latest_agents: Dict[int, Dict[str, AgentCollisionPayload]]
    ) -> Dict[int, Dict[str, List[Optional[Vector3D]]]]:
        """
        Compute collision corrections for all managers at once.

        Returns:
            {manager_id: {club: [Vector3D | None, ...]}}
        """
        # Flatten all agents into a single list for broad-phase.
        flat_records: List[Dict[str, Any]] = []
        radii: List[float] = []

        for manager_id, mgr_agents in latest_agents.items():
            for club, (shapes, vels, fwds, positions, names) in mgr_agents.items():
                for idx, shape in enumerate(shapes):
                    pos = positions[idx]
                    radius = self._shape_radius(shape)
                    record = {
                        "manager_id": manager_id,
                        "club": club,
                        "local_index": idx,
                        "shape": shape,
                        "pos": pos,
                        "forward": fwds[idx],
                        "name": names[idx],
                        "radius": radius,
                    }
                    flat_records.append(record)
                    radii.append(radius)

        n = len(flat_records)
        if n == 0:
            return {m_id: {} for m_id in latest_agents.keys()}

        # Build spatial grid for broad-phase.
        avg_radius = sum(radii) / max(1, len(radii))
        # Use a cell size proportional to typical diameter; keep a small minimum.
        cell_size = max(0.1, avg_radius * 2.5)
        grid = SpatialGrid(cell_size)

        grid_items: List[_GridItem] = []
        for idx, rec in enumerate(flat_records):
            item = _GridItem(idx, rec["pos"], rec["radius"])
            grid_items.append(item)
            grid.insert(item)

        # Prepare accumulation for responses per record.
        response_sum: List[Vector3D] = [Vector3D(0, 0, 0) for _ in range(n)]
        response_count: List[int] = [0 for _ in range(n)]

        # ------------------------------------------------------------------
        # Agent–agent collisions (all-to-all across managers)
        # ------------------------------------------------------------------
        for item in grid_items:
            i = item.index
            rec_i = flat_records[i]
            pos_i = rec_i["pos"]
            shape_i: Shape = rec_i["shape"]
            fwd_i: Vector3D = rec_i["forward"]
            r_i = rec_i["radius"]

            # Search neighbours in nearby cells.
            # Radius here is a broad-phase search radius; we use a conservative value.
            search_radius = max(r_i * 2.5, 0.1)
            neighbours = grid.neighbors(item, search_radius)

            for other in neighbours:
                j = other.index
                if j <= i:
                    # Avoid processing the same pair twice.
                    continue
                rec_j = flat_records[j]
                pos_j = rec_j["pos"]
                shape_j: Shape = rec_j["shape"]
                fwd_j: Vector3D = rec_j["forward"]
                r_j = rec_j["radius"]

                # Broad-phase circle check.
                delta = Vector3D(pos_i.x - pos_j.x, pos_i.y - pos_j.y, 0)
                sum_r = r_i + r_j
                dist = delta.magnitude()

                if dist >= sum_r:
                    continue

                # If positions coincide, pick an arbitrary direction.
                if dist == 0.0:
                    if fwd_i.magnitude() > 0:
                        delta = fwd_i
                    elif fwd_j.magnitude() > 0:
                        delta = fwd_j * -1.0
                    else:
                        delta = Vector3D(1, 0, 0)
                    dist = 0.0

                # Narrow-phase with shapes.
                overlap = shape_i.check_overlap(shape_j)
                if not overlap[0]:
                    continue

                normal = delta.normalize()
                penetration = sum_r - dist + 1e-3

                # Split the correction equally between the two agents.
                corr_i = normal * (penetration * 0.5)
                corr_j = normal * (-penetration * 0.5)

                response_sum[i] += corr_i
                response_count[i] += 1
                response_sum[j] += corr_j
                response_count[j] += 1

        # ------------------------------------------------------------------
        # Agent–object collisions (objects do not move, only agents are corrected)
        # ------------------------------------------------------------------
        if self.objects:
            for idx, rec in enumerate(flat_records):
                pos = rec["pos"]
                shape = rec["shape"]
                fwd = rec["forward"]
                r = rec["radius"]
                name = rec["name"]

                local_responses: List[Vector3D] = []

                for obj_id, (shapes, positions) in self.objects.items():
                    for s_idx, obj_shape in enumerate(shapes):
                        obj_pos = positions[s_idx]

                        delta = Vector3D(pos.x - obj_pos.x, pos.y - obj_pos.y, 0)
                        r_obj = self._shape_radius(obj_shape)
                        sum_r = r + r_obj
                        dist = delta.magnitude()

                        if dist >= sum_r:
                            continue

                        if dist == 0.0:
                            if fwd.magnitude() > 0:
                                delta = fwd
                            else:
                                delta = Vector3D(1, 0, 0)
                            dist = 0.0

                        overlap = shape.check_overlap(obj_shape)
                        if not overlap[0]:
                            continue

                        normal = delta.normalize()
                        penetration = sum_r - dist + 1e-3
                        resp = normal * penetration
                        local_responses.append(resp)

                        logger.debug("Collision agent-object: %s -> %s depth=%.4f", name, obj_id, penetration)

                if local_responses:
                    # Average local responses and add to global sum.
                    avg_resp = Vector3D()
                    for rvec in local_responses:
                        avg_resp += rvec
                    avg_resp /= float(len(local_responses))

                    response_sum[idx] += avg_resp
                    response_count[idx] += 1

        # ------------------------------------------------------------------
        # Build per-manager output: average accumulated responses.
        # ------------------------------------------------------------------
        corrections: Dict[int, Dict[str, List[Optional[Vector3D]]]] = {}

        # Prepare empty structures.
        for manager_id, mgr_agents in latest_agents.items():
            mgr_out: Dict[str, List[Optional[Vector3D]]] = {}
            for club, (shapes, _, _, _, _) in mgr_agents.items():
                mgr_out[club] = [None] * len(shapes)
            corrections[manager_id] = mgr_out

        # Fill them.
        for idx, rec in enumerate(flat_records):
            cnt = response_count[idx]
            if cnt == 0:
                continue
            summed = response_sum[idx]
            corr = summed / float(cnt)

            m_id = rec["manager_id"]
            club = rec["club"]
            local_index = rec["local_index"]

            mgr_corr = corrections.get(m_id)
            if not mgr_corr:
                continue
            club_list = mgr_corr.get(club)
            if club_list is None or local_index >= len(club_list):
                continue
            club_list[local_index] = corr

        return corrections
