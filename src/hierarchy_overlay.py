# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Hierarchy overlay utilities for arenas and flat objects."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sim.hierarchy")


class Bounds2D:
    """Axis-aligned 2D bounds (x/y only)."""

    __slots__ = ("x_min", "y_min", "x_max", "y_max")

    def __init__(self, x_min: float, y_min: float, x_max: float, y_max: float):
        """Initialize the instance."""
        self.x_min = float(x_min)
        self.y_min = float(y_min)
        self.x_max = float(x_max)
        self.y_max = float(y_max)

    def contains(self, x: float, y: float) -> bool:
        """Return True if the point (x, y) lies inside these bounds."""
        return (self.x_min <= x <= self.x_max) and (self.y_min <= y <= self.y_max)

    def split(self, branches: int) -> List["Bounds2D"]:
        """
        Split the bounds into `branches` children.

        branches=1: return [self]
        branches=2: split along the longest axis into 2 children
        branches=4: split into a 2x2 grid
        """
        if branches <= 1:
            return [self]

        x_mid = 0.5 * (self.x_min + self.x_max)
        y_mid = 0.5 * (self.y_min + self.y_max)

        if branches == 2:
            width = self.x_max - self.x_min
            height = self.y_max - self.y_min
            if width >= height:
                # Split vertically (left / right).
                return [
                    Bounds2D(self.x_min, self.y_min, x_mid, self.y_max),
                    Bounds2D(x_mid, self.y_min, self.x_max, self.y_max),
                ]
            else:
                # Split horizontally (bottom / top).
                return [
                    Bounds2D(self.x_min, self.y_min, self.x_max, y_mid),
                    Bounds2D(self.x_min, y_mid, self.x_max, self.y_max),
                ]

        if branches == 4:
            return [
                Bounds2D(self.x_min, self.y_min, x_mid, y_mid),
                Bounds2D(x_mid, self.y_min, self.x_max, y_mid),
                Bounds2D(self.x_min, y_mid, x_mid, self.y_max),
                Bounds2D(x_mid, y_mid, self.x_max, self.y_max),
            ]

        # Fallback: no split if an unsupported branching factor is requested.
        logger.warning("Unsupported branches=%s in Bounds2D.split; returning single cell", branches)
        return [self]


class HierarchyNode:
    """Single node in a hierarchy overlay."""

    __slots__ = ("node_id", "bounds", "level", "order", "parent_id", "children_ids")

    def __init__(
        self,
        node_id: str,
        bounds: Bounds2D,
        level: int,
        order: int,
        parent_id: Optional[str],
        children_ids: Optional[List[str]] = None
    ):
        """Initialize the instance."""
        self.node_id = node_id
        self.bounds = bounds
        self.level = int(level)
        self.order = int(order)
        self.parent_id = parent_id
        self.children_ids: List[str] = list(children_ids or [])


