# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""CPU affinity helpers for environment processes."""
from __future__ import annotations

import psutil

from core.util.logging_util import get_logger

logger = get_logger("environment")

used_cores: set[int] = set()


def pick_least_used_free_cores(num: int):
    """
    Select 'num' cores that are not in used_cores, picking the ones with lower CPU usage.
    """
    global used_cores

    usage = psutil.cpu_percent(interval=0.1, percpu=True)
    ordered = sorted(range(len(usage)), key=lambda c: usage[c])
    free = [c for c in ordered if c not in used_cores]
    return free[:num]


def set_affinity_safely(proc, num_cores: int):
    """
    Assign the least used cores without repetition.
    """
    global used_cores
    try:
        selected = pick_least_used_free_cores(num_cores)
        if not selected:
            logger.info("No free cores: fallback to all cores")
            fallback_count = psutil.cpu_count(logical=True) or 1
            selected = list(range(fallback_count))
        p = psutil.Process(proc.pid)
        p.cpu_affinity(selected)
        used_cores.update(selected)
        return selected
    except Exception as e:
        logger.error(f"[AFFINITY ERROR] PID {proc.pid}: {e}")
        return []


def set_shared_affinity(processes, num_cores: int):
    """
    Assign a shared set of cores to multiple processes, avoiding overlap with already used cores.
    """
    global used_cores
    try:
        selected = pick_least_used_free_cores(num_cores)
        if not selected:
            fallback_count = psutil.cpu_count(logical=True) or 1
            selected = list(range(fallback_count))

        for proc in processes:
            if proc is None:
                continue
            p = psutil.Process(proc.pid)
            p.cpu_affinity(selected)

        used_cores.update(selected)
        return selected
    except Exception as e:
        logger.error(f"[AFFINITY ERROR] shared for {[p.pid for p in processes if p]}: {e}")
        return []
