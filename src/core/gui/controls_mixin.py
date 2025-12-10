# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Input handling and control wiring for GUI_2D."""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QMouseEvent, QKeySequence, QShortcut


class ControlsMixin:
    """Mixin responsible for user interaction and UI controls."""

    view: Any
    gui_control_queue: Any
    clicked_spin: Any
    _centroid_last_click_ts: float
    _main_layout: Any
    graph_window: Any
    graph_views: dict
    view_mode_selector: Any
    graph_filter_selector: Any
    graph_filter_widget: Any
    graph_view_active: bool
    header_container: Any
    header_toggle: Any
    header_collapsed: bool
    running: bool
    reset: bool
    step_requested: bool
    _panning: bool
    _pan_last_scene_pos: Any
    connection_features_enabled: bool
    _camera_lock: Any
    hierarchy_overlay: Any

    def eventFilter(self, watched, event):
        """Handle Qt event filtering."""
        ev = event
        if watched == self.view.viewport():
            if event.type() == QEvent.Type.Resize:
                self._sync_scene_rect_with_view()
                self.update_scene()
                return False
            if event.type() == QEvent.Type.Wheel:
                delta = ev.angleDelta().y()
                if delta != 0:
                    steps = delta / 120.0
                    base = 0.94
                    factor = base**steps if steps > 0 else (1 / base) ** abs(steps)
                    self._zoom_camera(factor)
                return True
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                    scene_pos = self.view.mapToScene(ev.pos())
                    if getattr(self, "is_abstract", False):
                        item = self.scene.itemAt(scene_pos, self.view.transform())
                        data = item.data(0) if item is not None else None
                        new_selection = data if isinstance(data, tuple) else None
                    else:
                        new_selection = self.get_agent_at(scene_pos)
                    self._handle_agent_selection(new_selection, double_click=(event.type() == QEvent.Type.MouseButtonDblClick))
                    return True
                if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.RightButton and event.type() == QEvent.Type.MouseButtonPress:
                    self._panning = True
                    self._pan_last_scene_pos = self.view.mapToScene(ev.pos())
                    return True
            if event.type() == QEvent.Type.MouseMove and self._panning:
                if self._pan_last_scene_pos is not None:
                    current_scene_pos = self.view.mapToScene(ev.pos())
                    delta = current_scene_pos - self._pan_last_scene_pos
                    self._pan_camera_by_scene_delta(delta)
                    self._pan_last_scene_pos = current_scene_pos
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.RightButton:
                self._panning = False
                self._pan_last_scene_pos = None
                return True
        return super().eventFilter(watched, event)

    def _on_centroid_button_clicked(self):
        """Center the view on the agents centroid (double click locks)."""
        # If currently locked on centroid, a single click unlocks.
        if self._camera_lock and self._camera_lock[0] == "centroid":
            self._unlock_camera()
            self._update_centroid_button_label()
            return
        now = time.time()
        double_click = (now - self._centroid_last_click_ts) < 0.4
        self._centroid_last_click_ts = now
        self._focus_on_centroid(lock=double_click)
        self._update_centroid_button_label()

    def _on_restore_button_clicked(self):
        """Restore the default camera view."""
        self._clear_selection(update_view=False)
        self._unlock_camera()
        self._update_centroid_button_label()
        self._restore_view()

    def _handle_view_mode_change(self, index):
        """React to user selection from the view dropdown."""
        self._apply_graph_view_mode(index)

    def _initialize_graph_view_selection(self):
        """Apply the view mode requested from the configuration."""
        if not self.view_mode_selector:
            return
        default_index = 0
        self.view_mode_selector.blockSignals(True)
        self.view_mode_selector.setCurrentIndex(default_index)
        self.view_mode_selector.blockSignals(False)
        # Delay applying the mode until the connection graph structures exist.
        QTimer.singleShot(0, lambda: self._apply_graph_view_mode(default_index, initial=True))

    def _apply_graph_view_mode(self, index, initial=False):
        """Show/hide the graph column and update the layout strategy."""
        if not self.graph_views or not self.graph_window:
            return
        if index <= 0:
            self.graph_view_active = False
            if self.graph_window:
                self.graph_window.hide()
        else:
            self.graph_view_active = True
            self.view_mode = "static" if index == 1 else "dynamic"
            if self.graph_window:
                self.graph_window.show()
                self.graph_window.raise_()
                self.graph_window.activateWindow()
            self._recompute_graph_layout()
        self._update_graph_filter_controls()
        if self.graph_view_active:
            self._update_graph_views()
        if not initial:
            self._update_side_container_visibility()
        self.update_scene()

    def _on_graph_filter_changed(self, index):
        """Handle changes to the connection filter switch."""
        mode = "direct" if index == 0 else "indirect"
        if self.graph_filter_mode == mode:
            return
        self.graph_filter_mode = mode
        self._update_graph_views()

    def _set_graph_filter_label(self, *, global_mode: bool) -> None:
        """Adjust the visible label of the first filter option."""
        if not self.graph_filter_selector:
            return
        label = self._graph_filter_labels["global" if global_mode else "local"]
        if self.graph_filter_selector.itemText(0) != label:
            self.graph_filter_selector.blockSignals(True)
            self.graph_filter_selector.setItemText(0, label)
            self.graph_filter_selector.blockSignals(False)

    def _toggle_header_visibility(self):
        """Collapse/expand the top control bar leaving the toggle handle visible."""
        self.header_collapsed = not self.header_collapsed
        self.header_container.setVisible(not self.header_collapsed)
        self.header_toggle.setText("▼" if self.header_collapsed else "▲")
        self._main_layout.activate()

    def _send_shutdown_command(self, reason: str = "gui_closed"):
        """Ask the simulation to stop when the GUI is closing."""
        if not self.gui_control_queue:
            return
        try:
            self.gui_control_queue.put(("shutdown", reason))
        except Exception:
            pass

    def closeEvent(self, event):
        """Ensure auxiliary panels close with the main window."""
        self._send_shutdown_command("gui_close_event")
        try:
            if self.graph_window:
                self.graph_window.force_close()
            if self.spin_window:
                self.spin_window.force_close()
        finally:
            app = self._app_instance()
            if app is not None:
                app.quit()
        try:
            self._shutdown_logging()
        finally:
            super().closeEvent(event)

    def stop_gracefully(self):
        """Request a clean GUI shutdown (flush logs and stop Qt loop)."""
        try:
            self._log_info("GUI shutdown requested")
        except Exception:
            pass
        try:
            self.running = False
            self.step_requested = False
            self.reset = False
            timer = getattr(self, "timer", None)
            if timer:
                timer.stop()
        except Exception:
            pass
        try:
            self._shutdown_logging()
        except Exception:
            pass
        app = self._app_instance()
        if app is not None:
            app.quit()

    def start_simulation(self):
        """Start the simulation."""
        self.gui_control_queue.put("start")
        self.running = True
        self.reset = False

    def reset_simulation(self):
        """Reset the simulation."""
        self._clear_selection(update_view=False)
        self.gui_control_queue.put("reset")
        self.running = False
        self.reset = True

    def stop_simulation(self):
        """Stop the simulation."""
        self.gui_control_queue.put("stop")
        self.running = False

    def step_simulation(self):
        """Execute the simulation."""
        if not self.running:
            self.gui_control_queue.put("step")
            self.step_requested = True
            self.reset = False

    def _on_speed_slider_changed(self, value: int):
        """Update the playback pace and notify the arena."""
        multiplier = value / 20.0
        formatted = f"{multiplier:.2f}"
        self.speed_label.setText(f"{formatted}x")
        if not self.gui_control_queue:
            return
        try:
            self.gui_control_queue.put(("speed", multiplier))
        except Exception:
            pass

    # ----- Keyboard shortcuts -----------------------------------------------
    def keyPressEvent(self, event):
        """Handle basic keyboard shortcuts for simulation control."""
        key = event.key()
        if key == Qt.Key_Space:
            self._toggle_run()
            event.accept()
            return
        if key == Qt.Key_R:
            self.reset_simulation()
            event.accept()
            return
        if key == Qt.Key_E:
            if not self.running:
                self.step_simulation()
            event.accept()
            return
        if key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_KP_Add):
            self._zoom_camera(0.9)
            event.accept()
            return
        if key in (Qt.Key_Minus, Qt.Key_KP_Subtract):
            self._zoom_camera(1.1)
            event.accept()
            return
        if key == Qt.Key_C:
            self._on_centroid_button_clicked()
            event.accept()
            return
        if key == Qt.Key_V:
            self._on_restore_button_clicked()
            event.accept()
            return
        if key == Qt.Key_G and self.view_mode_selector:
            current = self.view_mode_selector.currentIndex()
            new_index = 0 if current != 0 else 1
            self.view_mode_selector.setCurrentIndex(new_index)
            event.accept()
            return
        if key in (Qt.Key_W, Qt.Key_Up):
            self._nudge_camera(0, -1)
            event.accept()
            return
        if key in (Qt.Key_S, Qt.Key_Down):
            self._nudge_camera(0, 1)
            event.accept()
            return
        if key in (Qt.Key_A, Qt.Key_Left):
            self._nudge_camera(-1, 0)
            event.accept()
            return
        if key in (Qt.Key_D, Qt.Key_Right):
            self._nudge_camera(1, 0)
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_run(self):
        """Toggle start/stop."""
        if self.running:
            self.stop_simulation()
        else:
            self.start_simulation()

    def _toggle_graphs_shortcut(self):
        """Toggle graph visibility via keyboard."""
        if not self.view_mode_selector:
            return
        current = self.view_mode_selector.currentIndex()
        new_index = 0 if current != 0 else 1
        self.view_mode_selector.setCurrentIndex(new_index)

    def _register_shortcut(self, seq, callback):
        """Register an application-wide shortcut."""
        sc = QShortcut(QKeySequence(seq), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(callback)

    def _app_instance(self):
        """Provide QApplication.instance() indirection for tests."""
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()
