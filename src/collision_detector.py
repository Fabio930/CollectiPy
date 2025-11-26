# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Collision detection utilities."""
from __future__ import annotations
import logging
import multiprocessing as mp
import time
from typing import Dict, List, Optional, Tuple, Any
from bodies.shapes3D import Shape
from geometry_utils.vector3D import Vector3D

logger = logging.getLogger("sim.collision")

# Type alias for the tuple exchanged with the collision detector.
AgentCollisionPayload = Tuple[
    List[Shape],            # shapes
    List[float],            # max velocities
    List[Vector3D],         # forward vectors
    List[Vector3D],         # previous positions
    List[str]               # agent names
]

class CollisionDetector:
    """
    Continuously consumes agent/object data and produces correction vectors
    that keep entities inside the arena and avoid overlaps.
    """
    def __init__(self, arena_shape: Shape, collisions: bool, wrap_config: Optional[dict] = None) -> None:
        """Initialize the instance."""
        self.arena_shape = arena_shape
        self.collisions = collisions
        self.wrap_config = wrap_config
        self.agents: Dict[str, AgentCollisionPayload] = {}
        self.objects: Dict[str, Tuple[List[Shape], List[Vector3D]]] = {}

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
        try:
            item = q.get(timeout=timeout)
            q.put(item)
            return True
        except Exception:
            return False

    def run(
        self,
        dec_agents_in: Any,
        dec_agents_out: Any,
        dec_arena_in: Any
    ) -> None:
        """
        Main loop: wait for updates from the arena and the entity manager,
        compute collision responses, and send corrections back.
        """
        logger.info("CollisionDetector started (collisions=%s)", self.collisions)
        agent_inputs = dec_agents_in if isinstance(dec_agents_in, (list, tuple)) else [dec_agents_in]
        manager_outputs = dec_agents_out if isinstance(dec_agents_out, (list, tuple)) else [dec_agents_out]
        latest_agents: Dict[int, Dict[str, AgentCollisionPayload]] = {}
        while True:
            idle = True
            # Pull the latest objects description when available.
            if dec_arena_in and self._poll(dec_arena_in, 0):
                try:
                    payload = dec_arena_in.get()
                    if payload:
                        self.objects = payload["objects"]
                        idle = False
                        logger.debug("Objects updated (%d groups)", len(self.objects))
                except EOFError:
                    pass
            # Pull agent data (shapes, velocities, names, ...).
            updated = False
            for q in agent_inputs:
                if q is None:
                    continue
                if self._poll(q, 0):
                    try:
                        payload = q.get()
                    except EOFError:
                        payload = None
                        continue
                    manager_id = payload.get("manager_id", 0)
                    latest_agents[manager_id] = payload["agents"]
                    updated = True
            if updated:
                idle = False
                merged: Dict[str, AgentCollisionPayload] = {}
                for ag in latest_agents.values():
                    merged.update(ag)
                self.agents = merged
                for m_id, mgr_agents in latest_agents.items():
                    out: Dict[str, List[Optional[Vector3D]]] = {}
                    for club, (shapes, velocities, vectors, positions, names) in mgr_agents.items():
                        n_shapes = len(shapes)
                        out_tmp: List[Optional[Vector3D]] = [None] * n_shapes
                        for idx in range(n_shapes):
                            shape = shapes[idx]
                            forward_vector = vectors[idx]
                            position = positions[idx]
                            name = names[idx]
                            responses: List[Vector3D] = []
                            if self.collisions:
                                responses.extend(
                                    self._resolve_agent_collisions(
                                        name,
                                        shape,
                                        position,
                                        forward_vector,
                                        vectors,
                                        positions,
                                        names
                                    )
                                )
                                if self.objects:
                                    responses.extend(
                                        self._resolve_object_collisions(
                                            name,
                                            shape,
                                            position,
                                            forward_vector
                                        )
                                    )
                            if not self.wrap_config:
                                boundary_response = self._resolve_arena_collision(
                                    shape,
                                    position,
                                    forward_vector
                                )
                                if boundary_response is not None:
                                    responses.append(boundary_response)
                            if responses:
                                correction = Vector3D()
                                for resp in responses:
                                    correction += resp
                                correction = correction / len(responses)
                                out_tmp[idx] = correction
                        out[club] = out_tmp
                    target_idx = m_id if m_id < len(manager_outputs) else 0
                    target_q = manager_outputs[target_idx]
                    if target_q:
                        try:
                            target_q.put(out)
                        except Exception:
                            pass
            if idle:
                time.sleep(0.001)

    def compute_corrections(self, agents_payload: dict, objects_payload: Optional[dict]) -> Dict[str, List[Optional[Vector3D]]]:
        """
        Synchronous collision resolution. Expects the same payload layout produced by
        EntityManager.pack_detector_data(): {club: (shapes, velocities, vectors, positions, names)}.
        """
        self.agents = agents_payload or {}
        self.objects = objects_payload or {}
        out: Dict[str, List[Optional[Vector3D]]] = {}
        for club, (shapes, velocities, vectors, positions, names) in self.agents.items():
            n_shapes = len(shapes)
            out_tmp: List[Optional[Vector3D]] = [None] * n_shapes
            for idx in range(n_shapes):
                shape = shapes[idx]
                forward_vector = vectors[idx]
                position = positions[idx]
                name = names[idx]
                responses: List[Vector3D] = []
                if self.collisions:
                    responses.extend(
                        self._resolve_agent_collisions(
                            name,
                            shape,
                            position,
                            forward_vector,
                            vectors,
                            positions,
                            names
                        )
                    )
                    if self.objects:
                        responses.extend(
                            self._resolve_object_collisions(
                                name,
                                shape,
                                position,
                                forward_vector
                            )
                        )
                if not self.wrap_config:
                    boundary_response = self._resolve_arena_collision(
                        shape,
                        position,
                        forward_vector
                    )
                    if boundary_response is not None:
                        responses.append(boundary_response)
                if responses:
                    correction = Vector3D()
                    for resp in responses:
                        correction += resp
                    correction = correction / len(responses)
                    out_tmp[idx] = correction
            out[club] = out_tmp
        return out

    def _resolve_agent_collisions(
        self,
        name: str,
        shape: Shape,
        position: Vector3D,
        forward_vector: Vector3D,
        vectors: List[Vector3D],
        positions: List[Vector3D],
        names: List[str]
    ) -> List[Vector3D]:
        """Resolve the agent collisions."""
        responses: List[Vector3D] = []
        for other_shapes, _, other_vectors, other_positions, other_names in self.agents.values():
            for idx, other_shape in enumerate(other_shapes):
                other_name = other_names[idx]
                if name == other_name:
                    continue
                other_position = other_positions[idx]
                delta = Vector3D(position.x - other_position.x, position.y - other_position.y, 0)
                sum_radius = self._shape_radius(shape) + self._shape_radius(other_shape)
                actual_distance = delta.magnitude()
                if actual_distance >= sum_radius:
                    continue
                if actual_distance == 0:
                    delta = forward_vector if forward_vector.magnitude() > 0 else Vector3D(1, 0, 0)
                    actual_distance = 0.0
                overlap = shape.check_overlap(other_shape)
                if not overlap[0]:
                    continue
                normal = delta.normalize()
                penetration_depth = sum_radius - actual_distance + 1e-3
                response = normal * penetration_depth
                responses.append(response)
                logger.info("Collision agent-agent: %s <-> %s depth=%.4f", name, other_name, penetration_depth)
        return responses

    def _resolve_object_collisions(
        self,
        name: str,
        shape: Shape,
        position: Vector3D,
        forward_vector: Vector3D
    ) -> List[Vector3D]:
        """Resolve the object collisions."""
        responses: List[Vector3D] = []
        for obj_id, (shapes, positions) in self.objects.items():
            for idx, obj_shape in enumerate(shapes):
                obj_position = positions[idx]
                delta = Vector3D(position.x - obj_position.x, position.y - obj_position.y, 0)
                sum_radius = self._shape_radius(shape) + self._shape_radius(obj_shape)
                actual_distance = delta.magnitude()
                if actual_distance >= sum_radius:
                    continue
                if actual_distance == 0:
                    delta = forward_vector if forward_vector.magnitude() > 0 else Vector3D(1, 0, 0)
                    actual_distance = 0.0
                overlap = shape.check_overlap(obj_shape)
                if not overlap[0]:
                    continue
                normal = delta.normalize()
                penetration_depth = sum_radius - actual_distance + 1e-3
                response = normal * penetration_depth
                responses.append(response)
                logger.info("Collision agent-object: %s -> %s depth=%.4f", name, obj_id, penetration_depth)
        return responses

    def _resolve_arena_collision(
        self,
        shape: Shape,
        position: Vector3D,
        forward_vector: Vector3D
    ) -> Optional[Vector3D]:
        """Resolve the arena collision."""
        if self.wrap_config and self.wrap_config.get("unbounded"):
            return None
        overlap = shape.check_overlap(self.arena_shape)
        if not overlap[0]:
            return None
        arena_min = self.arena_shape.min_vert()
        arena_max = self.arena_shape.max_vert()
        shape_min = shape.min_vert()
        shape_max = shape.max_vert()
        push = Vector3D(0, 0, 0)
        if shape_min.x < arena_min.x:
            push.x = arena_min.x - shape_min.x + 1e-3
        elif shape_max.x > arena_max.x:
            push.x = arena_max.x - shape_max.x - 1e-3

        if shape_min.y < arena_min.y:
            push.y = arena_min.y - shape_min.y + 1e-3
        elif shape_max.y > arena_max.y:
            push.y = arena_max.y - shape_max.y - 1e-3

        if push.x == 0 and push.y == 0:
            return None

        logger.info("Collision arena-boundary for shape id=%s", shape._id)
        return push

    def _compute_bounce_response(
        self,
        position: Vector3D,
        forward_vector: Vector3D,
        normal: Vector3D,
        penetration_depth: float,
        other_velocity: Vector3D
    ) -> Vector3D:
        """Compute bounce response."""
        relative_velocity = forward_vector - other_velocity
        closing_speed = relative_velocity.dot(normal)
        separation = normal * (penetration_depth + 1e-3)
        prev_position = position - forward_vector
        move = forward_vector
        if closing_speed > 0:
            reflected = reflect_vector(relative_velocity, normal)
            if reflected.magnitude() > 0:
                move = reflected.normalize() * forward_vector.magnitude()
        blended_move = (move * 0.8) + (forward_vector * 0.2)
        return prev_position + blended_move + separation

    def _shape_radius(self, shape: Shape) -> float:
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
                (Vector3D(v.x - center.x, v.y - center.y, v.z - center.z).magnitude() for v in shape.vertices_list),
                default=0.0
            )
        except Exception:
            return 0.0


def reflect_vector(vector: Vector3D, normal: Vector3D) -> Vector3D:
    """Reflect the vector."""
    n = normal.normalize()
    dot = vector.dot(n)
    return vector - n * (2 * dot)
