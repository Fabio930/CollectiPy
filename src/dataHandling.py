# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

from __future__ import annotations

import math, os, json, pickle, shutil, zipfile
from pathlib import Path
from config import Config
from utils.folder_utils import (
    DEFAULT_RESULTS_BASE,
    derive_experiment_folder_basename,
    generate_unique_folder_name,
    resolve_result_specs,
)

class DataHandlingFactory():
    """Data handling factory."""
    @staticmethod
    def create_data_handling(config_elem: Config):
        """Create data handling."""
        if config_elem.arena.get("_id") in ("abstract", "none", None):
            return DataHandling(config_elem)
        else:
            return SpaceDataHandling(config_elem)

class DataHandling():
    """Data handling."""
    SPIN_FIELD_ORDER = ("states", "angles", "external_field", "avg_direction_of_activity")

    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        results_cfg = config_elem.results or {}
        base_path = results_cfg.get("base_path") or DEFAULT_RESULTS_BASE
        self.agent_specs, self.group_specs = resolve_result_specs(results_cfg)
        self.base_dump_enabled = "base" in self.agent_specs
        self.spin_dump_enabled = "spin_model" in self.agent_specs
        self.graph_messages_enabled = "graphs" in self.group_specs or "graph_messages" in self.group_specs
        self.graph_detection_enabled = "graphs" in self.group_specs or "graph_detection" in self.group_specs
        self.snapshots_per_second = self._parse_snapshot_rate(results_cfg.get("snapshots_per_second", 1))
        base_root = Path(base_path).expanduser().resolve()
        base_root.mkdir(parents=True, exist_ok=True)
        folder_base = derive_experiment_folder_basename(
            config_elem, agent_specs=self.agent_specs, group_specs=self.group_specs
        )
        folder_override = getattr(config_elem, "output_folder_name", None)
        if folder_override:
            folder_name = folder_override
        else:
            folder_name = generate_unique_folder_name(base_root, folder_base)
        target_folder = base_root / folder_name
        target_folder.mkdir(parents=False, exist_ok=True)
        self.config_folder = str(target_folder)
        with open(target_folder / "config.json", "w") as f:
            json.dump(config_elem.__dict__, f, indent=4, default=str)
        self.agents_files = {}
        self.agent_spin_files = {}
        self.agent_name_order = []
        self.agent_lookup = {}
        self.agents_metadata = {}
        self.run_folder: str | None = None
        self._ticks_per_second = 1
        self._snapshot_offsets = [1]
        self._last_snapshot_tick = None
        self._graph_step_dirs = {}
        self._graphs_root = None
        self.hierarchy_enabled = bool(getattr(config_elem, "arena", {}).get("hierarchy"))

    def _parse_snapshot_rate(self, value):
        """Return a valid snapshot count per simulated second."""
        try:
            rate = int(value)
        except (TypeError, ValueError):
            rate = 1
        return max(1, min(2, rate))

    def _sanitize_tick_rate(self, ticks_per_second):
        """Ensure ticks per second is a positive integer."""
        try:
            value = int(ticks_per_second)
        except (TypeError, ValueError):
            value = 1
        return max(1, value)

    def _build_snapshot_offsets(self, ticks_per_second: int):
        """Return the list of tick offsets (within a second) where snapshots are taken."""
        ticks_per_second = max(1, ticks_per_second)
        offsets = set()
        for slot in range(1, self.snapshots_per_second + 1):
            raw = round(slot * ticks_per_second / self.snapshots_per_second)
            offsets.add(max(1, min(ticks_per_second, raw)))
        offsets.add(ticks_per_second)
        return sorted(offsets)

    def _prepare_graph_dirs(self):
        """Initialize per-step graph folders if requested."""
        if not self.run_folder:
            return
        self._graph_step_dirs = {}
        self._graphs_root = None
        if not (self.graph_messages_enabled or self.graph_detection_enabled):
            return
        graphs_root = os.path.join(self.run_folder, "graphs")
        os.makedirs(graphs_root, exist_ok=True)
        self._graphs_root = graphs_root
        if self.graph_messages_enabled:
            msg_dir = os.path.join(graphs_root, "messages")
            os.makedirs(msg_dir, exist_ok=True)
            self._graph_step_dirs["messages"] = msg_dir
        if self.graph_detection_enabled:
            det_dir = os.path.join(graphs_root, "detection")
            os.makedirs(det_dir, exist_ok=True)
            self._graph_step_dirs["detection"] = det_dir

    def _update_tick_rate(self, ticks_per_second):
        """Update the cached tick rate and snapshot schedule when needed."""
        if ticks_per_second is None:
            return
        sanitized = self._sanitize_tick_rate(ticks_per_second)
        if sanitized != self._ticks_per_second:
            self._ticks_per_second = sanitized
            self._snapshot_offsets = self._build_snapshot_offsets(self._ticks_per_second)

    def _should_capture_tick(self, tick: int, force: bool = False) -> bool:
        """Return True if the current tick should be captured."""
        if force:
            return True
        if tick is None:
            return False
        if tick <= 0:
            return False
        offsets = self._snapshot_offsets or [self._ticks_per_second]
        position_in_second = ((tick - 1) % max(1, self._ticks_per_second)) + 1
        return position_in_second in offsets

    def _finalize_graph_archives(self):
        """Zip per-step graph files (if any) and clean temporary folders."""
        if not self.run_folder:
            return
        for mode, dir_path in list(self._graph_step_dirs.items()):
            if not os.path.isdir(dir_path):
                continue
            archive_path = os.path.join(self.run_folder, f"{mode}_graphs.zip")
            if os.path.exists(archive_path):
                os.remove(archive_path)
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                for root, _, files in os.walk(dir_path):
                    for filename in sorted(files):
                        abs_path = os.path.join(root, filename)
                        arcname = os.path.relpath(abs_path, self.run_folder)
                        zf.write(abs_path, arcname)
            shutil.rmtree(dir_path)
        if self._graphs_root and os.path.isdir(self._graphs_root) and not os.listdir(self._graphs_root):
            os.rmdir(self._graphs_root)
        self._graph_step_dirs = {}
        self._graphs_root = None

    def new_run(self, run: int, shapes, spins, metadata, ticks_per_second: int | None = None):
        """Create a new run."""
        self.run_folder = os.path.join(self.config_folder, f"run_{run}")
        if os.path.exists(self.run_folder):
            raise Exception(f"Error run folder {self.run_folder} already present")
        os.mkdir(self.run_folder)
        self.agents_files = {}
        self.agent_spin_files = {}
        self.agent_name_order = []
        self.agent_lookup = {}
        self.agents_metadata = metadata or {}
        self._ticks_per_second = self._sanitize_tick_rate(ticks_per_second)
        self._snapshot_offsets = self._build_snapshot_offsets(self._ticks_per_second)
        self._last_snapshot_tick = None
        self._prepare_graph_dirs()

    def save(self, shapes, spins, metadata, tick: int, ticks_per_second: int | None = None, force: bool = False):
        """Save value (override in subclasses)."""
        _ = (shapes, spins, metadata, tick, ticks_per_second, force)

    def close(self, shapes):
        """Close the component resources."""
        self._archive_run_folder()

    def _archive_run_folder(self):
        """Compress the current run folder and remove its original contents."""
        if self.run_folder is None or not os.path.isdir(self.run_folder):
            return
        zip_path = f"{self.run_folder}.zip"
        if os.path.exists(zip_path):
            os.remove(zip_path)
        base_dir = os.path.dirname(self.run_folder)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for root, _, files in os.walk(self.run_folder):
                for filename in files:
                    abs_path = os.path.join(root, filename)
                    arcname = os.path.relpath(abs_path, base_dir)
                    zf.write(abs_path, arcname)
        shutil.rmtree(self.run_folder)
        self.run_folder = None

