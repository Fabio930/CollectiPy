# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""2D GUI implementation."""
from __future__ import annotations

import math
from typing import Any, Optional, cast

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtCore import Qt, QPointF, Signal, QTimer, QRectF, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QGraphicsView,
    QGraphicsScene,
    QPushButton,
    QHBoxLayout,
    QSizePolicy,
    QComboBox,
    QToolButton,
    QFrame,
    QSlider,
)

from core.gui.camera_mixin import CameraMixin
from core.gui.connections_mixin import ConnectionsMixin
from core.gui.controls_mixin import ControlsMixin
from core.gui.data_mixin import DataMixin
from core.gui.render_mixin import RenderMixin
from core.gui.panels import DetachedPanelWindow
from core.gui.widgets import ConnectionLegendWidget, NetworkGraphWidget
from core.util.logging_util import get_logger, shutdown_logging

logger = get_logger("gui")
# Help static analyzers with Qt dynamic attributes/constants.
Qt = cast(Any, Qt)
QSizePolicy = cast(Any, QSizePolicy)
QFrame = cast(Any, QFrame)
QEvent = cast(Any, QEvent)
QGraphicsView = cast(Any, QGraphicsView)


class GUI_2D(CameraMixin, ConnectionsMixin, RenderMixin, ControlsMixin, DataMixin, QWidget):
    """2D GUI implementation."""

    # Signal declaration kept for backward compatibility if ever used externally.
    agent_selected = Signal(object, bool)

    def __init__(
        self,
        config_elem: Any,
        arena_vertices,
        arena_color,
        gui_in_queue,
        gui_control_queue,
        wrap_config=None,
        hierarchy_overlay=None,
        log_context=None,
    ):
        """Initialize the instance."""
        super().__init__()
        self.gui_mode = config_elem.get("_id", "2D")
        self.is_abstract = self.gui_mode == "abstract"
        on_click_cfg = config_elem.get("on_click", "spins")
        self.on_click_modes = self._parse_mode_list(on_click_cfg)
        if not self.on_click_modes:
            self.on_click_modes = {"spins"}
        self.show_spins_enabled = "spins" in self.on_click_modes
        view_cfg = config_elem.get("view", config_elem.get("show"))
        self.show_modes = self._parse_mode_list(view_cfg)
        view_mode_cfg = str(config_elem.get("view_mode", "dynamic")).strip().lower()
        self.view_mode = view_mode_cfg if view_mode_cfg in {"static", "dynamic"} else "dynamic"
        self.connection_colors = {
            "messages": QColor(120, 200, 120),
            "detection": QColor(255, 127, 14),
        }
        self.viewable_modes = tuple(mode for mode in ("messages", "detection") if mode in self.show_modes)
        self.arena_vertices = arena_vertices or []
        self.arena_color = arena_color
        self.gui_in_queue = gui_in_queue
        self.gui_control_queue = gui_control_queue
        log_context = log_context or {}
        self._log_specs = log_context.get("log_specs")
        self._process_name = log_context.get("process_name", "gui")
        self._current_run: Optional[int] = None
        self._last_tick: Optional[int] = None
        self.wrap_config = wrap_config
        self.unbounded_mode = bool(wrap_config and wrap_config.get("unbounded"))
        self._unbounded_rect: Optional[QRectF] = None
        self.hierarchy_overlay = hierarchy_overlay or []
        self.setWindowTitle("Arena GUI")
        self.setFocusPolicy(Qt.StrongFocus)
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._view_rect = None
        self._view_initialized = False
        self._camera_lock = None  # ("agent", key) or ("centroid", None)
        self._panning = False
        self._pan_last_scene_pos = None
        self._centroid_last_click_ts = 0.0
        self._keyboard_pan_factor = 0.12
        self._zoom_min_span = 1e-3

        self._main_layout = QHBoxLayout()
        self._left_layout = QVBoxLayout()
        self.header_container = QFrame()
        self.header_container.setFrameShape(QFrame.NoFrame)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self.data_label = QLabel("Waiting for data...")
        header_layout.addWidget(self.data_label)
        self.button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.step_button = QPushButton("Step")
        self.reset_button = QPushButton("Reset")
        self.button_layout.addWidget(self.start_button)
        self.button_layout.addWidget(self.stop_button)
        self.button_layout.addWidget(self.step_button)
        self.button_layout.addWidget(self.reset_button)
        self.view_mode_selector = None
        self.view_mode_label = None
        if self.viewable_modes:
            self.view_mode_label = QLabel("Graphs")
            self.view_mode_label.setStyleSheet("font-weight: bold;")
            self.view_mode_selector = QComboBox()
            self.view_mode_selector.addItems(["Hide", "Static", "Dynamic"])
            self.view_mode_selector.currentIndexChanged.connect(self._handle_view_mode_change)
            self.button_layout.addWidget(self.view_mode_label)
            self.button_layout.addWidget(self.view_mode_selector)
        header_layout.addLayout(self.button_layout)
        self.view_controls_layout = QHBoxLayout()
        self.centroid_button = QPushButton("Centroid")
        self.restore_button = QPushButton("Restore View")
        self.view_controls_layout.addWidget(self.centroid_button)
        self.view_controls_layout.addWidget(self.restore_button)
        header_layout.addLayout(self.view_controls_layout)
        self.speed_layout = QHBoxLayout()
        self.speed_layout.setSpacing(4)
        self.speed_layout.setContentsMargins(0, 0, 0, 0)
        self.speed_layout.addWidget(QLabel("Playback pace:"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(20, 40)  # represent 1.0–2.0 with finer steps
        self.speed_slider.setValue(20)
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setToolTip("1.0 = native speed, 2.0 = slowest playback")
        self.speed_slider.setMinimumWidth(120)
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        self.speed_layout.addWidget(self.speed_slider, stretch=1)
        self.speed_label = QLabel("1.0x")
        self.speed_layout.addWidget(self.speed_label)
        header_layout.addLayout(self.speed_layout)
        self.header_container.setLayout(header_layout)
        self.header_collapsed = False
        self.header_toggle = QToolButton()
        self.header_toggle.setText("▲")
        self.header_toggle.setToolTip("Collapse/expand controls")
        self.header_toggle.setAutoRaise(True)
        self.header_toggle.clicked.connect(self._toggle_header_visibility)
        self.header_toggle.setStyleSheet("QToolButton { font-weight: bold; }")
        self._left_layout.addWidget(self.header_container)
        self._left_layout.addWidget(self.header_toggle, alignment=Qt.AlignHCenter)
        self.legend_widget = ConnectionLegendWidget()
        self.legend_widget.setVisible(False)
        self.start_button.clicked.connect(self.start_simulation)
        self.stop_button.clicked.connect(self.stop_simulation)
        self.step_button.clicked.connect(self.step_simulation)
        self.reset_button.clicked.connect(self.reset_simulation)
        self.centroid_button.clicked.connect(self._on_centroid_button_clicked)
        self.restore_button.clicked.connect(self._on_restore_button_clicked)
        self.view = QGraphicsView()
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMinimumWidth(640)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setFocusPolicy(Qt.NoFocus)
        self._layout_change_in_progress = False
        self._last_viewport_width = None
        self._panel_extra_padding = {
            "legend": 80,
        }
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 800, 800)
        self.scene.setBackgroundBrush(QColor(240, 240, 240))
        self.view.setScene(self.scene)

        self.clicked_spin = None
        self.spins_bars = None
        self.perception_bars = None
        self.arrow = None
        self.angle_labels = []
        self.spin_window = None
        self.spin_panel_visible = False
        self.abstract_dot_items = []
        markers_cfg = config_elem.get("abstract_markers", {})
        self.abstract_dot_size = max(2, int(markers_cfg.get("size", 10)))
        self.abstract_dot_spacing = max(0, int(markers_cfg.get("spacing", 4)))
        self.abstract_dot_margin = max(0, int(markers_cfg.get("margin", 10)))
        self.abstract_dot_default_color = markers_cfg.get("default_color", "black")
        if self.show_spins_enabled:
            self.figure, self.ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(4, 4))
            self.canvas = FigureCanvas(self.figure)
            self.canvas.setMinimumSize(320, 320)
            self.canvas.setMaximumWidth(360)
            self.spin_window = DetachedPanelWindow("Spin Model", close_callback=self._on_spin_window_closed)
            self.spin_window.setFocusPolicy(Qt.NoFocus)
            self.spin_window.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
            self.spin_window.setAttribute(Qt.WA_ShowWithoutActivating, True)
            spin_layout = QVBoxLayout()
            spin_layout.setContentsMargins(0, 0, 0, 0)
            spin_layout.addWidget(self.canvas)
            self.spin_window.setLayout(spin_layout)
            self.spin_window.setVisible(False)
            hint = self.spin_window.sizeHint()
            if hint.isValid():
                self.spin_window.setFixedSize(hint)
        arena_row = QHBoxLayout()
        arena_row.setContentsMargins(0, 0, 0, 0)
        arena_row.setSpacing(8)
        self.graph_window = None
        self.graph_layout = None
        self.graph_views = {}
        self.graph_view_active = False
        self.graph_filter_mode = "direct"
        self.graph_filter_selector = None
        self.graph_filter_widget = None
        self._graph_filter_labels = {
            "local": "I - Local",
            "global": "Global",
            "extended": "II - Extended",
        }
        if self.viewable_modes:
            self.graph_window = DetachedPanelWindow("Connection Graphs", close_callback=self._on_graph_window_closed)
            self.graph_window.setMinimumWidth(720)
            self.graph_window.setMaximumWidth(720)
            self.graph_window.setAutoFillBackground(True)
            self.graph_window.setStyleSheet("background-color: #2f2f2f; border-radius: 6px;")
            self.graph_layout = QVBoxLayout()
            self.graph_layout.setContentsMargins(16, 16, 16, 16)
            self.graph_layout.setSpacing(16)
            self.graph_window.setLayout(self.graph_layout)
            self.graph_window.setVisible(False)
            self.graph_window.setMinimumHeight(540)
            self.graph_window.setMaximumHeight(540)
            self.graph_window.setFixedSize(720, 540)
            for mode in self.viewable_modes:
                title = "Messages graph" if mode == "messages" else "Detection graph"
                graph_widget = NetworkGraphWidget(title, self.connection_colors[mode], title_color="#f5f5f5")
                graph_widget.setVisible(True)
                graph_widget.agent_selected.connect(self._handle_graph_agent_selection)
                self.graph_views[mode] = graph_widget
                self.graph_layout.addWidget(graph_widget)
            if self.graph_views:
                self.graph_layout.addStretch()
            self.graph_filter_widget = QWidget()
            filter_layout = QHBoxLayout()
            filter_layout.setContentsMargins(4, 4, 4, 4)
            filter_layout.setSpacing(6)
            filter_label = QLabel("Connections")
            filter_label.setStyleSheet("color: #f5f5f5; font-weight: bold;")
            self.graph_filter_selector = QComboBox()
            self.graph_filter_selector.addItems(["I - Local", "II - Extended"])
            self.graph_filter_selector.currentIndexChanged.connect(self._on_graph_filter_changed)
            self.graph_filter_selector.setEnabled(False)
            self._set_graph_filter_label(global_mode=True)
            self.graph_filter_selector.setCurrentIndex(0)
            self.graph_filter_selector.setStyleSheet(
                "QComboBox { color: #161616; background-color: #f4f4f4; border: 1px solid #d0d0d0; "
                "border-radius: 6px; padding: 2px 6px; }"
                "QComboBox::drop-down { border: none; }"
            )
            filter_layout.addWidget(filter_label)
            filter_layout.addWidget(self.graph_filter_selector)
            filter_layout.addStretch()
            self.graph_filter_widget.setLayout(filter_layout)
            self.graph_filter_widget.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.12); border: 1px solid #bcbcbc; border-radius: 8px;"
            )
            self.graph_filter_widget.setVisible(False)
            self.graph_layout.addWidget(self.graph_filter_widget)
        else:
            self.graph_window = None
            self.graph_layout = None
            self.graph_filter_widget = None
            self.graph_filter_selector = None
        arena_row.addWidget(self.view, 1)
        self.legend_column = None
        if self.legend_widget is not None:
            self.legend_column = QWidget()
            self.legend_column.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
            self.legend_column.setMinimumWidth(110)
            self.legend_column.setMaximumWidth(160)
            legend_layout = QVBoxLayout()
            legend_layout.setContentsMargins(4, 4, 4, 4)
            legend_layout.setSpacing(6)
            legend_layout.addWidget(self.legend_widget)
            legend_layout.addStretch()
            self.legend_column.setLayout(legend_layout)
            self.legend_column.setVisible(False)
            arena_row.addWidget(self.legend_column)
        self._left_layout.addLayout(arena_row)
        self._main_layout.addLayout(self._left_layout)
        self.setLayout(self._main_layout)
        self._update_legend_column_visibility()
        if self.view_mode_selector and self.graph_window is not None:
            self.view_mode_selector.setEnabled(True)
            self._initialize_graph_view_selection()
        elif self.view_mode_selector:
            self.view_mode_selector.setEnabled(False)
        showable_modes = self.on_click_modes | self.show_modes
        self.connection_features_enabled = bool(self.graph_views) or bool({"messages", "detection"} & showable_modes)
        self.time = 0
        self.objects_shapes = {}
        self.agents_shapes = {}
        self.agents_spins = {}
        self.agents_metadata = {}
        self.connection_lookup = {"messages": {}, "detection": {}}
        self.connection_graphs = {
            "messages": {"nodes": [], "edges": []},
            "detection": {"nodes": [], "edges": []},
        }
        self._graph_layout_coords = {}
        self._static_layout_cache = {}
        self._static_layout_ids = []
        self._graph_index_map = {"messages": {}, "detection": {}}
        self._agent_centers = {}
        self.running = False
        self.reset = False
        self.step_requested = False
        self.view.viewport().installEventFilter(self)
        # Keyboard shortcuts (use shortcuts to avoid focus issues).
        self._register_shortcut("+", lambda: self._zoom_camera(0.9))
        self._register_shortcut("=", lambda: self._zoom_camera(0.9))
        self._register_shortcut("Ctrl++", lambda: self._zoom_camera(0.9))
        self._register_shortcut("Ctrl+=", lambda: self._zoom_camera(0.9))
        self._register_shortcut("-", lambda: self._zoom_camera(1.1))
        self._register_shortcut("Ctrl+-", lambda: self._zoom_camera(1.1))
        for seq in ("W", "Up"):
            self._register_shortcut(seq, lambda: self._nudge_camera(0, -1))
        for seq in ("S", "Down"):
            self._register_shortcut(seq, lambda: self._nudge_camera(0, 1))
        for seq in ("A", "Left"):
            self._register_shortcut(seq, lambda: self._nudge_camera(-1, 0))
        for seq in ("D", "Right"):
            self._register_shortcut(seq, lambda: self._nudge_camera(1, 0))
        self._register_shortcut("Space", self._toggle_run)
        self._register_shortcut("R", self.reset_simulation)
        self._register_shortcut("E", self.step_simulation)
        self._register_shortcut("C", self._on_centroid_button_clicked)
        self._register_shortcut("V", self._on_restore_button_clicked)
        if self.view_mode_selector:
            self._register_shortcut("G", self._toggle_graphs_shortcut)
        self.resizeEvent(None)
        self.timer = QTimer(self)
        self.connection = self.timer.timeout.connect(self.update_data)
        self.timer.start(1)
        logger.info("GUI created successfully")

    @staticmethod
    def _parse_mode_list(value):
        """Normalize configuration entries that can be str or list."""
        if value is None:
            return set()
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if str(item).strip()]
        else:
            parts = []
        return {part.lower() for part in parts}

    @staticmethod
    def _resolve_shape_color(shape):
        """Return the color associated with a shape."""
        if hasattr(shape, "color"):
            try:
                return shape.color()
            except Exception:
                return "#ffffff"
        return "#ffffff"

    def _recompute_graph_layout(self):
        """Rebuild the graph layout using the current mode."""
        if not self.connection_graphs or not self.connection_graphs.get("messages"):
            self._graph_layout_coords = {}
            return
        nodes = self.connection_graphs["messages"].get("nodes", [])
        self._graph_layout_coords = self._select_graph_layout(nodes)

    def _log_info(self, message: str):
        """Log helper used by mixins."""
        try:
            logger.info(message)
        except Exception:
            pass

    def _shutdown_logging(self):
        """Isolate logging shutdown for reuse in mixins."""
        try:
            shutdown_logging()
        except Exception:
            pass
