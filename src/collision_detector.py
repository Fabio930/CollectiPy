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
from typing import Dict, List, Optional, Tuple
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

    def run(
        self,
        dec_agents_in: mp.Queue,
        dec_agents_out: mp.Queue,
        dec_arena_in: mp.Queue
    ) -> None:
        """
        Main loop: wait for updates from the arena and the entity manager,
        compute collision responses, and send corrections back.
        """
        logger.info("CollisionDetector started (collisions=%s)", self.collisions)
        while True:
            out: Dict[str, List[Optional[Vector3D]]] = {}
            # Pull the latest objects description when available.
            if dec_arena_in.poll(0):
                self.objects = dec_arena_in.get()["objects"]
                logger.debug("Objects updated (%d groups)", len(self.objects))
            # Pull agent data (shapes, velocities, names, ...).
            if dec_agents_in.poll(0):
                self.agents = dec_agents_in.get()["agents"]
                logger.debug("Agent state received (%d groups)", len(self.agents))
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
                            logger.debug("%s collision correction -> %s", name, correction)
                    out[club] = out_tmp
                dec_agents_out.put(out)

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
                sum_radius = shape.get_radius() + other_shape.get_radius()
                actual_distance = delta.magnitude()
                if actual_distance >= sum_radius or actual_distance == 0:
                    continue
                overlap = shape.check_overlap(other_shape)
                if not overlap[0]:
                    continue
                normal = delta.normalize()
                penetration_depth = sum_radius - actual_distance
                response = self._compute_bounce_response(
                    position,
                    forward_vector,
                    normal,
                    penetration_depth,
                    other_vectors[idx]
                )
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
                sum_radius = shape.get_radius() + obj_shape.get_radius()
                actual_distance = delta.magnitude()
                if actual_distance >= sum_radius or actual_distance == 0:
                    continue
                overlap = shape.check_overlap(obj_shape)
                if not overlap[0]:
                    continue
                normal = delta.normalize()
                penetration_depth = sum_radius - actual_distance
                response = self._compute_bounce_response(
                    position,
                    forward_vector,
                    normal,
                    penetration_depth,
                    Vector3D()
                )
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
        prev_position = position - forward_vector
        allowed_move = Vector3D(forward_vector.x, forward_vector.y, 0)
        corrective = Vector3D(0, 0, 0)

        if shape_min.x < arena_min.x:
            corrective.x += arena_min.x - shape_min.x + 1e-3
            if allowed_move.x < 0:
                allowed_move.x = 0
        elif shape_max.x > arena_max.x:
            corrective.x += arena_max.x - shape_max.x - 1e-3
            if allowed_move.x > 0:
                allowed_move.x = 0

        if shape_min.y < arena_min.y:
            corrective.y += arena_min.y - shape_min.y + 1e-3
            if allowed_move.y < 0:
                allowed_move.y = 0
        elif shape_max.y > arena_max.y:
            corrective.y += arena_max.y - shape_max.y - 1e-3
            if allowed_move.y > 0:
                allowed_move.y = 0

        logger.info("Collision arena-boundary for shape id=%s", shape._id)
        corrected_position = prev_position + allowed_move + corrective
        return corrected_position

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


def reflect_vector(vector: Vector3D, normal: Vector3D) -> Vector3D:
    """Reflect the vector."""
    n = normal.normalize()
    dot = vector.dot(n)
    return vector - n * (2 * dot)
