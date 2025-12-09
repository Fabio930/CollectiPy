# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Central detection server for cross-process perception snapshots."""

from __future__ import annotations

import math, queue, time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set
from core.util.geometry_utils.vector3D import Vector3D
from core.util.geometry_utils.spatialgrid import SpatialGrid
from core.util.logging_util import get_logger, start_run_logging, shutdown_logging

logger = get_logger("detection_server")


class _AgentInfo:
    """Internal snapshot of an agent used for detection."""

    __slots__ = (
        "name",
        "manager_id",
        "pos",
        "hierarchy_node",
        "entity",
        "detection_range",
    )

    def __init__(
        self,
        name: str,
        manager_id: int,
        pos: Vector3D,
        hierarchy_node: Optional[str],
        entity: Optional[str],
        detection_range: float,
    ) -> None:
        """Initialize the instance."""
        self.name = name
        self.manager_id = int(manager_id)
        self.pos = pos
        self.hierarchy_node = hierarchy_node
        self.entity = entity
        self.detection_range = detection_range


class _GridAgent:
    """Light wrapper used by the SpatialGrid."""

    __slots__ = ("name", "_pos")

    def __init__(self, name: str, pos: Vector3D) -> None:
        """Initialize the instance."""
        self.name = name
        self._pos = pos

    def get_position(self) -> Vector3D:
        """Return the agent position."""
        return self._pos


class DetectionServer:
    """Core aggregation logic for the detection server process."""

    def __init__(
        self,
        channels: Iterable[Tuple[Any, Any]],
        log_specs: Optional[Dict[str, Any]] = None,
        process_name: str = "detection_server",
    ):
        """Initialize the instance."""
        self.channels = list(channels)
        self._log_specs = log_specs or {}
        self._process_name = process_name
        self._current_run = 0
        self._running = True
        self._agents: Dict[str, _AgentInfo] = {}

    def stop(self) -> None:
        """Request a graceful shutdown."""
        self._running = False

    def run(self) -> None:
        """Main server loop."""
        logger.info("Detection server started with %d manager channels", len(self.channels))
        try:
            while self._running:
                any_packet = False
                for manager_id, (uplink, _) in enumerate(self.channels):
                    processed = self._process_uplink(manager_id, uplink)
                    any_packet = any_packet or processed
                if not any_packet:
                    time.sleep(0.00005)
        finally:
            logger.info("Detection server shutting down")
            shutdown_logging()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _process_uplink(self, manager_id: int, uplink: Any) -> bool:
        """Drain packets from a single manager uplink."""
        processed_any = False
        while True:
            try:
                packet = uplink.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break

            if not isinstance(packet, dict):
                continue

            kind = packet.get("kind")
            if kind == "shutdown":
                self.stop()
                processed_any = True
                continue
            if kind == "run_start":
                self._handle_run_start(packet)
                processed_any = True
                continue
            if kind == "agents_snapshot":
                self._handle_agents_snapshot(packet, manager_id)
                processed_any = True
        return processed_any

    def _handle_run_start(self, packet: Dict[str, Any]) -> None:
        """Rotate detection server logging when a new run starts."""
        if not self._log_specs:
            return
        run_value = packet.get("run")
        if isinstance(run_value, (int, float, str)):
            try:
                run_num = int(run_value)
            except (TypeError, ValueError):
                return
        else:
            return
        if run_num <= self._current_run:
            return
        self._current_run = run_num
        start_run_logging(self._log_specs, self._process_name, run_num)
        logger.info("Detection server logging started for run %d", run_num)

    def _handle_agents_snapshot(self, packet: Dict[str, Any], manager_id: int) -> None:
        """Update agent registry from a snapshot packet and broadcast the merged list."""
        agents = packet.get("agents") or []
        try:
            manager_id = int(packet.get("manager_id", manager_id))
        except (TypeError, ValueError):
            manager_id = int(manager_id)

        logger.debug(
            "[DS] snapshot from manager %d: %d agents: %s",
            manager_id,
            len(agents),
            [str(a.get("uid")) for a in agents],
        )

        for info in agents:
            name = str(info.get("uid"))
            if not name:
                continue
            x = float(info.get("x", 0.0))
            y = float(info.get("y", 0.0))
            z = float(info.get("z", 0.0))
            pos = Vector3D(x, y, z)
            node = info.get("hierarchy_node")
            entity = info.get("entity")
            try:
                det_range = float(info.get("detection_range", math.inf))
            except (TypeError, ValueError):
                det_range = math.inf
            self._agents[name] = _AgentInfo(
                name,
                manager_id,
                pos,
                node,
                entity,
                det_range,
            )

        self._broadcast_detection_snapshot()

    def _broadcast_detection_snapshot(self) -> None:
        """Send the latest global agent positions to all managers."""
        if not self.channels:
            return
        grid, cell_size = self._build_grid()
        if grid is None:
            return

        for manager_idx, (_, downlink) in enumerate(self.channels):
            if downlink is None:
                continue
            visible = self._agents_visible_to_manager(manager_idx, grid)
            packet = {
                "kind": "detection_snapshot",
                "agents": visible,
                "cell_size": cell_size,
            }
            try:
                downlink.put(packet)
            except Exception:
                continue

    def _build_grid(self) -> tuple[Optional[SpatialGrid], float]:
        """Build a spatial grid with current agents."""
        finite_ranges = [
            info.detection_range
            for info in self._agents.values()
            if info.detection_range is not None and math.isfinite(info.detection_range) and info.detection_range > 0
        ]
        max_range = max(finite_ranges) if finite_ranges else 1.0
        cell_size = max(0.05, min(max_range, 2.0))
        grid = SpatialGrid(cell_size)
        for info in self._agents.values():
            grid.insert(_GridAgent(info.name, info.pos))
        return grid, cell_size

    def _agents_visible_to_manager(self, manager_id: int, grid: SpatialGrid) -> List[Dict[str, Any]]:
        """Return agent rows visible to the given manager based on detection ranges."""
        if not self._agents:
            return []
        visible_names: Set[str] = set()
        own_agents = [info for info in self._agents.values() if info.manager_id == manager_id]
        if not own_agents:
            return []
        for observer in own_agents:
            rng = observer.detection_range
            if rng is None or rng <= 0:
                continue
            if math.isinf(rng):
                visible_names.update(self._agents.keys())
                break
            neighbors = grid.neighbors(_GridAgent(observer.name, observer.pos), rng)
            for neigh in neighbors:
                if neigh.name == observer.name:
                    continue
                visible_names.add(neigh.name)
        snapshot: List[Dict[str, Any]] = []
        for name in visible_names:
            info = self._agents.get(name)
            if info is None:
                continue
            snapshot.append(
                {
                    "uid": info.name,
                    "entity": info.entity,
                    "x": info.pos.x,
                    "y": info.pos.y,
                    "z": info.pos.z,
                    "hierarchy_node": info.hierarchy_node,
                }
            )
        return snapshot


def run_detection_server(
    channels: Iterable[Tuple[Any, Any]],
    log_specs: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience function used as a multiprocessing target."""
    server = DetectionServer(list(channels), log_specs=log_specs, process_name="detection_server")
    server.run()