class SpaceDataHandling(DataHandling):
    """Space data handling."""
    def __init__(self, config_elem: Config):
        """Initialize the instance."""
        super().__init__(config_elem)

    def new_run(self, run: int, shapes, spins, metadata, ticks_per_second: int | None = None):
        """Create a new run."""
        super().new_run(run, shapes, spins, metadata, ticks_per_second)
        self.agent_name_order = []
        self.agent_lookup = {}
        if not self.run_folder:
            raise RuntimeError("run_folder not initialized")
        if shapes is not None:
            for key, entities in shapes.items():
                for idx, entity in enumerate(entities):
                    agent_id = self._agent_identifier(key, idx, entity)
                    self.agent_lookup[(key, idx)] = agent_id
                    if agent_id not in self.agent_name_order:
                        self.agent_name_order.append(agent_id)
                    if self.base_dump_enabled:
                        file_path = os.path.join(self.run_folder, f"{agent_id}.pkl")
                        if os.path.exists(file_path):
                            raise Exception(f"Error: file {file_path} already exists")
                        file_handle = open(file_path, "wb")
                        pickler = pickle.Pickler(file_handle, protocol=pickle.HIGHEST_PROTOCOL)
                        header = ["tick", "pos x", "pos y", "pos z"]
                        if self.hierarchy_enabled:
                            header.append("hierarchy_node")
                        pickler.dump({"type": "header", "value": header, "columns": header})
                        self.agents_files[(key, idx)] = {"handle": file_handle, "pickler": pickler, "columns": header}
                    if self.spin_dump_enabled:
                        spin_path = os.path.join(self.run_folder, f"{agent_id}_spins.pkl")
                        if os.path.exists(spin_path):
                            raise Exception(f"Error: file {spin_path} already exists")
                        spin_handle = open(spin_path, "wb")
                        spin_pickler = pickle.Pickler(spin_handle, protocol=pickle.HIGHEST_PROTOCOL)
                        spin_payload = self._resolve_spin_entry((spins or {}).get(key), idx)
                        spin_columns = ["tick"]
                        if isinstance(spin_payload, dict):
                            spin_columns.extend(list(spin_payload.keys()))
                        else:
                            spin_columns.extend(self.SPIN_FIELD_ORDER)
                        spin_pickler.dump({"type": "header", "value": spin_columns, "columns": spin_columns})
                        self.agent_spin_files[(key, idx)] = {"handle": spin_handle, "pickler": spin_pickler, "columns": spin_columns}
        self.agents_metadata = metadata or {}
        # Capture the bootstrap snapshot (tick 0) right away.
        if self.base_dump_enabled or self.spin_dump_enabled or self.graph_messages_enabled or self.graph_detection_enabled:
            self.save(shapes, spins, metadata, tick=0, ticks_per_second=self._ticks_per_second, force=True)

    def save(self, shapes, spins, metadata, tick: int, ticks_per_second: int | None = None, force: bool = False):
        """Save sampled data for the current tick."""
        if not (self.base_dump_enabled or self.spin_dump_enabled or self.graph_messages_enabled or self.graph_detection_enabled):
            return
        self._update_tick_rate(ticks_per_second)
        if tick is None:
            return
        spin_data = spins or {}
        self.agents_metadata = metadata or self.agents_metadata
        if self._last_snapshot_tick == tick:
            if not force:
                return
            # Already stored this tick; nothing else to do.
            return
        capture = self._should_capture_tick(tick, force=force)
        if not capture:
            return
        if self.base_dump_enabled and shapes is not None:
            for key, entities in shapes.items():
                for idx, entity in enumerate(entities):
                    entry = self.agents_files.get((key, idx))
                    if not entry:
                        continue
                    com = entity.center_of_mass()
                    row = {
                        "tick": tick,
                        "pos x": com.x,
                        "pos y": com.y,
                        "pos z": com.z
                    }
                    if self.hierarchy_enabled:
                        row["hierarchy_node"] = self._resolve_hierarchy_node(entity)
                    entry["pickler"].dump({"type": "row", "value": row})
        if self.spin_dump_enabled and self.agent_spin_files:
            for (key, idx), spin_entry in self.agent_spin_files.items():
                spin_values = self._resolve_spin_entry(spin_data.get(key), idx)
                row: dict[str, object] = {"tick": tick}
                if isinstance(spin_values, dict):
                    row.update(spin_values)
                spin_entry["pickler"].dump({"type": "row", "value": row})
        self._write_graph_snapshot(shapes, tick)
        self._last_snapshot_tick = tick

    def close(self, shapes):
        """Close the component resources."""
        if self.agents_files:
            for entry in self.agents_files.values():
                entry["handle"].flush()
                entry["handle"].close()
            self.agents_files.clear()
        if self.agent_spin_files:
            for entry in self.agent_spin_files.values():
                entry["handle"].flush()
                entry["handle"].close()
            self.agent_spin_files.clear()
        self._finalize_graph_archives()
        super().close(shapes)

    def _agent_identifier(self, key, idx, shape_obj):
        """Return a stable agent identifier for file names."""
        if shape_obj is not None:
            metadata = getattr(shape_obj, "metadata", None)
            if isinstance(metadata, dict):
                name = metadata.get("entity_name")
                if name:
                    return name
        return f"{key}_{idx}"

    def _resolve_spin_entry(self, spin_group, idx):
        """Return the spin payload for the given agent, normalized as a dict."""
        if not spin_group or idx >= len(spin_group):
            return None
        payload = spin_group[idx]
        if payload is None:
            return None
        if isinstance(payload, dict):
            return {str(k): payload.get(k) for k in payload.keys()}
        if isinstance(payload, (list, tuple)):
            normalized = {}
            for pos, key in enumerate(self.SPIN_FIELD_ORDER):
                if pos < len(payload):
                    normalized[key] = payload[pos]
            return normalized if normalized else None
        return {"states": payload}

    def _resolve_hierarchy_node(self, entity):
        """Return the hierarchy node identifier for the provided entity, if any."""
        metadata = getattr(entity, "metadata", None)
        if not isinstance(metadata, dict):
            return None
        node = metadata.get("hierarchy_node")
        if node is None:
            return None
        return str(node)

    def _write_graph_snapshot(self, shapes, tick: int):
        """Persist per-step adjacency graphs (messages/detection)."""
        if not shapes:
            return
        if not (self.graph_messages_enabled or self.graph_detection_enabled):
            return
        if tick is None:
            return
        metadata = self.agents_metadata or {}
        agents = []
        for key, entities in shapes.items():
            group_meta = metadata.get(key, [])
            for idx, entity in enumerate(entities):
                agent_id = self.agent_lookup.get((key, idx))
                if not agent_id:
                    agent_id = self._agent_identifier(key, idx, entity)
                    self.agent_lookup[(key, idx)] = agent_id
                    if agent_id not in self.agent_name_order:
                        self.agent_name_order.append(agent_id)
                center = entity.center_of_mass()
                entry_meta = group_meta[idx] if idx < len(group_meta) else {}
                agents.append((agent_id, center, entry_meta))
        for mode in ("messages", "detection"):
            if mode == "messages" and not self.graph_messages_enabled:
                continue
            if mode == "detection" and not self.graph_detection_enabled:
                continue
            dir_path = self._graph_step_dirs.get(mode)
            if not dir_path:
                continue
            edges = self._compute_graph_edges(mode, agents)
            filename = os.path.join(dir_path, f"step_{tick:09d}.pkl")
            with open(filename, "wb") as fh:
                rows = [{"source": name, "target": name} for name in self.agent_name_order]
                rows.extend({"source": src, "target": dst} for src, dst in edges)
                payload = {
                    "mode": mode,
                    "tick": tick,
                    "columns": ["source", "target"],
                    "rows": rows,
                    "description": "Two-column edge list (self loops + directed edges)."
                }
                pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

    def _compute_graph_edges(self, mode: str, agents):
        """Compute adjacency edges for the requested mode."""
        edges = set()
        for i, (name_a, pos_a, meta_a) in enumerate(agents):
            for j, (name_b, pos_b, meta_b) in enumerate(agents):
                if i == j:
                    continue
                distance = math.dist((pos_a.x, pos_a.y), (pos_b.x, pos_b.y))
                if mode == "messages":
                    if self._can_message(meta_a, meta_b, distance):
                        edges.add((name_a, name_b))
                else:
                    if self._can_detect(meta_a, distance):
                        edges.add((name_a, name_b))
        return sorted(edges)

    @staticmethod
    def _can_message(meta_src, meta_dst, distance):
        """Return True if the source metadata allows messaging another agent at the given distance."""
        if not meta_src or not meta_src.get("msg_enable"):
            return False
        if not meta_dst:
            return False
        try:
            rng = float(meta_src.get("msg_comm_range", 0.0))
        except (TypeError, ValueError):
            rng = 0.0
        if rng <= 0:
            return False
        try:
            tx_rate = float(meta_src.get("msg_tx_rate", 0.0))
        except (TypeError, ValueError):
            tx_rate = 0.0
        if tx_rate <= 0.0:
            return False
        try:
            rx_rate = float(meta_dst.get("msg_rx_rate", 0.0))
        except (TypeError, ValueError):
            rx_rate = 0.0
        if rx_rate <= 0.0:
            return False
        return math.isinf(rng) or distance <= rng

    @staticmethod
    def _can_detect(meta, distance):
        """Return True if detection metadata allows sensing at the given distance."""
        if not meta:
            return False
        try:
            rng = float(meta.get("detection_range", 0.1))
        except (TypeError, ValueError):
            rng = 0.1
        if rng <= 0:
            return False
        try:
            freq = float(meta.get("detection_frequency", math.inf))
        except (TypeError, ValueError):
            freq = 0.0
        if freq <= 0.0:
            return False
        return math.isinf(rng) or distance <= rng
