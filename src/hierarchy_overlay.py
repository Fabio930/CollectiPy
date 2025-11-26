# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Bounds2D:
    """Axis-aligned bounding box used for hierarchy nodes."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        """Provide the width."""
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        """Provide the height."""
        return max(0.0, self.max_y - self.min_y)

    def clamp(self, x: float, y: float, padding: float = 0.0) -> Tuple[float, float]:
        """Clamp coordinates inside the box while keeping an optional padding margin."""
        safe_min_x = self.min_x + padding
        safe_max_x = self.max_x - padding
        safe_min_y = self.min_y + padding
        safe_max_y = self.max_y - padding
        # If the padding is too large keep the point at the cell centroid.
        if safe_min_x > safe_max_x:
            safe_min_x = safe_max_x = 0.5 * (self.min_x + self.max_x)
        if safe_min_y > safe_max_y:
            safe_min_y = safe_max_y = 0.5 * (self.min_y + self.max_y)
        clamped_x = min(max(x, safe_min_x), safe_max_x)
        clamped_y = min(max(y, safe_min_y), safe_max_y)
        return clamped_x, clamped_y

    def serialize(self) -> Tuple[float, float, float, float]:
        """Provide the serialize."""
        return (self.min_x, self.min_y, self.max_x, self.max_y)


@dataclass
class HierarchyNode:
    """Hierarchy node."""
    node_id: str
    level: int
    bounds: Optional[Bounds2D]
    parent_id: Optional[str]
    order: int = 0
    color: Optional[str] = None
    children: List[str] = field(default_factory=list)


class HierarchyOverlay:
    """
    Utility class generating a reversed-tree partition of an arena or flat objects.

    Nodes are identified using dot-separated paths starting from "0" (root).
    When spatial bounds are available each level subdivides the parent cell
    into equally-sized, adjacent rectangles (branching factor 2 or 4).
    """

    _SUPPORTED_BRANCHES = (1, 2, 4)

    def __init__(self, bounds: Optional[Bounds2D], depth: int = 0, branches: int = 1):
        """Initialize the instance."""
        depth = max(0, int(depth))
        branches = int(branches)
        if branches not in self._SUPPORTED_BRANCHES:
            raise ValueError(f"Hierarchy branches must be one of {self._SUPPORTED_BRANCHES}, got {branches}")
        self.depth = depth
        self.branches = branches
        self.nodes: Dict[str, HierarchyNode] = {}
        root = HierarchyNode(node_id="0", level=0, bounds=bounds, parent_id=None, order=0)
        self.nodes[root.node_id] = root
        if self.depth > 0 and self.branches > 1:
            self._build_children(root, 1)
        self._assign_level_colors()

    def get_root_id(self) -> str:
        """Return the root id."""
        return "0"

    def _build_children(self, parent: HierarchyNode, level: int) -> None:
        """Build children."""
        if level > self.depth:
            return
        sub_bounds = self._split_bounds(parent.bounds)
        for idx in range(self.branches):
            bounds = sub_bounds[idx] if idx < len(sub_bounds) else parent.bounds
            child_id = f"{parent.node_id}.{idx}"
            child = HierarchyNode(
                node_id=child_id,
                level=parent.level + 1,
                bounds=bounds,
                parent_id=parent.node_id,
                order=idx
            )
            self.nodes[child_id] = child
            parent.children.append(child_id)
            if level < self.depth and self.branches > 1:
                self._build_children(child, level + 1)

    def _assign_level_colors(self):
        """Assign the level colors."""
        max_level = self.max_level()
        palette = self._build_palette(max_level + 1 if max_level >= 0 else 1)
        self.level_colors: Dict[int, str] = {}
        for level in range(max_level + 1):
            self.level_colors[level] = palette[min(level, len(palette) - 1)]
        for node in self.nodes.values():
            node.color = self.level_colors.get(node.level)

    def _build_palette(self, count: int) -> List[str]:
        """Build palette."""
        base_palette = [
            "#1b9e77",
            "#d95f02",
            "#7570b3",
            "#e7298a",
            "#66a61e",
            "#e6ab02",
            "#a6761d",
            "#666666",
            "#F15050",
            "#b2df8a",
            "#fb9a99",
            "#8da0cb",
        ]
        palette = []
        idx = 0
        while len(palette) < count and idx < len(base_palette):
            palette.append(base_palette[idx])
            idx += 1
        if len(palette) >= count:
            return palette
        import colorsys
        golden_ratio = 0.61803398875
        hue = 0.0
        while len(palette) < count:
            hue = (hue + golden_ratio) % 1.0
            rgb = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(rgb[0] * 255),
                int(rgb[1] * 255),
                int(rgb[2] * 255)
            )
            if hex_color not in palette:
                palette.append(hex_color)
        return palette

    def _split_bounds(self, bounds: Optional[Bounds2D]) -> List[Optional[Bounds2D]]:
        """Split the bounds."""
        if bounds is None:
            return [None for _ in range(self.branches)]
        if self.branches == 1:
            return [bounds]
        if self.branches == 2:
            if bounds.width >= bounds.height:
                mid_x = 0.5 * (bounds.min_x + bounds.max_x)
                return [
                    Bounds2D(bounds.min_x, bounds.min_y, mid_x, bounds.max_y),
                    Bounds2D(mid_x, bounds.min_y, bounds.max_x, bounds.max_y),
                ]
            mid_y = 0.5 * (bounds.min_y + bounds.max_y)
            return [
                Bounds2D(bounds.min_x, bounds.min_y, bounds.max_x, mid_y),
                Bounds2D(bounds.min_x, mid_y, bounds.max_x, bounds.max_y),
            ]
        # self.branches == 4
        mid_x = 0.5 * (bounds.min_x + bounds.max_x)
        mid_y = 0.5 * (bounds.min_y + bounds.max_y)
        return [
            Bounds2D(bounds.min_x, bounds.min_y, mid_x, mid_y),      # bottom-left
            Bounds2D(mid_x, bounds.min_y, bounds.max_x, mid_y),      # bottom-right
            Bounds2D(bounds.min_x, mid_y, mid_x, bounds.max_y),      # top-left
            Bounds2D(mid_x, mid_y, bounds.max_x, bounds.max_y),      # top-right
        ]

    def get_node(self, node_id: str) -> Optional[HierarchyNode]:
        """Return the node."""
        return self.nodes.get(node_id)

    def get_bounds(self, node_id: str) -> Optional[Bounds2D]:
        """Return the bounds."""
        node = self.get_node(node_id)
        if not node:
            return None
        return node.bounds

    def get_level_color(self, level: int) -> Optional[str]:
        """Return the level color."""
        if not hasattr(self, "level_colors"):
            return None
        return self.level_colors.get(level)

    def get_node_number(self, node_id: str) -> Optional[int]:
        """Return the node number."""
        node = self.get_node(node_id)
        if not node:
            return None
        return node.order

    def level_of(self, node_id: str) -> Optional[int]:
        """Level of."""
        node = self.get_node(node_id)
        if not node:
            return None
        return node.level

    def clamp_point(self, node_id: str, x: float, y: float, padding: float = 0.0) -> Tuple[float, float]:
        """Clamp the point."""
        node = self.get_node(node_id)
        if not node or not node.bounds:
            return x, y
        return node.bounds.clamp(x, y, padding=padding)

    def nodes_at_level(self, level: int) -> List[HierarchyNode]:
        """Nodes at level."""
        return [node for node in self.nodes.values() if node.level == level]

    def levels(self) -> Iterable[int]:
        """Provide the levels."""
        return sorted({node.level for node in self.nodes.values()})

    def to_rectangles(self, include_root: bool = False) -> List[dict]:
        """
        Return a serialisable description of the hierarchy.

        Each entry contains the bounding rectangle (if available) and its level.
        """
        output = []
        for node in self.nodes.values():
            if node.bounds is None:
                continue
            if node.level == 0 and not include_root:
                continue
            output.append({
                "id": node.node_id,
                "level": node.level,
                "bounds": node.bounds.serialize(),
                "color": node.color,
                "number": node.order
            })
        return sorted(output, key=lambda item: (item["level"], item["id"]))

    def max_level(self) -> int:
        """Max level."""
        if not self.nodes:
            return 0
        return max(node.level for node in self.nodes.values())

    def parent_of(self, node_id: str) -> Optional[str]:
        """Return the of."""
        node = self.get_node(node_id)
        if not node:
            return None
        return node.parent_id

    def children_of(self, node_id: str) -> List[str]:
        """Return the of."""
        node = self.get_node(node_id)
        if not node:
            return []
        return list(node.children)

    def neighbors(self, node_id: str) -> List[str]:
        """Return the operation."""
        neigh = []
        parent = self.parent_of(node_id)
        if parent is not None:
            neigh.append(parent)
        neigh.extend(self.children_of(node_id))
        return neigh

    def descendants_of(self, node_id: str, include_self: bool = False) -> List[str]:
        """Return all descendant nodes (optionally including the starting node)."""
        if node_id not in self.nodes:
            return []
        descendants: List[str] = []
        queue: List[str] = list(self.children_of(node_id))
        while queue:
            current = queue.pop(0)
            descendants.append(current)
            queue.extend(self.children_of(current))
        if include_self:
            descendants.insert(0, node_id)
        return descendants

    def path_to_root(self, node_id: str) -> List[str]:
        """Return the to root."""
        path = []
        node = self.get_node(node_id)
        while node:
            path.append(node.node_id)
            if node.parent_id is None:
                break
            node = self.get_node(node.parent_id)
        return path

    def path_between(self, start_id: str, end_id: str) -> List[str]:
        """Return the between."""
        if start_id == end_id:
            return [start_id]
        start_path = self.path_to_root(start_id)
        end_path = self.path_to_root(end_id)
        if not start_path or not end_path:
            return []
        start_set = {node_id: idx for idx, node_id in enumerate(start_path)}
        lca = None
        lca_idx = None
        for idx, node_id in enumerate(end_path):
            if node_id in start_set:
                lca = node_id
                lca_idx = idx
                break
        if lca is None:
            return []
        # path from start to LCA (inclusive)
        start_to_lca = start_path[: start_set[lca] + 1]
        # path from LCA to end (exclusive of LCA to avoid duplication)
        lca_to_end = list(reversed(end_path[: lca_idx]))
        return start_to_lca + lca_to_end

    def is_adjacent(self, source_id: str, target_id: str) -> bool:
        """Is adjacent."""
        if source_id == target_id:
            return True
        parent = self.parent_of(source_id)
        if parent == target_id:
            return True
        parent_target = self.parent_of(target_id)
        if parent_target == source_id:
            return True
        return False

    def locate_path(self, x: float, y: float, include_root: bool = True) -> List[str]:
        """Locate the path."""
        root = self.get_node(self.get_root_id())
        if not root or not root.bounds:
            return []
        if not self._contains(root.bounds, x, y):
            return []
        path = [root.node_id] if include_root else []
        current = root
        while current.children:
            next_child = None
            for child_id in current.children:
                child = self.get_node(child_id)
                if child and child.bounds and self._contains(child.bounds, x, y):
                    next_child = child
                    break
            if not next_child:
                break
            path.append(next_child.node_id)
            current = next_child
        return path

    def locate_node(self, x: float, y: float, include_root: bool = True) -> Optional[str]:
        """Locate the node."""
        path = self.locate_path(x, y, include_root=include_root)
        if not path:
            return None
        return path[-1]

    @staticmethod
    def _contains(bounds: Bounds2D, x: float, y: float) -> bool:
        """Provide the contains."""
        return bounds.min_x <= x <= bounds.max_x and bounds.min_y <= y <= bounds.max_y
