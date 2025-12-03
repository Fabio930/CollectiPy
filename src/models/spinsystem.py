# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Spin system model used by spin-based movement behaviours."""
import math
import numpy as np
from random import Random
from models.utils import normalize_angle

_PI = math.pi

class SpinModule:
    """Spin module."""
    def __init__(self, random_generator:Random, num_groups:int, num_spins_per_group:int, T:float, J:float, nu:float, p_spin_up:float=0.5, time_delay:int=1, dynamics:str='metropolis'):
        """Initialize the instance."""
        self.random_generator = random_generator
        self.num_groups = num_groups
        self.num_spins_per_group = num_spins_per_group
        self.T = T
        self.J = J
        self.nu = nu
        self.p_spin_up = p_spin_up
        self.spins = self._random_spins()
        self.spins_history = [self.spins.copy()]
        self.history_length = time_delay
        self.dynamics = dynamics
        group_angles = np.linspace(0, 2 * _PI, num_groups, endpoint=False)
        self.angles = np.repeat(group_angles, self.num_spins_per_group)
        self.external_field = np.zeros(self.num_groups * self.num_spins_per_group, dtype=np.float32)
        self.avg_direction = None
        self.J_matrix = self._precompute_j_matrix()

    def _random_spins(self):
        """Generate the spins."""
        rand_vals = np.array([Random.uniform(self.random_generator, 0, 1)
                              for _ in range(self.num_groups * self.num_spins_per_group)])
        spins = (rand_vals < self.p_spin_up).astype(np.uint8)
        return spins.reshape(self.num_groups, self.num_spins_per_group)

    def _precompute_j_matrix(self):
        """Precompute j matrix."""
        angle_diff_matrix = np.abs(np.subtract.outer(self.angles, self.angles))
        angle_diff_matrix = np.minimum(angle_diff_matrix, 2 * _PI - angle_diff_matrix)
        return np.cos(_PI * ((angle_diff_matrix / _PI) ** self.nu))

    def set_p_spin_up(self, p_spin_up:float):
        """Set the p spin up."""
        self.p_spin_up = p_spin_up

    def calculate_hamiltonian(self, state):
        """Calculate hamiltonian."""
        state_flat = state.ravel()
        interaction = state_flat[:, None] * state_flat[None, :]
        H_spin_interactions = -(self.J / (self.num_spins_per_group * self.num_groups)) * np.sum(np.triu(self.J_matrix * interaction, 1))
        external_field_contribution = -np.dot(self.external_field, state_flat)
        return H_spin_interactions + external_field_contribution

    def step(self,timedelay=True, dt=0.1, tau=33):
        """Execute the simulation step."""
        i = Random.randint(self.random_generator, 0, self.num_groups - 1)
        j = Random.randint(self.random_generator, 0, self.num_spins_per_group - 1)
        state_to_use = self.spins
        if timedelay:
            hybrid_state = self.spins_history[0].copy()
            hybrid_state[i, j] = self.spins[i, j]
            state_to_use = hybrid_state
        current_hamiltonian = self.calculate_hamiltonian(state_to_use)
        state_to_use[i, j] ^= 1
        new_hamiltonian = self.calculate_hamiltonian(state_to_use)
        delta_h = new_hamiltonian - current_hamiltonian
        if self.dynamics == 'metropolis':
            self._metropolis_acceptance(i, j, delta_h)
        elif self.dynamics == 'glauber':
            self._glauber_acceptance(i, j, delta_h, dt, tau)
        else:
            raise ValueError(f"Unknown dynamics type: {self.dynamics}")
        self.spins_history.append(self.spins.copy())
        if len(self.spins_history) > self.history_length:
            self.spins_history.pop(0)

    def _metropolis_acceptance(self, i, j, delta_h):
        """Metropolis acceptance."""
        if delta_h <= 0 or Random.uniform(self.random_generator, 0, 1) < math.exp(-delta_h / self.T):
            self.spins[i, j] ^= 1

    def _glauber_acceptance(self, i, j, delta_h, dt, tau):
        """Glauber acceptance."""
        G = self.num_groups
        N = self.num_spins_per_group
        acceptance_prob = (G * N * dt) / tau * (1 / (1 + math.exp(delta_h / self.T)))
        acceptance_prob = min(acceptance_prob, 1.0)
        if Random.uniform(self.random_generator, 0, 1) < acceptance_prob:
            self.spins[i, j] ^= 1

    def run_spins(self, steps=1, dt=0.1, tau=33):
        """Run the spins."""
        for _ in range(steps):
            self.step(dt=dt, tau=tau)
        return self.spins

    def average_direction_of_activity(self):
        """Average direction of activity."""
        flattened_spins = self.spins.ravel()
        if np.all(flattened_spins == 1):
            self.avg_direction = None
            return None
        unit_vectors = np.exp(1j * self.angles)
        active_mask = flattened_spins == 1
        if not np.any(active_mask):
            self.avg_direction = None
            return None
        sum_vector = np.sum(unit_vectors[active_mask])
        self.avg_direction = None
        if sum_vector != 0: self.avg_direction = math.atan2(sum_vector.imag, sum_vector.real)
        return self.avg_direction

    def get_avg_direction_of_activity(self):
        """Return the avg direction of activity."""
        return self.avg_direction

    def get_inverse_magnitude_of_activity(self):
        """Return the inverse magnitude of activity."""
        flattened_spins = self.spins.ravel()
        unit_vectors = np.exp(1j * self.angles)
        active_mask = flattened_spins == 1
        if not np.any(active_mask):
            return float('inf')
        sum_vector = np.sum(unit_vectors[active_mask])
        magnitude = abs(sum_vector)
        return 1 / magnitude if magnitude != 0 else float('inf')

    def get_width_of_activity(self):
        """Return the width of activity."""
        flattened_spins = self.spins.ravel()
        active_mask = flattened_spins == 1
        active_angles = self.angles[active_mask]
        if len(active_angles) > 1:
            unit_vectors = np.exp(1j * active_angles)
            R = abs(np.mean(unit_vectors))
            # Guard against numerical edge cases and clamp into (0, 1).
            if not math.isfinite(R) or R <= 0.0:
                return None
            R_clamped = max(min(R, 1.0 - 1e-12), 1e-12)
            circ_std = math.sqrt(max(0.0, -2.0 * math.log(R_clamped)))
            return circ_std
        return None

    def reset_spins(self):
        """Reset the spins."""
        self.spins = self._random_spins()
        self.spins_history = [self.spins.copy()]

    def update_external_field(self, perceptual_outputs):
        """Update external field."""
        self.external_field = np.asarray(perceptual_outputs, dtype=np.float32)

    def get_states(self):
        """Return the states."""
        return self.spins

    def get_external_field(self):
        """Return the external field."""
        return self.external_field

    def get_angles(self):
        """Return the angles."""
        return (self.angles, self.num_groups, self.num_spins_per_group)

    def set_states(self, states):
        """Set the states."""
        if states.shape != self.spins.shape:
            raise ValueError(f"Invalid shape for spin states. Expected {self.spins.shape}, but got {states.shape}.")
        self.spins = states.copy()
        self.spins_history.append(self.spins.copy())
        if len(self.spins_history) > self.history_length:
            self.spins_history.pop(0)

    def sense_other_ring(self, other_ring_states, gain=1.0):
        """Sense the environment and update perception."""
        self.external_field = gain * np.asarray(other_ring_states, dtype=np.float32).ravel()


