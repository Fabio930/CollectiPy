# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Agent initialization and splitting utilities for environment."""
from __future__ import annotations

import psutil
from typing import Any, Dict

from core.entities import EntityFactory
from core.configuration.config import Config


def agents_init(exp: Config, log):
    """Instantiate agents from configuration."""
    agents_cfg = exp.environment.get("agents") or {}
    if not isinstance(agents_cfg, dict):
        raise ValueError("Invalid agents configuration: expected a dictionary.")
    agents: Dict[str, tuple[Dict[str, Any], list]] = {
        agent_type: (cfg, []) for agent_type, cfg in agents_cfg.items()
    }

    for agent_type, (config, entities) in agents.items():
        if not isinstance(config, dict):
            raise ValueError(f"Invalid agent configuration for {agent_type}")
        number_raw = config.get("number", 0)
        try:
            number = int(number_raw)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid number of agents for {agent_type}: {number_raw}")
        if number <= 0:
            raise ValueError(f"Agent group {agent_type} must have a positive 'number' of agents")
        for n in range(number):
            entities.append(
                EntityFactory.create_entity(
                    entity_type="agent_" + agent_type,
                    config_elem=config,
                    _id=n
                )
            )
    totals = {name: len(ents) for name, (_, ents) in agents.items()}
    log.info("Agents initialized: total=%s groups=%s", sum(totals.values()), totals)
    return agents


def _split_agents(
    agents: Dict[str, tuple[Dict[str, Any], list]],
    num_blocks: int,
) -> list[Dict[str, tuple[Dict[str, Any], list]]]:
    """Split agents into nearly even blocks."""
    if num_blocks <= 1:
        return [agents]

    flat = []
    for agent_type, (cfg, entities) in agents.items():
        for entity in entities:
            flat.append((agent_type, cfg, entity))

    total = len(flat)
    num_blocks = max(1, min(num_blocks, total))
    blocks: list[Dict[str, tuple[Dict[str, Any], list]]] = [dict() for _ in range(num_blocks)]

    for idx, (agent_type, cfg, entity) in enumerate(flat):
        target = idx % num_blocks
        if agent_type not in blocks[target]:
            blocks[target][agent_type] = (cfg, [])
        blocks[target][agent_type][1].append(entity)

    blocks = [b for b in blocks if any(len(v[1]) for v in b.values())]
    return blocks


def _count_agents(
    agents: Dict[str, tuple[Dict[str, Any], list]]
) -> int:
    """Count total agents."""
    total = 0
    for _, (_, entities) in agents.items():
        total += len(entities)
    return total


def _estimate_agents_per_process(
    agents: Dict[str, tuple[Dict[str, Any], list]],
) -> int:
    """
    Derive the desired number of agents per process based on workload.

    Heavy behavior -> fewer agents per process.
    Lighter behavior -> more agents per process.
    """
    has_spin = False
    has_messages = False
    has_fast_detection = False

    for cfg, entities in agents.values():
        behavior = str(cfg.get("moving_behavior", "") or "").lower()
        if behavior == "spin_model":
            has_spin = True

        if cfg.get("messages"):
            has_messages = True

        det_cfg = cfg.get("detection", {}) or {}
        try:
            acq_rate = float(det_cfg.get("acquisition_per_second", det_cfg.get("rx_per_second", 1)))
            if acq_rate > 1:
                has_fast_detection = True
        except Exception:
            pass

    if has_spin:
        return 6
    if has_messages or has_fast_detection:
        return 10
    return 20


def compute_agent_processes(
    agents: Dict[str, tuple[Dict[str, Any], list]],
    render_enabled: bool,
) -> int:
    """Compute number of agent manager processes with internal heuristics."""
    available_cores = psutil.cpu_count(logical=True) or 1
    total_agents = _count_agents(agents)
    if total_agents <= 0:
        return 1
    target = _estimate_agents_per_process(agents)
    target = max(5, min(30, target))

    import math
    n_procs = math.ceil(total_agents / target)

    reserved = 3 + (1 if render_enabled else 0)
    max_for_agents = max(1, available_cores - reserved)
    return max(1, min(8, n_procs, max_for_agents))


__all__ = [
    "agents_init",
    "_split_agents",
    "_count_agents",
    "_estimate_agents_per_process",
    "compute_agent_processes",
]