class HierarchyOverlay:
    """
    Reversed-tree partition over a 2D area.

    The overlay can be attached to:
    - the whole arena, or
    - a flat object (Bounds2D restricted to the object perimeter).

    It is intentionally generic: movement, detection and messaging layers decide
    how to use it, based on the `information_scope` configuration.
    """

    def __init__(
        self,
        bounds: Bounds2D,
        depth: int = 0,
        branches: int = 1,
        owner_id: Optional[str] = None,
        info_scope_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize the instance."""
        if depth < 0:
            raise ValueError("Hierarchy depth cannot be negative")
        if branches not in (1, 2, 4):
            raise ValueError("Hierarchy branches must be 1, 2 or 4")

        self.bounds = bounds
        self.depth = int(depth)
        self.branches = int(branches)
        self.owner_id = owner_id

        self.nodes: Dict[str, HierarchyNode] = {}
        self.level_colors: Dict[str, Tuple[float, float, float]] = {}
        self.information_scope: Optional[Dict[str, Any]] = None

        self._build_tree()
        self._parse_information_scope(info_scope_config)

    # ------------------------------------------------------------------
    # Tree construction
    # ------------------------------------------------------------------
    def _build_tree(self) -> None:
        """Build the node tree from the root bounds."""
        order_counter = 0

        def _build(node_id: str, bounds: Bounds2D, level: int, remaining_depth: int, parent_id: Optional[str]):
            nonlocal order_counter
            order_counter += 1
            node = HierarchyNode(node_id, bounds, level, order_counter, parent_id, [])
            self.nodes[node_id] = node

            if remaining_depth <= 0 or self.branches <= 1:
                return

            child_bounds = bounds.split(self.branches)
            for idx, cb in enumerate(child_bounds):
                child_id = "%s:%d" % (node_id, idx)
                node.children_ids.append(child_id)
                _build(child_id, cb, level + 1, remaining_depth - 1, node_id)

        _build("0", self.bounds, 0, self.depth, None)
        self._build_level_colors()

    def _build_level_colors(self) -> None:
        """Assign simple colors per level for visualisation/markers."""
        base_palette = [
            (1.0, 0.0, 0.0),
            (0.0, 0.6, 0.0),
            (0.1, 0.1, 0.9),
            (0.8, 0.8, 0.0),
            (0.8, 0.0, 0.8),
            (0.0, 0.7, 0.7),
        ]
        for node_id, node in self.nodes.items():
            self.level_colors[node_id] = base_palette[node.level % len(base_palette)]

    # ------------------------------------------------------------------
    # Information scope
    # ------------------------------------------------------------------
    def _parse_information_scope(self, cfg: Optional[Dict[str, Any]]) -> None:
        """Parse the hierarchy-level information_scope config."""
        if not cfg or not isinstance(cfg, dict):
            self.information_scope = None
            return

        mode = str(cfg.get("mode", "")).strip().lower()
        direction = str(cfg.get("direction", "both")).strip().lower() or "both"
        over_raw = cfg.get("over", [])

        if mode not in {"node", "branch", "tree"}:
            logger.warning("HierarchyOverlay information_scope mode '%s' is not supported", mode)
            self.information_scope = None
            return

        if mode == "node":
            direction = "both"
        elif direction not in {"up", "down", "both", "flat"}:
            logger.warning("HierarchyOverlay information_scope direction '%s' invalid; defaulting to 'both'", direction)
            direction = "both"

        valid_channels = {"messages", "detection", "movement"}
        if isinstance(over_raw, (list, tuple, set)):
            over = {str(ch).strip().lower() for ch in over_raw}
        elif isinstance(over_raw, str):
            over = {over_raw.strip().lower()} if over_raw.strip() else set()
        else:
            over = set()

        over = over & valid_channels
        if not over:
            # If nothing valid is specified, we do not enforce overlay-based restrictions.
            self.information_scope = None
            return

        self.information_scope = {
            "mode": mode,
            "direction": direction,
            "over": over
        }

    # ------------------------------------------------------------------
    # Public helpers for geometry & hierarchy operations
    # ------------------------------------------------------------------
    def node_for_point(self, x: float, y: float) -> Optional[str]:
        """Return the deepest node that contains the given point, or None."""
        if not self.bounds.contains(x, y):
            return None
        node_id = "0"
        while True:
            node = self.nodes.get(node_id)
            if node is None or not node.children_ids:
                return node_id
            found_child = None
            for child_id in node.children_ids:
                child = self.nodes[child_id]
                if child.bounds.contains(x, y):
                    found_child = child_id
                    break
            if found_child is None:
                return node_id
            node_id = found_child

    def parent_of(self, node_id: str) -> Optional[str]:
        """Return the parent node id, or None for the root."""
        node = self.nodes.get(node_id)
        return node.parent_id if node else None

    def children_of(self, node_id: str) -> List[str]:
        """Return the direct children IDs of a node."""
        node = self.nodes.get(node_id)
        return list(node.children_ids) if node else []

    def descendants_of(self, node_id: str) -> List[str]:
        """Return all descendants (deep) of a node."""
        out: List[str] = []
        stack = [node_id]
        while stack:
            current = stack.pop()
            node = self.nodes.get(current)
            if node is None:
                continue
            for child_id in node.children_ids:
                out.append(child_id)
                stack.append(child_id)
        return out

    def path_to_root(self, node_id: str) -> List[str]:
        """Return the list of nodes from node_id up to the root (excluding node_id)."""
        out: List[str] = []
        current = node_id
        while True:
            node = self.nodes.get(current)
            if node is None or node.parent_id is None:
                break
            parent_id = node.parent_id
            out.append(parent_id)
            current = parent_id
        return out

    def to_rectangles(self) -> List[Dict[str, Any]]:
        """
        Return a list of rectangles describing the hierarchy for GUI overlay.

        Each entry is a dictionary:
        {
          "node_id": str,
          "bounds": (x_min, y_min, x_max, y_max),
          "level": int,
          "order": int,
          "color": (r, g, b)
        }
        """
        rectangles: List[Dict[str, Any]] = []
        for node_id, node in self.nodes.items():
            color = self.level_colors.get(node_id)
            rectangles.append(
                {
                    "node_id": node_id,
                    "bounds": (node.bounds.x_min, node.bounds.y_min, node.bounds.x_max, node.bounds.y_max),
                    "level": node.level,
                    "order": node.order,
                    "color": color
                }
            )
        return rectangles


class ArenaHierarchy(HierarchyOverlay):
    """Specialised overlay used for arena partitioning."""
    # Currently identical to HierarchyOverlay; kept for clarity/compatibility.
    pass