class PerceptionModule:
    """Perception layer converting detections into spin-friendly channels."""
    def __init__(
        self,
        num_groups: int,
        num_spins_per_group: int,
        perception_width: float,
        group_angles: np.ndarray,
        reference: str = "egocentric",
        perception_global_inhibition: float = 0.0,
        max_detection_distance: float | None = None,
        agent_strength: float = 5.0,
    ):
        self.num_groups = num_groups
        self.num_spins_per_group = num_spins_per_group
        self.perception_width = perception_width
        self.group_angles = group_angles
        self.reference = reference
        self.perception_global_inhibition = perception_global_inhibition
        self.max_detection_distance = (
            float(max_detection_distance) if max_detection_distance is not None else math.inf
        )
        self.agent_strength = agent_strength

    def build_channels(self, observer, detections: dict) -> dict[str, np.ndarray]:
        """Convert raw detections into object/agent/combined perception channels."""
        channel_size = self.num_groups * self.num_spins_per_group
        agent_channel = np.zeros(channel_size)
        object_channel = np.zeros(channel_size)
        for target in detections.get("agents", []) or []:
            position = target.get("position")
            if position is None:
                continue
            dx = position.x - observer.position.x
            dy = position.y - observer.position.y
            dz = position.z - observer.position.z
            strength = target.get("strength", self.agent_strength)
            width = target.get("width", self.perception_width)
            self._accumulate_target(agent_channel, dx, dy, dz, width, strength, observer)

        for target in detections.get("objects", []) or []:
            position = target.get("position")
            if position is None:
                continue
            dx = position.x - observer.position.x
            dy = position.y - observer.position.y
            dz = position.z - observer.position.z
            uncertainty = target.get("uncertainty", 0.0) or 0.0
            width = self.perception_width + uncertainty
            try:
                strength = float(target.get("strength", 0.0) or 0.0)
            except (TypeError, ValueError):
                strength = 0.0
            self._accumulate_target(object_channel, dx, dy, dz, width, strength, observer)

        self._apply_global_inhibition(agent_channel)
        self._apply_global_inhibition(object_channel)
        combined_channel = agent_channel + object_channel
        return {
            "objects": object_channel,
            "agents": agent_channel,
            "combined": combined_channel,
        }

    def _accumulate_target(self, perception, dx, dy, dz, effective_width, strength, observer):
        """Accumulate weighted contribution of a target into a perception channel."""
        distance = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
        if math.isfinite(self.max_detection_distance) and distance > self.max_detection_distance:
            return
        angle_to_object = math.degrees(math.atan2(-dy, dx))
        if self.reference == "egocentric":
            angle_to_object -= observer.orientation.z
        angle_to_object = normalize_angle(angle_to_object)
        angle_diffs = np.abs(self.group_angles - math.radians(angle_to_object))
        angle_diffs = np.minimum(angle_diffs, 2 * math.pi - angle_diffs)
        sigma = max(effective_width, 1e-6)
        weights = (self.perception_width / sigma) * np.exp(-(angle_diffs ** 2) / (2 * (sigma ** 2)))
        weights *= strength
        perception += np.repeat(weights, self.num_spins_per_group)

    def _apply_global_inhibition(self, perception_channel):
        """Apply a global inhibition value to the provided perception channel."""
        if self.perception_global_inhibition == 0:
            return
        perception_channel -= self.perception_global_inhibition

