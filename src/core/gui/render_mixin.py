# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Rendering utilities for GUI_2D."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPolygonF, QColor, QPen, QBrush


class RenderMixin:
    """Mixin that handles scene rendering."""

    view: any
    scene: any
    arena_vertices: list
    arena_color: str
    wrap_config: dict
    unbounded_mode: bool
    hierarchy_overlay: list
    abstract_dot_items: list
    agents_shapes: dict
    objects_shapes: dict
    clicked_spin: tuple
    connection_lookup: dict
    connection_colors: dict
    _agent_centers: dict
    show_modes: set
    on_click_modes: set
    scale: float
    offset_x: float
    offset_y: float
    time: int
    legend_widget: any

    def get_agent_at(self, scene_pos):
        """Return the agent at."""
        if self.agents_shapes is not None:
            for key, entities in self.agents_shapes.items():
                for idx, entity in enumerate(entities):
                    vertices = entity.vertices()
                    polygon = QPolygonF([
                        QPointF(
                            vertex.x * self.scale + self.offset_x,
                            vertex.y * self.scale + self.offset_y,
                        )
                        for vertex in vertices
                    ])
                    if polygon.containsPoint(scene_pos, Qt.FillRule.OddEvenFill):
                        return key, idx
        return None

    def draw_arena(self):
        """Draw arena."""
        if not self.arena_vertices:
            return
        if self.unbounded_mode:
            self._update_unbounded_vertices()
        scale = self.scale
        offset_x = self.offset_x
        offset_y = self.offset_y
        transformed_vertices = [
            QPointF(
                v.x * scale + offset_x,
                v.y * scale + offset_y,
            )
            for v in self.arena_vertices
        ]
        polygon = QPolygonF(transformed_vertices)
        pen = QPen(Qt.black, 2)
        if self.wrap_config and not self.unbounded_mode:
            pen.setStyle(Qt.DashLine)
        brush = QBrush(QColor(self.arena_color))
        self.scene.addPolygon(polygon, pen, brush)
        if self.wrap_config and not self.unbounded_mode:
            self._draw_axes_and_wrap_indicators(polygon)
        self._draw_hierarchy_overlay()

    def _draw_axes_and_wrap_indicators(self, polygon: QPolygonF):
        """Draw axes and wrap indicators."""
        rect = polygon.boundingRect()
        axis_pen = QPen(QColor(120, 120, 255), 1, Qt.DotLine)
        axis_pen.setCosmetic(True)
        # Draw reference axes crossing the map center.
        center_x = rect.left() + rect.width() / 2
        center_y = rect.top() + rect.height() / 2
        self.scene.addLine(rect.left(), center_y, rect.right(), center_y, axis_pen)
        self.scene.addLine(center_x, rect.top(), center_x, rect.bottom(), axis_pen)
        equator_label = self.scene.addText("Equator")
        equator_label.setDefaultTextColor(QColor(80, 80, 200))
        equator_label.setPos(rect.left() + 5, center_y - 20)
        prime_label = self.scene.addText("Prime Merid.")
        prime_label.setDefaultTextColor(QColor(80, 80, 200))
        prime_label.setPos(center_x + 5, rect.top() + 5)

    def _draw_hierarchy_overlay(self):
        """Draw hierarchy overlay."""
        if not self.hierarchy_overlay:
            return
        for item in self.hierarchy_overlay:
            bounds = item.get("bounds")
            if not bounds or len(bounds) != 4:
                continue
            rect = QRectF(
                bounds[0] * self.scale + self.offset_x,
                bounds[1] * self.scale + self.offset_y,
                (bounds[2] - bounds[0]) * self.scale,
                (bounds[3] - bounds[1]) * self.scale,
            )
            color_value = item.get("color")
            text_color = QColor(color_value) if color_value else QColor(80, 80, 200)
            qcolor = QColor(text_color)
            qcolor.setAlpha(80)
            pen = QPen(text_color, 2)
            pen.setCosmetic(True)
            level = item.get("level", 1)
            pen.setStyle(Qt.SolidLine if level <= 1 else Qt.DashLine)
            brush = QBrush(qcolor)
            brush.setStyle(Qt.Dense4Pattern)
            rect_item = self.scene.addRect(rect, pen, brush)
            rect_item.setZValue(-1)
            number = item.get("number")
            if number is not None:
                label = self.scene.addText(str(number))
                label.setDefaultTextColor(text_color)
                label_rect = label.boundingRect()
                label.setZValue(0)
                label.setPos(
                    rect.center().x() - label_rect.width() / 2,
                    rect.center().y() - label_rect.height() / 2,
                )

    def _draw_abstract_dots(self):
        """Render agents as a grid of dots in abstract mode."""
        self.abstract_dot_items = []
        if not getattr(self, "is_abstract", False):
            return
        if not self.agents_shapes:
            return
        view_width = max(1, self.view.viewport().width())
        x = self.abstract_dot_margin
        y = self.abstract_dot_margin
        line_height = self.abstract_dot_size + self.abstract_dot_spacing
        max_row_width = max(self.abstract_dot_margin + self.abstract_dot_size, view_width - self.abstract_dot_margin)
        base_pen = QPen(Qt.black, 0.5)
        base_pen.setCosmetic(True)
        for key, entities in self.agents_shapes.items():
            for idx, shape in enumerate(entities):
                if x + self.abstract_dot_size > max_row_width and x > self.abstract_dot_margin:
                    x = self.abstract_dot_margin
                    y += line_height
                color_name = self.abstract_dot_default_color
                if hasattr(shape, "color"):
                    try:
                        color_name = shape.color()
                    except Exception:
                        color_name = self.abstract_dot_default_color
                selected = self.clicked_spin is not None and self.clicked_spin[0] == key and self.clicked_spin[1] == idx
                pen = base_pen if not selected else QPen(QColor("white"), 1.2)
                pen.setCosmetic(True)
                rect = QRectF(x, y, self.abstract_dot_size, self.abstract_dot_size)
                ellipse = self.scene.addEllipse(rect, pen, QBrush(QColor(color_name)))
                ellipse.setData(0, (key, idx))
                self.abstract_dot_items.append(ellipse)
                x += self.abstract_dot_size + self.abstract_dot_spacing

    def update_scene(self):
        """Update scene."""
        self.data_label.setText(f"Arena ticks: {self.time}")
        self._ensure_view_initialized()
        self._update_camera_lock()
        self._recompute_transform()
        self.scene.clear()
        if getattr(self, "is_abstract", False):
            self._draw_abstract_dots()
            return
        if not self.arena_vertices:
            return
        self.draw_arena()
        scale = self.scale
        offset_x = self.offset_x
        offset_y = self.offset_y

        wrap_offsets = [(0.0, 0.0)] if self.unbounded_mode else None

        if self.objects_shapes is not None:
            for entities in self.objects_shapes.values():
                for entity in entities:
                    vertices = entity.vertices()
                    for dx, dy in (wrap_offsets or self._wrap_offsets(vertices)):
                        entity_vertices = [
                            QPointF(
                                (vertex.x + dx) * scale + offset_x,
                                (vertex.y + dy) * scale + offset_y,
                            )
                            for vertex in vertices
                        ]
                        entity_color = QColor(entity.color())
                        entity_polygon = QPolygonF(entity_vertices)
                        self.scene.addPolygon(entity_polygon, QPen(entity_color, 0.1), QBrush(entity_color))

        if self.agents_shapes is not None:
            for key, entities in self.agents_shapes.items():
                for idx, entity in enumerate(entities):
                    vertices = entity.vertices()
                    offsets = [(0.0, 0.0)] if self.unbounded_mode else self._wrap_offsets(vertices)
                    for dx, dy in offsets:
                        entity_vertices = [
                            QPointF(
                                (vertex.x + dx) * scale + offset_x,
                                (vertex.y + dy) * scale + offset_y,
                            )
                            for vertex in vertices
                        ]
                        entity_color = QColor(entity.color())
                        entity_polygon = QPolygonF(entity_vertices)
                        self.scene.addPolygon(entity_polygon, QPen(entity_color, 0.1), QBrush(entity_color))
                        if self.clicked_spin is not None and self.clicked_spin[0] == key and self.clicked_spin[1] == idx:
                            xs = [point.x() for point in entity_vertices]
                            ys = [point.y() for point in entity_vertices]
                            centroid_x = sum(xs) / len(xs)
                            centroid_y = sum(ys) / len(ys)
                            max_radius = max(math.hypot(x - centroid_x, y - centroid_y) for x, y in zip(xs, ys))
                            self.scene.addEllipse(
                                centroid_x - max_radius,
                                centroid_y - max_radius,
                                2 * max_radius,
                                2 * max_radius,
                                QPen(QColor("white"), 1),
                                QBrush(Qt.NoBrush),
                            )
                    attachments = entity.get_attachments()
                    for attachment in attachments:
                        att_vertices = attachment.vertices()
                        for dx, dy in offsets:
                            attachment_vertices = [
                                QPointF(
                                    (vertex.x + dx) * scale + offset_x,
                                    (vertex.y + dy) * scale + offset_y,
                                )
                                for vertex in att_vertices
                            ]
                            attachment_color = QColor(attachment.color())
                            attachment_polygon = QPolygonF(attachment_vertices)
                            self.scene.addPolygon(attachment_polygon, QPen(attachment_color, 1), QBrush(attachment_color))
        self._draw_selected_connections(scale, offset_x, offset_y)

    def _wrap_offsets(self, vertices):
        """Return wrap offsets for a given set of vertices."""
        if not self.wrap_config or not vertices:
            return [(0.0, 0.0)]
        width = float(self.wrap_config.get("width") or 0.0)
        height = float(self.wrap_config.get("height") or 0.0)
        if width <= 0 or height <= 0:
            return [(0.0, 0.0)]
        origin = self.wrap_config.get("origin")
        origin_x = self._origin_component(origin, "x", 0)
        origin_y = self._origin_component(origin, "y", 1)
        wrap_min_x = origin_x
        wrap_max_x = origin_x + width
        wrap_min_y = origin_y
        wrap_max_y = origin_y + height
        min_x = min(v.x for v in vertices)
        max_x = max(v.x for v in vertices)
        min_y = min(v.y for v in vertices)
        max_y = max(v.y for v in vertices)
        x_offsets = {0.0}
        y_offsets = {0.0}
        eps = 1e-6
        if min_x < wrap_min_x - eps:
            x_offsets.add(width)
        if max_x > wrap_max_x + eps:
            x_offsets.add(-width)
        if min_y < wrap_min_y - eps:
            y_offsets.add(height)
        if max_y > wrap_max_y + eps:
            y_offsets.add(-height)
        return [(dx, dy) for dx in x_offsets for dy in y_offsets]

    @staticmethod
    def _origin_component(origin, axis_name, index):
        """Extract axis component from the wrap origin."""
        if origin is None:
            return 0.0
        if hasattr(origin, axis_name):
            return float(getattr(origin, axis_name))
        if isinstance(origin, dict) and axis_name in origin:
            return float(origin[axis_name])
        if isinstance(origin, (list, tuple)) and len(origin) > index:
            return float(origin[index])
        return 0.0

    def _draw_selected_connections(self, scale, offset_x, offset_y):
        """Draw connection lines for the selected agent."""
        if self.is_abstract or not self.clicked_spin or not getattr(self, "connection_features_enabled", False):
            return
        selected_id = self.clicked_spin
        center = self._agent_centers.get(selected_id)
        if center is None:
            return
        selected_meta = self._get_metadata_for_agent(selected_id) or {}
        selected_detection_range = float(selected_meta.get("detection_range", 0.1))
        active_modes = self.on_click_modes | self.show_modes
        has_detection = bool(self.connection_lookup.get("detection"))
        start_x = center.x * scale + offset_x
        start_y = center.y * scale + offset_y
        for mode in ("messages", "detection"):
            if mode not in active_modes:
                continue
            neighbors = self.connection_lookup.get(mode, {}).get(selected_id, set())
            if not neighbors:
                continue
            pen = QPen(self.connection_colors[mode], 1.4)
            pen.setCosmetic(True)
            for neighbor in neighbors:
                other_center = self._agent_centers.get(neighbor)
                if other_center is None:
                    continue
                if mode == "detection":
                    if not math.isinf(selected_detection_range) and selected_detection_range <= 0:
                        continue
                    distance = math.hypot(center.x - other_center.x, center.y - other_center.y)
                    if not math.isinf(selected_detection_range) and distance > selected_detection_range:
                        continue
                end_x = other_center.x * scale + offset_x
                end_y = other_center.y * scale + offset_y
                line = self.scene.addLine(start_x, start_y, end_x, end_y, pen)
                if mode == "messages" and has_detection:
                    line.setZValue(5)
                    path = line.line()
                    length = math.hypot(path.x2() - path.x1(), path.y2() - path.y1())
                    if length > 0:
                        offset = 3.0
                        dx = (path.y2() - path.y1()) / length * offset
                        dy = -(path.x2() - path.x1()) / length * offset
                        path.translate(dx, dy)
                        line.setLine(path)
