# Re-export for compatibility.
from core.main.environment.runtime import Environment
from core.main.environment.factory import EnvironmentFactory
from core.main.environment.affinity import (
    pick_least_used_free_cores,
    set_affinity_safely,
    set_shared_affinity,
    used_cores,
)
from core.main.environment.agents import (
    agents_init,
    _split_agents,
    _count_agents,
    _estimate_agents_per_process,
    compute_agent_processes,
)

__all__ = [
    "Environment",
    "EnvironmentFactory",
    "pick_least_used_free_cores",
    "set_affinity_safely",
    "set_shared_affinity",
    "used_cores",
    "agents_init",
    "_split_agents",
    "_count_agents",
    "_estimate_agents_per_process",
    "compute_agent_processes",
]
