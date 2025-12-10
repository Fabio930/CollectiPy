# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Reusable Qt widgets for the GUI."""
from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Qt as _Qt, QEvent as _QEvent, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QMouseEvent
from PySide6.QtWidgets import (
    QLabel,
    QWidget,
    QVBoxLayout,
    QSizePolicy as _QSizePolicy,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
)

Qt = cast(Any, _Qt)
QSizePolicy = cast(Any, _QSizePolicy)
QEvent = cast(Any, _QEvent)


class NetworkGraphWidget(QWidget):
    """Simple widget that renders an interaction graph."""

    agent_selected = Signal(object, bool)

    def __init__(self, title: str, edge_color: QColor, title_color="black"):
        super().__init__()
        self.edge_color = edge_color
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(f"color: {self._color_to_css(title_color)}; font-weight: bold;")
        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)
        self._view.setMinimumSize(480, 360)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._view.setStyleSheet("background-color: white; border: 1px solid #cccccc;")
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._title)
        layout.addWidget(self._view)
        self.setLayout(layout)

        self._view.viewport().installEventFilter(self)

    def update_graph(self, nodes, edges, normalized_coords=None, highlight=None):
        """Redraw the graph based on the provided nodes and edges."""
        self._scene.clear()
        if not nodes:
            self._scene.addText("No agents available")
            return
        pad_x = 60
        pad_y = 70
        view_w = max(self._view.viewport().width(), 480)
        view_h = max(self._view.viewport().height(), 360)
        draw_w = max(1.0, view_w - 2 * pad_x)
        draw_h = max(1.0, view_h - pad_y - 40)
        node_radius = 7
        coords = {}
        if normalized_coords:
            for idx in range(len(nodes)):
                norm = normalized_coords.get(idx)
                if norm is None:
                    continue
                coords[idx] = (
                    pad_x + norm[0] * draw_w,
                    pad_y + norm[1] * draw_h,
                )
        if len(coords) < len(nodes):
            xs = [node["pos"].x for node in nodes]
            ys = [node["pos"].y for node in nodes]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span_x = max(max_x - min_x, 1e-6)
            span_y = max(max_y - min_y, 1e-6)
            for idx, node in enumerate(nodes):
                if idx in coords:
                    continue
                norm_x = (node["pos"].x - min_x) / span_x if span_x > 0 else 0.5
                norm_y = (node["pos"].y - min_y) / span_y if span_y > 0 else 0.5
                coords[idx] = (
                    pad_x + norm_x * draw_w,
                    pad_y + norm_y * draw_h,
                )
        self._scene.setSceneRect(0, 0, view_w, view_h)
        highlight_edges = set()
        highlight_nodes = set()
        selected_index = None
        if highlight:
            highlight_edges = highlight.get("edges", set()) or set()
            highlight_nodes = highlight.get("nodes", set()) or set()
            selected_index = highlight.get("selected")
        highlight_active = bool(highlight_edges or highlight_nodes)
        dim_edge_color = QColor(160, 160, 160, 80)
        processed_edges = []
        for entry in edges:
            if isinstance(entry, tuple):
                if len(entry) >= 2:
                    idx_a, idx_b = entry[0], entry[1]
                    edge_color = entry[2] if len(entry) >= 3 and isinstance(entry[2], QColor) else None
                else:
                    continue
            elif isinstance(entry, dict):
                idx_a = entry.get("from") or entry.get("a")
                idx_b = entry.get("to") or entry.get("b")
                edge_color = entry.get("color")
                if not isinstance(edge_color, QColor):
                    edge_color = None
            else:
                continue
            if idx_a is None or idx_b is None:
                continue
            processed_edges.append((idx_a, idx_b, edge_color))
        for idx_a, idx_b, edge_color in processed_edges:
            if idx_a not in coords or idx_b not in coords:
                continue
            edge_key = tuple(sorted((idx_a, idx_b)))
            base_color = edge_color or self.edge_color
            if highlight_active:
                if edge_key in highlight_edges:
                    color = base_color
                    width = 2.0
                else:
                    color = dim_edge_color
                    width = 1.0
            else:
                color = base_color
                width = 1.2
            edge_pen = QPen(color, width)
            edge_pen.setCosmetic(True)
            ax, ay = coords[idx_a]
            bx, by = coords[idx_b]
            self._scene.addLine(ax, ay, bx, by, edge_pen)
        node_pen = QPen(Qt.black, 0.8)
        node_pen.setCosmetic(True)
        highlight_edges = set()
        highlight_nodes = set()
        selected_index = None
        if highlight:
            highlight_edges = highlight.get("edges", set()) or set()
            selected_index = highlight.get("selected")
            if selected_index is not None:
                highlight_nodes = {selected_index}
        highlight_active = selected_index is not None
        for idx, node in enumerate(nodes):
            if idx not in coords:
                continue
            px, py = coords[idx]
            fill_color = QColor(node.get("color") or "#ffffff")
            # Keep the selected node at full color; dim all others when a highlight is active.
            if highlight_active and idx not in highlight_nodes:
                dimmed = self._dim_color(fill_color)
                dimmed.setAlpha(80)
                node_brush = QBrush(dimmed)
            else:
                node_brush = QBrush(fill_color)
            ellipse = self._scene.addEllipse(
                px - node_radius,
                py - node_radius,
                node_radius * 2,
                node_radius * 2,
                node_pen,
                node_brush,
            )
            ellipse.setData(0, node.get("id"))
            ellipse.setToolTip(node.get("label", ""))
            text_value = node.get("short_label") or node.get("label", "")
            label = self._scene.addText(text_value)
            label.setData(0, node.get("id"))
            label.setDefaultTextColor(Qt.black)
            label_rect = label.boundingRect()
            label.setPos(
                px - label_rect.width() / 2,
                py - node_radius - label_rect.height() - 2,
            )
            if highlight_active and idx not in highlight_nodes:
                ellipse.setOpacity(0.25)
                label.setOpacity(0.25)
            if selected_index is not None and idx == selected_index:
                halo_pen = QPen(Qt.black, 2.0)
                halo_pen.setCosmetic(True)
                self._scene.addEllipse(
                    px - node_radius - 4,
                    py - node_radius - 4,
                    (node_radius + 4) * 2,
                    (node_radius + 4) * 2,
                    halo_pen,
                )

    def eventFilter(self, watched: Any, event: _QEvent):
        """Handle click selection on graph nodes."""
        if watched == self._view.viewport():
            if event.type() == QEvent.Type.MouseButtonDblClick:
                mouse_event = cast(QMouseEvent, event)
                agent_id = self._agent_at(mouse_event.pos())
                if agent_id is not None:
                    self.agent_selected.emit(agent_id, True)
                    return True
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = cast(QMouseEvent, event)
                agent_id = self._agent_at(mouse_event.pos())
                if agent_id is not None:
                    self.agent_selected.emit(agent_id, False)
                    return True
        return super().eventFilter(watched, event)

    def _agent_at(self, viewport_pos):
        """Return agent id at the given viewport position if present."""
        scene_pos = self._view.mapToScene(viewport_pos)
        # itemAt may return edges; search all items under cursor for data
        for item in self._scene.items(scene_pos):
            agent_id = item.data(0) if hasattr(item, "data") else None
            if agent_id is not None:
                return agent_id
        return None

    @staticmethod
    def _color_to_css(value) -> str:
        """Return a CSS-compatible color string."""
        if isinstance(value, QColor):
            return value.name()
        return str(value)

    @staticmethod
    def _dim_color(color: QColor) -> QColor:
        """Return a dimmed variant of the provided color."""
        if not isinstance(color, QColor):
            color = QColor(color)
        dimmed = QColor(color)
        dimmed.setAlpha(120)
        return dimmed


class ConnectionLegendWidget(QWidget):
    """Small legend describing the active connection overlays."""

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout()
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(8)
        self.setLayout(self._layout)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Maximum)
        self.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.95);"
            "border: 1px solid #c0c0c0;"
            "border-radius: 6px;"
        )

    def update_entries(self, entries):
        """Replace the legend entries with the provided list."""
        self._clear_entries()
        if not entries:
            self.setVisible(False)
            return
        for color, label in entries:
            entry = QWidget()
            entry_layout = QHBoxLayout()
            entry_layout.setContentsMargins(2, 2, 2, 2)
            entry_layout.setSpacing(6)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background-color: {self._color_to_css(color)}; border: 1px solid #555555;"
            )
            text_label = QLabel(label)
            text_label.setStyleSheet("font-size: 10pt;")
            entry_layout.addWidget(swatch)
            entry_layout.addWidget(text_label)
            entry.setLayout(entry_layout)
            self._layout.addWidget(entry)
        self.setVisible(True)

    def _clear_entries(self):
        """Remove the previous legend entries."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _color_to_css(color):
        """Return the hex CSS representation for the provided color."""
        if isinstance(color, QColor):
            return color.name()
        return str(color)
