# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Camera and viewport helpers shared by GUI_2D."""
from __future__ import annotations

import math
from typing import Optional, Any

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QWidget

from core.util.geometry_utils.vector3D import Vector3D


class CameraMixin:
    """Mixin providing camera logic for the 2D GUI."""

    _view_rect: Optional[QRectF]
    _view_initialized: bool
    _camera_lock: Optional[tuple[str, Any]]
    _keyboard_pan_factor: float
    _zoom_min_span: float
    _unbounded_rect: Optional[QRectF]
    wrap_config: Optional[dict]
    unbounded_mode: bool
    view: Any
    scene: Any
    hierarchy_overlay: Any
    arena_vertices: list
    arena_color: str
    scale: float
    offset_x: float
    offset_y: float
    _agent_centers: dict
    _last_viewport_width: Optional[int]
    _layout_change_in_progress: bool
    _panel_extra_padding: dict

    # ----- Camera and view helpers -----------------------------------------
    def _refresh_agent_centers(self):
        """Rebuild the cache of agent centers."""
        centers = {}
        shapes = getattr(self, "agents_shapes", {}) or {}
        for key, entities in shapes.items():
            for idx, shape in enumerate(entities):
                try:
                    center = shape.center_of_mass()
                except Exception:
                    center = None
                if center is None:
                    continue
                centers[(key, idx)] = center
        if centers:
            self._agent_centers = centers

    def _compute_arena_rect(self):
        """Return the bounding rectangle of the arena vertices."""
        if self.unbounded_mode:
            return self._compute_dynamic_unbounded_rect()
        if not self.arena_vertices:
            return None
        min_x = min(v.x for v in self.arena_vertices)
        max_x = max(v.x for v in self.arena_vertices)
        min_y = min(v.y for v in self.arena_vertices)
        max_y = max(v.y for v in self.arena_vertices)
        width = max(max_x - min_x, 1e-6)
        height = max(max_y - min_y, 1e-6)
        return QRectF(min_x, min_y, width, height)

    def _compute_agents_rect(self):
        """Return the bounding rectangle covering all agents."""
        centers = self._agent_centers or {}
        if not centers:
            return None
        xs = [c.x for c in centers.values()]
        ys = [c.y for c in centers.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max(max_x - min_x, 1e-6)
        height = max(max_y - min_y, 1e-6)
        return QRectF(min_x, min_y, width, height)

    def _pad_rect(self, rect: QRectF, padding_ratio: float = 0.05, min_padding: float = 0.1):
        """Return a rectangle expanded by a padding factor."""
        if rect is None:
            return None
        pad = max(rect.width(), rect.height()) * padding_ratio
        pad = max(pad, min_padding)
        return QRectF(
            rect.left() - pad,
            rect.top() - pad,
            rect.width() + 2 * pad,
            rect.height() + 2 * pad,
        )

    def _fit_rect_to_aspect(self, rect: QRectF):
        """Expand the rect so it matches the viewport aspect ratio."""
        if rect is None:
            return None
        vw = max(1, self.view.viewport().width()) if self.view else 1
        vh = max(1, self.view.viewport().height()) if self.view else 1
        aspect = vw / float(vh)
        width = max(rect.width(), 1e-6)
        height = max(rect.height(), 1e-6)
        if width / height > aspect:
            target_height = width / aspect
            target_width = width
        else:
            target_width = height * aspect
            target_height = height
        dx = (target_width - width) / 2.0
        dy = (target_height - height) / 2.0
        return QRectF(
            rect.left() - dx,
            rect.top() - dy,
            target_width,
            target_height,
        )

    def _default_view_rect(self):
        """Return the default view rectangle based on arena or agents."""
        arena_rect = self._compute_arena_rect()
        agents_rect = self._compute_agents_rect()
        base_rect = None
        # Prefer arena bounds when bounded; otherwise use agents.
        if (self.wrap_config is None or not self.unbounded_mode) and arena_rect is not None:
            base_rect = arena_rect
        elif agents_rect is not None:
            base_rect = agents_rect
        elif arena_rect is not None:
            base_rect = arena_rect
        if base_rect is None:
            base_rect = QRectF(-5, -5, 10, 10)
        padded = self._pad_rect(base_rect)
        return self._fit_rect_to_aspect(padded)

    def _compute_dynamic_unbounded_rect(self):
        """Compute a bounded preview rect for unbounded arenas."""
        centers = self._agent_centers or {}
        if centers:
            xs = [c.x for c in centers.values()]
            ys = [c.y for c in centers.values()]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span = max(max_x - min_x, max_y - min_y, 1.0)
            pad = max(span * 0.5, 2.0)
            rect = QRectF(min_x - pad, min_y - pad, (max_x - min_x) + 2 * pad, (max_y - min_y) + 2 * pad)
        else:
            rect = QRectF(-5, -5, 10, 10)
        return rect

    def _update_unbounded_vertices(self):
        """Resize the preview square so all agents stay away from edges."""
        rect = self._compute_dynamic_unbounded_rect()
        pad = max(rect.width(), rect.height()) * 0.05
        rect = QRectF(
            rect.left() - pad,
            rect.top() - pad,
            rect.width() + 2 * pad,
            rect.height() + 2 * pad,
        )
        # Grow-only behavior to avoid sudden shrinking/jumps.
        if self._unbounded_rect is None:
            self._unbounded_rect = rect
        else:
            u = self._unbounded_rect
            min_x = min(u.left(), rect.left())
            min_y = min(u.top(), rect.top())
            max_x = max(u.right(), rect.right())
            max_y = max(u.bottom(), rect.bottom())
            self._unbounded_rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        urect = self._unbounded_rect
        self.arena_vertices = [
            Vector3D(urect.left(), urect.top(), 0),
            Vector3D(urect.right(), urect.top(), 0),
            Vector3D(urect.right(), urect.bottom(), 0),
            Vector3D(urect.left(), urect.bottom(), 0),
        ]

    def _ensure_view_initialized(self):
        """Initialize the camera view rectangle if missing."""
        if getattr(self, "_view_initialized", False):
            return
        rect = self._default_view_rect()
        if rect is None:
            return
        self._view_rect = rect
        self._view_initialized = True

    def _recompute_transform(self):
        """Update scale and offsets based on the current view rectangle."""
        self._ensure_view_initialized()
        if self._view_rect is None:
            return
        if self.unbounded_mode:
            self._update_unbounded_vertices()
        aspect_fitted = self._fit_rect_to_aspect(self._view_rect)
        if aspect_fitted is not None:
            self._view_rect = aspect_fitted
        rect = self._view_rect
        vw = max(1, self.view.viewport().width()) if self.view else 1
        vh = max(1, self.view.viewport().height()) if self.view else 1
        scale_x = vw / rect.width()
        scale_y = vh / rect.height()
        self.scale = min(scale_x, scale_y)
        self.offset_x = vw * 0.5 - rect.center().x() * self.scale
        self.offset_y = vh * 0.5 - rect.center().y() * self.scale

    def _world_from_scene(self, scene_point: QPointF):
        """Convert a scene pixel coordinate into world coordinates."""
        if self.scale == 0:
            return QPointF(0, 0)
        return QPointF(
            (scene_point.x() - self.offset_x) / self.scale,
            (scene_point.y() - self.offset_y) / self.scale,
        )

    def _is_point_visible(self, world_point: QPointF, margin_ratio: float = 0.02):
        """Return True if a world point is inside the current view rect."""
        if self._view_rect is None:
            return False
        margin_x = self._view_rect.width() * margin_ratio
        margin_y = self._view_rect.height() * margin_ratio
        expanded = QRectF(
            self._view_rect.left() - margin_x,
            self._view_rect.top() - margin_y,
            self._view_rect.width() + 2 * margin_x,
            self._view_rect.height() + 2 * margin_y,
        )
        return expanded.contains(world_point)

    def _pan_camera_by_scene_delta(self, delta: QPointF):
        """Pan the camera using a delta measured in scene pixels."""
        if self.scale == 0:
            return
        dx_world = delta.x() / self.scale
        dy_world = delta.y() / self.scale
        self._pan_camera(-dx_world, -dy_world)

    def _pan_camera(self, dx_world: float, dy_world: float):
        """Translate the camera view by the given world delta."""
        if self._view_rect is None:
            self._ensure_view_initialized()
        if self._view_rect is None:
            return
        self._view_rect.translate(dx_world, dy_world)
        self.update_scene()

    def _zoom_camera(self, factor: float, anchor_scene_pos=None):
        """Zoom the camera keeping the anchor point stable."""
        if self._view_rect is None:
            self._ensure_view_initialized()
        if self._view_rect is None:
            return
        lock = self._camera_lock[0] if self._camera_lock else None
        lock_target = self._camera_lock[1] if self._camera_lock else None
        rect = self._view_rect
        aspect = rect.width() / max(rect.height(), 1e-6)
        anchor_world = None
        if anchor_scene_pos is not None:
            anchor_world = self._world_from_scene(self.view.mapToScene(anchor_scene_pos))
        if anchor_world is None:
            anchor_world = QPointF(rect.center().x(), rect.center().y())
        base_rect = self._default_view_rect()
        max_span = max(base_rect.width(), base_rect.height()) * 5 if base_rect else rect.width() * 5
        min_span = max(self._zoom_min_span, min(rect.width(), rect.height()) * 0.05)
        new_width = rect.width() * factor
        new_width = max(min_span, min(new_width, max_span))
        new_height = new_width / aspect
        center = rect.center()
        new_center = QPointF(
            anchor_world.x() + (center.x() - anchor_world.x()) * factor,
            anchor_world.y() + (center.y() - anchor_world.y()) * factor,
        )
        self._view_rect = QRectF(
            new_center.x() - new_width / 2.0,
            new_center.y() - new_height / 2.0,
            new_width,
            new_height,
        )
        # Preserve lock target after zoom.
        if lock == "agent" and lock_target is not None:
            self._focus_on_agent(lock_target, force=True, lock=True, apply_scene=False)
        elif lock == "centroid":
            # Re-center on centroid but keep user-driven zoom; do not enlarge span.
            self._focus_on_centroid(lock=True, apply_scene=False, preserve_view_size=True)
        self.update_scene()

    def _restore_view(self):
        """Reset the camera to show the arena or agents."""
        rect = None
        if self.wrap_config is None:
            rect = self._compute_arena_rect()
            if rect is not None:
                rect = self._pad_rect(rect)
        agents_rect = self._compute_agents_rect()
        if rect is None or self.wrap_config is not None:
            rect = agents_rect if agents_rect is not None else self._default_view_rect()
        if rect is None:
            return
        self._unlock_camera()
        self._view_rect = self._fit_rect_to_aspect(rect)
        self.update_scene()

    def _focus_on_centroid(self, lock=False, apply_scene=True, preserve_view_size: bool = False):
        """Move camera to the centroid of all agents."""
        if not self._agent_centers:
            return
        xs = [c.x for c in self._agent_centers.values()]
        ys = [c.y for c in self._agent_centers.values()]
        centroid = QPointF(sum(xs) / len(xs), sum(ys) / len(ys))
        rect = self._view_rect or self._default_view_rect()
        if rect is None:
            return
        span = max(
            math.hypot(c.x - centroid.x(), c.y - centroid.y())
            for c in self._agent_centers.values()
        )
        target_width = rect.width()
        target_height = rect.height()
        if not preserve_view_size:
            # Ensure we include at least two agents (bounding-box based).
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            bbox_span = max(max_x - min_x, max_y - min_y, self._zoom_min_span)
            margin = max(bbox_span * 0.2, self._zoom_min_span * 2)
            min_span = bbox_span + margin
            target_width = max(target_width, min_span)
            target_height = max(target_height, min_span / max(rect.width() / max(rect.height(), 1e-6), 1e-6))
            if self.wrap_config is not None:
                target_width = max(target_width, span * 2.2, rect.width() * 0.8, self._zoom_min_span)
                target_height = target_width / max(rect.width() / max(rect.height(), 1e-6), 1e-6)
        new_rect = QRectF(
            centroid.x() - target_width / 2.0,
            centroid.y() - target_height / 2.0,
            target_width,
            target_height,
        )
        self._view_rect = self._fit_rect_to_aspect(new_rect)
        if lock:
            self._lock_camera("centroid", None)
        else:
            self._unlock_camera()
        if apply_scene:
            self.update_scene()

    def _focus_on_agent(self, agent_key, force=False, lock=False, apply_scene=True):
        """Move camera to the specified agent."""
        if not agent_key:
            return
        center = self._agent_centers.get(agent_key)
        if center is None:
            return
        point = QPointF(center.x, center.y)
        if not force and self._is_point_visible(point):
            if lock:
                self._lock_camera("agent", agent_key)
            return
        rect = self._view_rect or self._default_view_rect()
        if rect is None:
            return
        new_rect = QRectF(
            point.x() - rect.width() / 2.0,
            point.y() - rect.height() / 2.0,
            rect.width(),
            rect.height(),
        )
        self._view_rect = new_rect
        if lock:
            self._lock_camera("agent", agent_key)
        else:
            self._unlock_camera()
        if apply_scene:
            self.update_scene()

    def _lock_camera(self, mode, target):
        """Lock camera on agent or centroid."""
        self._camera_lock = (mode, target)
        self._update_centroid_button_label()

    def _unlock_camera(self):
        """Clear camera lock."""
        self._camera_lock = None
        self._update_centroid_button_label()

    def _update_camera_lock(self):
        """Maintain camera lock on every refresh."""
        if not self._camera_lock:
            return
        mode, target = self._camera_lock
        if mode == "agent" and target not in (self._agent_centers or {}):
            self._unlock_camera()
            return
        if mode == "centroid" and not self._agent_centers:
            self._unlock_camera()
            return
        if mode == "agent":
            self._focus_on_agent(target, force=True, lock=True, apply_scene=False)
        elif mode == "centroid":
            self._focus_on_centroid(lock=True, apply_scene=False, preserve_view_size=True)
        if self.unbounded_mode:
            self._update_unbounded_vertices()

    def _update_centroid_button_label(self):
        """Reflect lock state on centroid button label."""
        if not hasattr(self, "centroid_button") or self.centroid_button is None:
            return
        locked = self._camera_lock and self._camera_lock[0] == "centroid"
        label = "Centroid" + (" [lock]" if locked else "")
        if self.centroid_button.text() != label:
            self.centroid_button.setText(label)

    def _nudge_camera(self, dx_sign: float, dy_sign: float):
        """Move camera with keyboard controls."""
        if self._view_rect is None:
            self._ensure_view_initialized()
        if self._view_rect is None:
            return
        step_x = self._view_rect.width() * self._keyboard_pan_factor
        step_y = self._view_rect.height() * self._keyboard_pan_factor
        self._pan_camera(dx_sign * step_x, dy_sign * step_y)

    def _sync_scene_rect_with_view(self):
        """Ensure the scene rectangle matches the current viewport size."""
        if not self.view or not self.scene:
            return
        view_width = max(1, self.view.viewport().width())
        view_height = max(1, self.view.viewport().height())
        self.scene.setSceneRect(0, 0, view_width, view_height)
        self._last_viewport_width = view_width

    def _capture_viewport_width(self):
        """Return the current viewport width if available."""
        if not self.view:
            return None
        viewport = self.view.viewport()
        if viewport is None:
            return None
        width = viewport.width()
        return width if width > 0 else None

    def _preserve_arena_view_width(self, previous_width, extra_padding=0):
        """Resize the top-level window so the arena keeps its width."""
        if previous_width is None or getattr(self, "_layout_change_in_progress", False):
            return
        current_width = self._capture_viewport_width()
        if current_width is None:
            return
        delta = previous_width - current_width
        if abs(delta) < 1 and extra_padding <= 0:
            return
        self._layout_change_in_progress = True
        try:
            adjustment = delta + max(0, extra_padding)
            if abs(adjustment) < 1 and delta != 0:
                adjustment = delta
            new_width = max(self.minimumWidth(), self.width() + adjustment)
            self.resize(new_width, self.height())
        finally:
            self._layout_change_in_progress = False

    def resizeEvent(self, event: Optional[QResizeEvent]):
        """Handle Qt resize events."""
        if event is not None:
            super().resizeEvent(event)
        self._sync_scene_rect_with_view()
        self.update_scene()
