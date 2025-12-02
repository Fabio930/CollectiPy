from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

LOG_DIRNAME = "logs"
DEFAULT_RESULTS_BASE = "./data/"


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


def normalize_specs(value) -> set[str]:
    """Return a normalized set of spec tokens."""
    if value is None:
        return set()
    if isinstance(value, str):
        iterable = [value]
    elif isinstance(value, (list, tuple, set)):
        iterable = value
    else:
        iterable = []
    return {str(item).strip().lower() for item in iterable if str(item).strip()}


def resolve_result_specs(results_cfg: dict | None) -> tuple[set[str], set[str]]:
    """Return agent/group specs applying defaults and legacy aliases."""
    if not isinstance(results_cfg, dict):
        return set(), set()
    agent_specs = normalize_specs(results_cfg.get("agent_specs"))
    group_specs = normalize_specs(results_cfg.get("group_specs"))
    legacy_specs = normalize_specs(results_cfg.get("model_specs"))
    agent_specs_were_provided = "agent_specs" in results_cfg
    if not agent_specs_were_provided and not agent_specs:
        agent_specs = {"base"}
    if legacy_specs:
        if "spin_model" in legacy_specs:
            agent_specs.add("spin_model")
        if "graphs" in legacy_specs:
            group_specs.update({"graph_messages", "graph_detection", "graphs"})
        if "graph_messages" in legacy_specs:
            group_specs.add("graph_messages")
        if "graph_detection" in legacy_specs:
            group_specs.add("graph_detection")
    return agent_specs, group_specs


def resolve_base_dirs(
    logging_cfg: dict | None,
    results_cfg: dict | None,
) -> tuple[Path, Path]:
    """
    Return (results_root, logs_root) applying default coupling:
    - results defaults to DEFAULT_RESULTS_BASE unless overridden.
    - logs defaults to <results_root>/logs unless logging.base_path is provided.
    """
    results_cfg = results_cfg or {}
    logging_cfg = logging_cfg or {}

    raw_results_base = results_cfg.get("base_path")
    raw_logs_base = logging_cfg.get("base_path")

    results_root = Path(raw_results_base) if raw_results_base else Path(DEFAULT_RESULTS_BASE)
    results_root = results_root.expanduser()

    if raw_logs_base:
        logs_root = Path(raw_logs_base).expanduser()
    else:
        logs_root = results_root / LOG_DIRNAME

    return results_root.resolve(), logs_root.resolve()


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


def generate_shared_unique_folder_name(
    base_paths: Iterable[str | Path],
    base_name: str,
) -> str:
    """Return a unique folder name across multiple base paths."""
    abs_bases = [Path(p) for p in base_paths if p]
    existing: set[str] = set()
    for base in abs_bases:
        if not base.exists():
            continue
        for name in os.listdir(base):
            if (base / name).is_dir():
                existing.add(name)
    candidate = base_name
    counter = 0
    while candidate in existing:
        counter += 1
        suffix = _alphanumeric_index(counter)
        candidate = f"{base_name}_{suffix}"
    return candidate
