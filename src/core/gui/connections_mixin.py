# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Connection overlays and graph helpers."""
from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Qt


class ConnectionsMixin:
    """Mixin that manages selection, graphs, and overlays."""

    clicked_spin: Any
    agents_metadata: dict
    agents_shapes: dict
    graph_views: dict
    graph_view_active: bool
    graph_filter_mode: str
    graph_filter_selector: Any
    graph_filter_widget: Any
    graph_window: Any
    view_mode_selector: Any
    connection_colors: dict
    on_click_modes: set
    show_modes: set
    legend_widget: Any
    legend_column: Any
    _graph_filter_labels: dict
    _graph_layout_coords: dict
    _static_layout_cache: dict
    _static_layout_ids: list
    _graph_index_map: dict
    _agent_centers: dict
    connection_lookup: dict
    connection_graphs: dict
    _camera_lock: Any
    spin_window: Any
    spin_panel_visible: bool
    _panel_extra_padding: dict
    scale: float
    offset_x: float
    offset_y: float
    is_abstract: bool

    def _normalize_agent_id(self, agent_key):
        """Return a hashable (group, index) tuple for a selected agent."""
        if agent_key is None:
            return None
        if isinstance(agent_key, (list, tuple)):
            normalized = tuple(agent_key)
        else:
            try:
                normalized = tuple(agent_key)
            except Exception:
                return None
        if len(normalized) != 2:
            return None
        try:
            hash(normalized)
        except TypeError:
            normalized = tuple(
                tuple(item) if isinstance(item, list) else item
                for item in normalized
            )
            try:
                hash(normalized)
            except TypeError:
                return None
        return normalized

    def _handle_agent_selection(self, agent_key, double_click=False):
        """Handle agent selection regardless of source."""
        normalized_key = self._normalize_agent_id(agent_key)
        if normalized_key is None:
            self._clear_selection()
            return
        if normalized_key == self.clicked_spin and not double_click:
            self._clear_selection()
            return
        self.clicked_spin = normalized_key
        self._show_spin_canvas()
        self.update_spins_plot()
        self._update_connection_legend()
        self._update_graph_filter_controls()
        self._update_graph_views()
        self.update_scene()
        if double_click:
            self._focus_on_agent(normalized_key, force=True, lock=True)
        else:
            self._unlock_camera()
            self._focus_on_agent(normalized_key, force=False, lock=False)

    def _handle_graph_agent_selection(self, agent_key, double_click=False):
        """Handle agent selection triggered from the graph windows."""
        self._refresh_agent_centers()
        self._handle_agent_selection(agent_key, double_click=double_click)

    def _show_spin_canvas(self):
        """Ensure the spin plot canvas is visible."""
        if not getattr(self, "show_spins_enabled", False) or self.spin_window is None or self.spin_panel_visible:
            return
        self.spin_panel_visible = True
        self._update_side_container_visibility()

    def _hide_spin_canvas(self):
        """Hide the spin plot canvas if it is visible."""
        if not getattr(self, "show_spins_enabled", False) or not self.spin_panel_visible or self.spin_window is None:
            return
        self.spin_panel_visible = False
        self._update_side_container_visibility()

    def _update_connection_legend(self):
        """Update the legend describing the connection overlays."""
        if not self.legend_widget:
            return
        if not self.clicked_spin:
            self.legend_widget.update_entries(self._default_connection_entries())
            self._update_legend_column_visibility()
            self._update_side_container_visibility()
            return
        meta = self._get_metadata_for_agent(self.clicked_spin)
        if not meta:
            self.legend_widget.update_entries(self._default_connection_entries())
            self._update_legend_column_visibility()
            self._update_side_container_visibility()
            return
        entries = []
        detection_requested = "detection" in (self.on_click_modes | self.show_modes)
        message_requested = "messages" in (self.on_click_modes | self.show_modes)
        if detection_requested:
            detection_label = str(meta.get("detection_type") or "Detection").strip()
            if detection_label:
                entries.append((self.connection_colors["detection"], detection_label))
        if message_requested and meta.get("msg_enable"):
            msg_label = "Messaging"
            msg_type = str(meta.get("msg_type") or "").strip()
            msg_kind = str(meta.get("msg_kind") or "").strip()
            descriptors = []
            if msg_type:
                descriptors.append(msg_type.capitalize())
            if msg_kind:
                descriptors.append(msg_kind.capitalize())
            if descriptors:
                msg_label = f"{msg_label} {' '.join(descriptors)}"
            entries.append((self.connection_colors["messages"], msg_label))
        self.legend_widget.update_entries(entries)
        self._update_legend_column_visibility()
        self._update_side_container_visibility()

    def _default_connection_entries(self):
        """Return default legend entries describing connection colors."""
        entries = []
        active_modes = self.on_click_modes | self.show_modes
        if "detection" in active_modes:
            entries.append((self.connection_colors["detection"], "Detection"))
        if "messages" in active_modes:
            entries.append((self.connection_colors["messages"], "Messaging"))
        return entries

    def _get_metadata_for_agent(self, agent_key):
        """Return metadata entry for the given agent id tuple."""
        if not agent_key or self.agents_metadata is None:
            return None
        group_meta = self.agents_metadata.get(agent_key[0])
        if not group_meta:
            return None
        idx = agent_key[1]
        if idx is None or idx >= len(group_meta):
            return None
        return group_meta[idx]

    def _update_graph_filter_controls(self):
        """Show or hide the graph filter switch based on the selection state."""
        if not self.graph_filter_widget or not self.graph_filter_selector:
            return
        graph_visible = bool(self.graph_views and self.graph_view_active)
        self.graph_filter_widget.setVisible(graph_visible)
        has_selection = bool(self.clicked_spin and graph_visible)
        self.graph_filter_selector.setEnabled(has_selection)
        if not has_selection:
            if self.graph_filter_mode != "direct":
                self.graph_filter_mode = "direct"
            self._set_graph_filter_label(global_mode=True)
            self.graph_filter_selector.blockSignals(True)
            self.graph_filter_selector.setCurrentIndex(0)
            self.graph_filter_selector.blockSignals(False)
        else:
            self._set_graph_filter_label(global_mode=False)
            self.graph_filter_selector.blockSignals(True)
            # Default to local view when a selection is made.
            self.graph_filter_selector.setCurrentIndex(0)
            self.graph_filter_selector.blockSignals(False)
            if self.view_mode_selector and self.view_mode_selector.isEnabled():
                # If the graphs were hidden, move to static view on selection.
                if self.view_mode_selector.currentIndex() == 0:
                    self.view_mode_selector.blockSignals(True)
                    self.view_mode_selector.setCurrentIndex(1)
                    self.view_mode_selector.blockSignals(False)

    def _update_side_container_visibility(self):
        """Update the visibility of the auxiliary side container."""
        if not self.spin_window:
            return
        if self.spin_panel_visible:
            if not self.spin_window.isVisible():
                # Avoid stealing focus from the main window.
                self.spin_window.show()
            self.spin_window.raise_()
        else:
            if self.spin_window.isVisible():
                self.spin_window.hide()

    def _on_spin_window_closed(self):
        """React when the spin window is manually closed."""
        if not self.spin_panel_visible:
            return
        self.spin_panel_visible = False
        self._update_side_container_visibility()

    def _on_graph_window_closed(self):
        """React when the graph window is manually closed."""
        if self.view_mode_selector:
            self.view_mode_selector.blockSignals(True)
            self.view_mode_selector.setCurrentIndex(0)
            self.view_mode_selector.blockSignals(False)
        self._apply_graph_view_mode(0)
        self.graph_view_active = False

    def _update_legend_column_visibility(self):
        """Ensure the legend column mirrors the legend widget visibility."""
        if not self.legend_column:
            return
        should_show = bool(self.legend_widget and self.legend_widget.isVisible())
        current_state = self.legend_column.isVisible()
        if current_state == should_show:
            return
        previous_width = self._capture_viewport_width()
        self.legend_column.setVisible(should_show)
        self._main_layout.activate()
        padding = self._panel_extra_padding.get("legend", 0) if should_show else 0
        self._preserve_arena_view_width(previous_width, padding)

    def _graph_filter_active(self):
        """Return True if the graph filter switch can affect the view."""
        return bool(
            self.graph_views
            and self.graph_view_active
            and self.graph_filter_widget
            and self.graph_filter_widget.isVisible()
            and self.clicked_spin
        )

    def _build_graph_highlight(self, mode):
        """Return highlight information for the given mode."""
        if not self.clicked_spin:
            return None
        index_map = self._graph_index_map.get(mode) or {}
        adjacency = self.connection_lookup.get(mode) or {}
        selected_idx = index_map.get(self.clicked_spin)
        if selected_idx is None:
            return None
        center = self._agent_centers.get(self.clicked_spin)
        selected_meta = self._get_metadata_for_agent(self.clicked_spin) or {}
        selected_detection_range = float(selected_meta.get("detection_range", 0.1))
        highlight = {
            "nodes": set([selected_idx]),
            "edges": set(),
            "selected": selected_idx,
        }
        if self.graph_filter_mode == "direct" or not self._graph_filter_active():
            neighbors = adjacency.get(self.clicked_spin, set())
            if mode == "detection" and center is not None:
                filtered = set()
                for neighbor in neighbors:
                    other_center = self._agent_centers.get(neighbor)
                    if other_center is None:
                        continue
                    if not math.isinf(selected_detection_range) and selected_detection_range <= 0:
                        continue
                    distance = math.hypot(center.x - other_center.x, center.y - other_center.y)
                    if math.isinf(selected_detection_range) or distance <= selected_detection_range:
                        filtered.add(neighbor)
                neighbors = filtered
            for neighbor in neighbors:
                idx = index_map.get(neighbor)
                if idx is None:
                    continue
                highlight["nodes"].add(idx)
                highlight["edges"].add(tuple(sorted((selected_idx, idx))))
            return highlight
        # Indirect mode: include the whole connected component reachable from the selection.
        visited = {self.clicked_spin}
        queue = [self.clicked_spin]
        while queue:
            current = queue.pop(0)
            current_idx = index_map.get(current)
            neighbors = adjacency.get(current, set())
            if mode == "detection" and center is not None and current == self.clicked_spin:
                filtered = set()
                for neighbor in neighbors:
                    other_center = self._agent_centers.get(neighbor)
                    if other_center is None:
                        continue
                    if not math.isinf(selected_detection_range) and selected_detection_range <= 0:
                        continue
                    distance = math.hypot(center.x - other_center.x, center.y - other_center.y)
                    if math.isinf(selected_detection_range) or distance <= selected_detection_range:
                        filtered.add(neighbor)
                neighbors = filtered
            for neighbor in neighbors:
                neighbor_idx = index_map.get(neighbor)
                if current_idx is not None and neighbor_idx is not None:
                    highlight["edges"].add(tuple(sorted((current_idx, neighbor_idx))))
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        for node_id in visited:
            idx = index_map.get(node_id)
            if idx is not None:
                highlight["nodes"].add(idx)
        return highlight

    def _clear_selection(self, update_view=True):
        """Clear the currently selected agent and refresh the view."""
        if self.clicked_spin is None:
            return
        self.clicked_spin = None
        self._unlock_camera()
        self._update_centroid_button_label()
        self._hide_spin_canvas()
        if self.legend_widget:
            self.legend_widget.update_entries([])
        self._update_graph_filter_controls()
        self._update_graph_views()
        self._update_side_container_visibility()
        if update_view:
            self.update_scene()

    def _connection_features_active(self) -> bool:
        """Return True when connection overlays or graphs must be rendered."""
        if not getattr(self, "connection_features_enabled", False):
            return False
        overlay_modes = {"messages", "detection"}
        overlays_enabled = bool(overlay_modes & self.show_modes)
        on_click_enabled = bool(overlay_modes & self.on_click_modes) and self.clicked_spin is not None
        graphs_visible = bool(self.graph_views) and self.graph_view_active
        return overlays_enabled or on_click_enabled or graphs_visible

    def _clear_connection_caches(self) -> None:
        """Reset cached adjacency data to keep the scene lightweight."""
        self.connection_lookup = {"messages": {}, "detection": {}}
        self.connection_graphs["messages"] = {"nodes": [], "edges": []}
        self.connection_graphs["detection"] = {"nodes": [], "edges": []}
        self._agent_centers = {}
        self._graph_layout_coords = {}
        self._graph_index_map = {"messages": {}, "detection": {}}

    def _rebuild_connection_graphs(self):
        """Recompute adjacency data for message and detection networks."""
        if not getattr(self, "connection_features_enabled", False):
            self._clear_connection_caches()
            return
        nodes = []
        centers = {}
        metadata = self.agents_metadata or {}
        shapes = self.agents_shapes or {}
        for key, entities in shapes.items():
            meta_list = metadata.get(key, [])
            for idx, shape in enumerate(entities):
                center = shape.center_of_mass()
                centers[(key, idx)] = center
                meta = meta_list[idx] if idx < len(meta_list) else {}
                display_label = f"{key}#{idx}"
                nodes.append({
                    "id": (key, idx),
                    "key": key,
                    "index": idx,
                    "pos": center,
                    "label": display_label,
                    "short_label": self._compress_node_label(key, idx),
                    "color": self._resolve_shape_color(shape),
                    "meta": meta,
                })
        adjacency = {mode: {node["id"]: set() for node in nodes} for mode in ("messages", "detection")}
        edges = {"messages": [], "detection": []}
        index_map = {node["id"]: idx for idx, node in enumerate(nodes)}
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                node_a = nodes[i]
                node_b = nodes[j]
                dist = math.hypot(
                    node_a["pos"].x - node_b["pos"].x,
                    node_a["pos"].y - node_b["pos"].y,
                )
                if self._should_link_messages(node_a["meta"], node_b["meta"], dist):
                    adjacency["messages"][node_a["id"]].add(node_b["id"])
                    adjacency["messages"][node_b["id"]].add(node_a["id"])
                    edges["messages"].append((i, j))
                if self._should_link_detection(node_a["meta"], node_b["meta"], dist):
                    adjacency["detection"][node_a["id"]].add(node_b["id"])
                    adjacency["detection"][node_b["id"]].add(node_a["id"])
                    edges["detection"].append((i, j))
        self._agent_centers = centers
        self.connection_lookup = adjacency
        self.connection_graphs["messages"] = {"nodes": nodes, "edges": edges["messages"]}
        self.connection_graphs["detection"] = {"nodes": nodes, "edges": edges["detection"]}
        self._graph_layout_coords = self._select_graph_layout(nodes)
        self._graph_index_map["messages"] = dict(index_map)
        self._graph_index_map["detection"] = dict(index_map)

    def _select_graph_layout(self, nodes):
        """Return the node coordinates depending on the view mode."""
        if getattr(self, "view_mode", None) == "static":
            ids = sorted([node["id"] for node in nodes])
            if ids != self._static_layout_ids:
                self._static_layout_cache = self._build_static_layout(ids)
                self._static_layout_ids = ids
            coords = {}
            for idx, node in enumerate(nodes):
                coords[idx] = self._static_layout_cache.get(node["id"], (0.5, 0.5))
            return coords
        return self._compute_normalized_layout(nodes)

    @staticmethod
    def _compute_normalized_layout(nodes):
        """Return normalized node positions so both graphs share the layout."""
        if not nodes:
            return {}
        xs = [node["pos"].x for node in nodes]
        ys = [node["pos"].y for node in nodes]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        coords = {}
        for idx, node in enumerate(nodes):
            norm_x = (node["pos"].x - min_x) / span_x if span_x > 0 else 0.5
            norm_y = (node["pos"].y - min_y) / span_y if span_y > 0 else 0.5
            coords[idx] = (norm_x, norm_y)
        return coords

    @staticmethod
    def _build_static_layout(node_ids):
        """Arrange nodes along a circle for the static view."""
        coords = {}
        count = max(1, len(node_ids))
        radius = 0.4
        for idx, node_id in enumerate(node_ids):
            angle = (2 * math.pi * idx) / count
            coords[node_id] = (
                0.5 + radius * math.cos(angle),
                0.5 + radius * math.sin(angle),
            )
        return coords

    @staticmethod
    def _resolve_shape_color(shape):
        """Return the color associated with a shape."""
        if hasattr(shape, "color"):
            try:
                return shape.color()
            except Exception:
                return "#ffffff"
        return "#ffffff"

    @staticmethod
    def _compress_node_label(entity_key, index):
        """Compress the agent label using the requested naming rule."""
        base = entity_key or ""
        suffix = base[6:] if base.startswith("agent_") else base
        tokens = [token for token in suffix.split("_") if token]
        first_char = tokens[0][0].lower() if tokens and tokens[0] else (suffix[:1].lower() or "a")
        class_id = tokens[1] if len(tokens) > 1 else "0"
        return f"{first_char}.{class_id}#{index}"

    def _should_link_messages(self, meta_a, meta_b, distance):
        """Return True if two agents can exchange messages."""
        # Messaging must be enabled on both sides.
        enable_a = bool(meta_a.get("msg_enable"))
        enable_b = bool(meta_b.get("msg_enable"))
        if not (enable_a and enable_b):
            return False

        # Range-based visibility (symmetric).
        range_a = float(meta_a.get("msg_comm_range", 0.0))
        range_b = float(meta_b.get("msg_comm_range", 0.0))
        if range_a <= 0 or range_b <= 0:
            return False
        limit = min(range_a, range_b)
        if not (math.isinf(limit) or distance <= limit):
            return False

        # Message type / kind compatibility.
        msg_type_a = str(meta_a.get("msg_type") or "").strip().lower()
        msg_type_b = str(meta_b.get("msg_type") or "").strip().lower()
        msg_kind_a = str(meta_a.get("msg_kind") or "").strip().lower()
        msg_kind_b = str(meta_b.get("msg_kind") or "").strip().lower()

        # Handshake vs non-handshake live on separate "worlds":
        # - agents with type "hand_shake" can only talk to other hand_shake agents
        # - agents with broadcast / rebroadcast never connect to hand_shake ones
        handshake_a = (msg_type_a == "hand_shake")
        handshake_b = (msg_type_b == "hand_shake")
        if handshake_a != handshake_b:
            return False

        # Anonymous vs id-aware:
        # if both ends declare a kind and they differ, we treat them as incompatible.
        if msg_kind_a and msg_kind_b and msg_kind_a != msg_kind_b:
            return False

        # Otherwise, the link is allowed.
        return True

    def _should_link_detection(self, meta_a, meta_b, distance):
        """Return True if either agent can detect the other."""
        range_a = float(meta_a.get("detection_range", 0.1))
        range_b = float(meta_b.get("detection_range", 0.1))
        cond_a = range_a > 0 and (math.isinf(range_a) or distance <= range_a)
        cond_b = range_b > 0 and (math.isinf(range_b) or distance <= range_b)
        return cond_a or cond_b

    def _update_graph_views(self):
        """Refresh the auxiliary graph widgets with the latest data."""
        if not self.graph_views or not getattr(self, "connection_features_enabled", False):
            return
        layout = self._graph_layout_coords
        for mode, widget in self.graph_views.items():
            graph_data = self.connection_graphs.get(mode, {"nodes": [], "edges": []})
            highlight = self._build_graph_highlight(mode)
            if highlight is None and self.clicked_spin:
                # Fallback: dim others even when no adjacency was built.
                index_map = self._graph_index_map.get(mode) or {}
                selected_idx = index_map.get(self.clicked_spin)
                if selected_idx is not None:
                    highlight = {"nodes": {selected_idx}, "edges": set(), "selected": selected_idx}
            widget.update_graph(graph_data["nodes"], graph_data["edges"], layout, highlight)
