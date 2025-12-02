from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


def sanitize_token(token: str | None) -> str | None:
    """Return a filesystem-friendly token derived from the input."""
    if not token:
        return None
    raw = re.sub(r"[^A-Za-z0-9]+", "_", str(token))
    raw = re.sub(r"_+", "_", raw).strip("_").lower()
    return raw or None


def _alphanumeric_index(index: int) -> str:
    """Convert an integer into an alphanumeric suffix (a, b, ..., z, 0, 1, ...)."""
    if index <= 0:
        return ""
    digits = "abcdefghijklmnopqrstuvwxyz0123456789"
    base = len(digits)
    result = []
    value = index
    while value > 0:
        value -= 1
        result.append(digits[value % base])
        value //= base
    return "".join(reversed(result))


def derive_experiment_folder_basename(
    config_elem,
    agent_specs: Iterable[str] | None = None,
    group_specs: Iterable[str] | None = None,
) -> str:
    """Build a descriptive folder base name from configuration tokens."""
    tokens: list[str] = []
    config_path = getattr(config_elem, "config_path", None)
    if config_path:
        tokens.append(Path(config_path).stem)

    arena_id = getattr(config_elem, "arena", {}).get("_id")
    if arena_id:
        tokens.append(str(arena_id))

    env = getattr(config_elem, "environment", {}) or {}
    tokens.append("collisions" if env.get("collisions") else "nocol")
    num_runs = env.get("num_runs")
    if isinstance(num_runs, int) and num_runs > 1:
        tokens.append(f"run{num_runs}")

    agents = env.get("agents", {})
    if isinstance(agents, dict):
        tokens.extend(str(name) for name in sorted(agents.keys()))
        behaviors = {
            str(cfg.get("moving_behavior"))
            for cfg in agents.values()
            if isinstance(cfg, dict) and cfg.get("moving_behavior")
        }
        tokens.extend(sorted(behaviors))

    spec_tokens = set()
    if agent_specs:
        spec_tokens.update({str(tok) for tok in agent_specs if tok})
    if group_specs:
        spec_tokens.update({str(tok) for tok in group_specs if tok})
    tokens.extend(sorted(spec_tokens))

    sanitized = []
    seen = set()
    for tok in tokens:
        cleaned = sanitize_token(tok)
        if not cleaned or cleaned in seen:
            continue
        sanitized.append(cleaned)
        seen.add(cleaned)
    if not sanitized:
        return "config"
    return "_".join(sanitized)


def generate_unique_folder_name(base_path: str | Path, base_name: str) -> str:
    """Ensure the folder name is unique by appending an alphanumeric suffix when needed."""
    abs_base = Path(base_path)
    existing = {
        name
        for name in os.listdir(abs_base)
        if os.path.isdir(os.path.join(abs_base, name))
    }
    candidate = base_name
    counter = 0
    while candidate in existing:
        counter += 1
        suffix = _alphanumeric_index(counter)
        candidate = f"{base_name}_{suffix}"
    return candidate
