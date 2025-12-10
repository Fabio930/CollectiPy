# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Data ingestion and plotting helpers for GUI_2D."""
from __future__ import annotations

import math
from typing import Any

from matplotlib import cm

from core.util.logging_util import start_run_logging


class DataMixin:
    """Mixin that updates GUI state from queues and plots."""

    gui_in_queue: Any
    show_spins_enabled: bool
    clicked_spin: Any
    agents_spins: dict
    _log_specs: Any
    _process_name: str
    _current_run: int | None
    _last_tick: int | None
    connection_features_enabled: bool

    def update_spins_plot(self):
        """Update spins plot."""
        if not self.show_spins_enabled:
            return
        if not (self.clicked_spin and self.agents_spins is not None):
            self._clear_selection(update_view=False)
            return
        key, idx = self.clicked_spin
        spins_list = self.agents_spins.get(key)
        if not spins_list or idx >= len(spins_list):
            self._clear_selection(update_view=False)
            return
        spin = spins_list[idx]
        if spin is None:
            self._clear_selection(update_view=False)
            return
        self._show_spin_canvas()
        cmap = cm.get_cmap("coolwarm")
        group_mean_spins = spin[0].mean(axis=1)
        colors_spins = cmap(group_mean_spins)
        group_mean_perception = spin[2].reshape(spin[1][1], spin[1][2]).mean(axis=1)
        normalized_perception = (group_mean_perception + 1) * 0.5
        colors_perception = cmap(normalized_perception)
        angles = spin[1][0][::spin[1][2]]
        width = 2 * math.pi / spin[1][1]
        if self.spins_bars is None or self.perception_bars is None:
            self.ax.clear()
            self.spins_bars = self.ax.bar(
                angles, 0.75, width=width, bottom=0.75,
                color=colors_spins, edgecolor="black", alpha=0.9,
            )
            self.perception_bars = self.ax.bar(
                angles, 0.5, width=width, bottom=1.6,
                color=colors_perception, edgecolor="black", alpha=0.9,
            )
            self.angle_labels = []
            for deg, label in zip([0, 90, 180, 270], ["0°", "90°", "180°", "270°"]):
                rad = math.radians(deg)
                txt = self.ax.text(rad, 2.5, label, ha="center", va="center", fontsize=10)
                self.angle_labels.append(txt)
            self.ax.set_yticklabels([])
            self.ax.set_xticks([])
            self.ax.grid(False)
        else:
            for bar, color in zip(self.spins_bars, colors_spins):
                bar.set_color(color)
            for bar, color in zip(self.perception_bars, colors_perception):
                bar.set_color(color)
        avg_angle = spin[3]
        if avg_angle is not None:
            if self.arrow is not None:
                self.arrow.remove()
            self.arrow = self.ax.annotate(
                "", xy=(avg_angle, 0.5), xytext=(avg_angle, 0.1),
                arrowprops=dict(facecolor="black", arrowstyle="->", lw=2),
            )
        self.ax.set_title(self.clicked_spin[0] + " " + str(self.clicked_spin[1]), fontsize=12, y=1.15)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _pull_latest_gui_payload(self) -> Any:
        """Return the most recent payload from the GUI queue (if any)."""
        if self.gui_in_queue is None:
            return None
        if self.gui_in_queue.qsize() <= 0:
            return None
        data = self.gui_in_queue.get()
        while self.gui_in_queue.qsize() > 0:
            data = self.gui_in_queue.get()
        return data

    def _maybe_rotate_logs(self, payload: Any) -> None:
        """Rotate GUI logging when a new run starts."""
        if not isinstance(payload, dict):
            return
        status = payload.get("status")
        tick_value = None
        if isinstance(status, (list, tuple)) and status:
            try:
                tick_value = int(status[0])
            except Exception:
                tick_value = None

        if self._log_specs is None:
            if tick_value is not None:
                self._last_tick = tick_value
            return

        run_value = payload.get("run")
        try:
            run_number = int(run_value) if run_value is not None else None
        except (TypeError, ValueError):
            run_number = None

        next_run = None
        if run_number is not None:
            if self._current_run is None or run_number > self._current_run:
                next_run = run_number
            elif tick_value == 0 and (self._last_tick is None or self._last_tick > 0):
                next_run = run_number
        elif tick_value == 0:
            if self._current_run is None:
                next_run = 1
            elif self._last_tick is not None and self._last_tick > 0:
                next_run = self._current_run + 1

        if next_run is not None:
            start_run_logging(self._log_specs, self._process_name, next_run)
            self._current_run = next_run
            self._log_info(f"GUI logging started for run {next_run}")

        if tick_value is not None:
            self._last_tick = tick_value

    def update_data(self):
        """Update data."""
        data = self._pull_latest_gui_payload()
        if isinstance(data, dict) and data.get("status") == "shutdown":
            self.stop_gracefully()
            return

        if self.running or self.step_requested:
            if not data:
                # Preserve step intent until we actually consume a payload.
                if self.step_requested and not self.running:
                    return
            else:
                self._maybe_rotate_logs(data)
                self.time = data["status"][0]
                o_shapes = {}
                for key, item in data["objects"].items():
                    o_shapes[key] = item[0]
                self.objects_shapes = o_shapes
                self.agents_shapes = data["agents_shapes"]
                self.agents_spins = data["agents_spins"]
                self._refresh_agent_centers()
                if self.connection_features_enabled:
                    self.agents_metadata = data.get("agents_metadata", {})
                    if self._connection_features_active():
                        self._rebuild_connection_graphs()
                        self._update_graph_views()
                    else:
                        self._clear_connection_caches()
                        self._update_graph_views()
                else:
                    self.agents_metadata = {}
            self.update_scene()
            if self.spin_panel_visible:
                self.update_spins_plot()
            if self.clicked_spin:
                self._update_connection_legend()
            self.update()
            if data:
                self.step_requested = False
        elif self.reset:
            while self.gui_in_queue.qsize() > 0:
                _ = self.gui_in_queue.get()
            self.objects_shapes = {}
            self.agents_shapes = {}
            self.agents_spins = {}
            self.agents_metadata = {}
            self._agent_centers = {}
            self._view_initialized = False
            self._clear_connection_caches()
            self._update_graph_views()
            self._clear_selection(update_view=False)
            self.update_scene()
            self.update()
