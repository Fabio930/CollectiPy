# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Graphical user interface for the simulator."""
import logging, math
import matplotlib.pyplot as plt
from config import Config
from matplotlib.cm import coolwarm
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QGraphicsView, QGraphicsScene, QPushButton, QHBoxLayout, QSizePolicy, QComboBox, QToolButton, QFrame
from PySide6.QtCore import QTimer, Qt, QPointF, QEvent, QRectF
from PySide6.QtGui import QPolygonF, QColor, QPen, QBrush, QMouseEvent

class GuiFactory():

    """Gui factory."""
    @staticmethod
    def create_gui(config_elem:Config,arena_vertices:list,arena_color:str,gui_in_queue,gui_control_queue, wrap_config=None, hierarchy_overlay=None):
        """Create gui."""
        if config_elem.get("_id") in ("2D","abstract"):
            return QApplication([]),GUI_2D(
                config_elem,
                arena_vertices,
                arena_color,
                gui_in_queue,
                gui_control_queue,
                wrap_config=wrap_config,
                hierarchy_overlay=hierarchy_overlay
            )
        else:
            raise ValueError(f"Invalid gui type: {config_elem.get('_id')} valid types are '2D' or 'abstract'")

class GUI_2D(QWidget):
    """2 d."""
    def __init__(self, config_elem: Config,arena_vertices,arena_color,gui_in_queue,gui_control_queue, wrap_config=None, hierarchy_overlay=None):
        """Initialize the instance."""
        super().__init__()
        self.gui_mode = config_elem.get("_id", "2D")
        self.is_abstract = self.gui_mode == "abstract"
        on_click_cfg = config_elem.get("on_click", "show_spins")
        self.on_click_modes = self._parse_mode_list(on_click_cfg)
        if not self.on_click_modes:
            self.on_click_modes = {"show_spins"}
        self.show_spins_enabled = "show_spins" in self.on_click_modes
        view_cfg = config_elem.get("view", config_elem.get("show"))
        self.show_modes = self._parse_mode_list(view_cfg)
        view_mode_cfg = str(config_elem.get("view_mode", "dynamic")).strip().lower()
        self.view_mode = view_mode_cfg if view_mode_cfg in {"static", "dynamic"} else "dynamic"
        self.connection_colors = {
            "messages": QColor(120, 200, 120),
            "detection": QColor(255, 127, 14)
        }
        self.viewable_modes = tuple(mode for mode in ("messages", "detection") if mode in self.show_modes)
        self.arena_vertices = arena_vertices or []
        self.arena_color = arena_color
        self.gui_in_queue = gui_in_queue
        self.gui_control_queue = gui_control_queue
        self.wrap_config = wrap_config
        self.hierarchy_overlay = hierarchy_overlay or []
        self.setWindowTitle("Arena GUI")
        self.setFocusPolicy(Qt.StrongFocus)

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
        self.scale = 1
        self.view = QGraphicsView()
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMinimumWidth(640)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout_change_in_progress = False
        self._last_viewport_width = None
        self._panel_extra_padding = {
            "graph": 200,
            "legend": 80,
            "side": 220
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
        self.spin_panel = None
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
            self.spin_panel = QWidget()
            spin_layout = QVBoxLayout()
            spin_layout.setContentsMargins(0, 0, 0, 0)
            spin_layout.addWidget(self.canvas)
            self.spin_panel.setLayout(spin_layout)
            self.spin_panel.setVisible(False)
        if self.wrap_config:
            hint = QLabel("Wrap-around active (sphere projection)")
            hint.setStyleSheet("color: gray; font-size: 10pt;")
            self._left_layout.addWidget(hint)
        arena_row = QHBoxLayout()
        arena_row.setContentsMargins(0, 0, 0, 0)
        arena_row.setSpacing(8)
        self.graph_container = None
        self.graph_layout = None
        self.graph_views = {}
        self.graph_view_active = False
        self.graph_filter_mode = "direct"
        self.graph_filter_selector = None
        self.graph_filter_widget = None
        self._graph_filter_labels = {
            "local": "I - Local",
            "global": "Global",
            "extended": "II - Extended"
        }
        if self.viewable_modes:
            self.graph_container = QWidget()
            self.graph_container.setMinimumWidth(520)
            self.graph_container.setMaximumWidth(640)
            self.graph_container.setVisible(False)
            self.graph_container.setAutoFillBackground(True)
            self.graph_container.setStyleSheet("background-color: #2f2f2f; border-radius: 6px;")
            self.graph_layout = QVBoxLayout()
            self.graph_layout.setContentsMargins(16, 16, 16, 16)
            self.graph_layout.setSpacing(16)
            self.graph_container.setLayout(self.graph_layout)
            for mode in self.viewable_modes:
                title = "Messages graph" if mode == "messages" else "Detection graph"
                graph_widget = NetworkGraphWidget(title, self.connection_colors[mode], title_color="#f5f5f5")
                graph_widget.setVisible(True)
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
            arena_row.addWidget(self.graph_container)
        else:
            self.graph_container = None
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
        self.side_container = None
        self.side_layout = None
        if self.spin_panel is not None:
            self.side_container = QWidget()
            self.side_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.side_container.setMinimumWidth(260)
            self.side_layout = QVBoxLayout()
            self.side_layout.setContentsMargins(0, 0, 0, 0)
            self.side_container.setLayout(self.side_layout)
            self.side_container.setVisible(False)
            self.side_layout.addWidget(self.spin_panel)
            self.side_layout.addStretch()
        self._main_layout.addLayout(self._left_layout)
        if self.side_container is not None:
            self._main_layout.addWidget(self.side_container)
        self.setLayout(self._main_layout)
        self._update_legend_column_visibility()
        if self.view_mode_selector and self.graph_container is not None:
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
            "detection": {"nodes": [], "edges": []}
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
        self.resizeEvent(None)
        self.timer = QTimer(self)
        self.connection = self.timer.timeout.connect(self.update_data)
        self.timer.start(1)
        logging.info("GUI created successfully")

    def eventFilter(self, watched, event):
        """Handle Qt event filtering."""
        if watched == self.view.viewport():
            if event.type() == QEvent.Type.Resize:
                self._sync_scene_rect_with_view()
                self.update_scene()
                return False
            if event.type() == QEvent.Type.MouseButtonPress:
                if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                    scene_pos = self.view.mapToScene(event.pos())
                    if self.is_abstract:
                        item = self.scene.itemAt(scene_pos, self.view.transform())
                        data = item.data(0) if item is not None else None
                        new_selection = data if isinstance(data, tuple) else None
                    else:
                        new_selection = self.get_agent_at(scene_pos)
                    if new_selection is None:
                        if self.clicked_spin is not None:
                            self._clear_selection()
                    elif new_selection == self.clicked_spin:
                        self._clear_selection()
                    else:
                        self.clicked_spin = new_selection
                        self._show_spin_canvas()
                        self.update_spins_plot()
                        self._update_connection_legend()
                        self._update_graph_filter_controls()
                        self._update_graph_views()
                        self.update_scene()
                return True
        return super().eventFilter(watched, event)

    def _show_spin_canvas(self):
        """Ensure the spin plot canvas is visible."""
        if not self.show_spins_enabled or self.spin_panel is None or self.spin_panel_visible:
            return
        self.spin_panel_visible = True
        self.spin_panel.setVisible(True)
        self._update_side_container_visibility()
        self.adjustSize()

    def _hide_spin_canvas(self):
        """Hide the spin plot canvas if it is visible."""
        if not self.show_spins_enabled or not self.spin_panel_visible or self.spin_panel is None:
            return
        self.spin_panel_visible = False
        self.spin_panel.setVisible(False)
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
        if not self.side_container:
            return
        needs_side_panel = bool(self.spin_panel_visible)
        previous = self.side_container.isVisible()
        previous_width = self._capture_viewport_width()
        self.side_container.setVisible(needs_side_panel)
        if previous != needs_side_panel:
            self._main_layout.activate()
            padding = self._panel_extra_padding.get("side", 0) if needs_side_panel else 0
            self._preserve_arena_view_width(previous_width, padding)
            self.adjustSize()

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
        if not self.graph_views:
            return
        previous_width = self._capture_viewport_width()
        previous_visibility = self.graph_container.isVisible() if self.graph_container else False
        if index <= 0:
            self.graph_view_active = False
            if self.graph_container:
                self.graph_container.setVisible(False)
        else:
            self.graph_view_active = True
            self.view_mode = "static" if index == 1 else "dynamic"
            if self.graph_container:
                self.graph_container.setVisible(True)
            self._recompute_graph_layout()
        if self.graph_container:
            current_visibility = self.graph_container.isVisible()
        else:
            current_visibility = False
        self._update_graph_filter_controls()
        if self.graph_view_active:
            self._update_graph_views()
        if previous_visibility != current_visibility:
            self._main_layout.activate()
            padding = self._panel_extra_padding.get("graph", 0) if current_visibility else 0
            self._preserve_arena_view_width(previous_width, padding)
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
    def _recompute_graph_layout(self):
        """Rebuild the graph layout using the current mode."""
        if not self.connection_graphs or not self.connection_graphs.get("messages"):
            self._graph_layout_coords = {}
            return
        nodes = self.connection_graphs["messages"].get("nodes", [])
        self._graph_layout_coords = self._select_graph_layout(nodes)

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
        if not self._graph_filter_active():
            return None
        index_map = self._graph_index_map.get(mode) or {}
        adjacency = self.connection_lookup.get(mode) or {}
        selected_idx = index_map.get(self.clicked_spin)
        if selected_idx is None:
            return None
        highlight = {
            "nodes": set([selected_idx]),
            "edges": set(),
            "selected": selected_idx
        }
        if self.graph_filter_mode == "direct":
            neighbors = adjacency.get(self.clicked_spin, set())
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
        self._hide_spin_canvas()
        if self.legend_widget:
            self.legend_widget.update_entries([])
        self._update_graph_filter_controls()
        self._update_graph_views()
        self._update_side_container_visibility()
        if update_view:
            self.update_scene()
    
    def get_agent_at(self, scene_pos):
        """Return the agent at."""
        if self.agents_shapes is not None:
            for key, entities in self.agents_shapes.items():
                for idx, entity in enumerate(entities):
                    vertices = entity.vertices()
                    polygon = QPolygonF([
                        QPointF(
                            vertex.x * self.scale + self.offset_x,
                            vertex.y * self.scale + self.offset_y
                        )
                        for vertex in vertices
                    ])
                    if polygon.containsPoint(scene_pos, Qt.FillRule.OddEvenFill):
                        return key, idx
        return None

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
        if previous_width is None or self._layout_change_in_progress:
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

    def resizeEvent(self, event):
        """Handle Qt resize events."""
        super().resizeEvent(event)
        self._sync_scene_rect_with_view()
        self.update_scene()

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

    # ----- Keyboard shortcuts -----------------------------------------------
    def keyPressEvent(self, event):
        """Handle basic keyboard shortcuts for simulation control."""
        key = event.key()
        if key == Qt.Key_Space:
            if self.running:
                self.stop_simulation()
            else:
                self.start_simulation()
            event.accept()
            return
        if key == Qt.Key_R:
            self.reset_simulation()
            event.accept()
            return
        if key == Qt.Key_S:
            if not self.running:
                self.step_simulation()
            event.accept()
            return
        super().keyPressEvent(event)

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
        group_mean_spins = spin[0].mean(axis=1)
        colors_spins = coolwarm(group_mean_spins)
        group_mean_perception = spin[2].reshape(spin[1][1], spin[1][2]).mean(axis=1)
        normalized_perception = (group_mean_perception + 1) * 0.5
        colors_perception = coolwarm(normalized_perception)
        angles = spin[1][0][::spin[1][2]]
        width = 2 * math.pi / spin[1][1]
        if self.spins_bars is None or self.perception_bars is None:
            self.ax.clear()
            self.spins_bars = self.ax.bar(
                angles, 0.75, width=width, bottom=0.75,
                color=colors_spins, edgecolor="black", alpha=0.9
            )
            self.perception_bars = self.ax.bar(
                angles, 0.5, width=width, bottom=1.6,
                color=colors_perception, edgecolor="black", alpha=0.9
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
        self.ax.set_title(self.clicked_spin[0]+" "+str(self.clicked_spin[1]), fontsize=12, y=1.15)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def update_data(self):
        """Update data."""
        if self.running or self.step_requested:
            if self.gui_in_queue.qsize() > 0:
                data = self.gui_in_queue.get()
                self.time = data["status"][0]
                o_shapes = {}
                for key, item in data["objects"].items():
                    o_shapes[key] = item[0]
                self.objects_shapes = o_shapes
                self.agents_shapes = data["agents_shapes"]
                self.agents_spins = data["agents_spins"]
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
            self.step_requested = False
        elif self.reset:
            while self.gui_in_queue.qsize() > 0:
                _ = self.gui_in_queue.get()
            self.objects_shapes = {}
            self.agents_shapes = {}
            self.agents_spins = {}
            self.agents_metadata = {}
            self._clear_connection_caches()
            self._update_graph_views()
            self._clear_selection(update_view=False)
            self.update_scene()
            self.update()

    def draw_arena(self):
        """Draw arena."""
        if not self.arena_vertices:
            return
        view_width = self.view.viewport().width()
        view_height = self.view.viewport().height()
        min_x = min(v.x for v in self.arena_vertices)
        min_y = min(v.y for v in self.arena_vertices)
        max_x = max(v.x for v in self.arena_vertices)
        max_y = max(v.y for v in self.arena_vertices)
        arena_width = max_x - min_x
        arena_height = max_y - min_y
        margin_x = 40
        margin_y = 40
        scale_x = (view_width - 2 * margin_x) / arena_width if arena_width > 0 else 1
        scale_y = (view_height - 2 * margin_y) / arena_height if arena_height > 0 else 1
        self.scale = min(scale_x, scale_y)
        self.offset_x = margin_x - min_x * self.scale
        self.offset_y = margin_y - min_y * self.scale
        transformed_vertices = [
            QPointF(
                v.x * self.scale + self.offset_x,
                v.y * self.scale + self.offset_y
            )
            for v in self.arena_vertices
        ]
        polygon = QPolygonF(transformed_vertices)
        pen = QPen(Qt.black, 2)
        if self.wrap_config:
            pen.setStyle(Qt.DashLine)
        brush = QBrush(QColor(self.arena_color))
        if self.wrap_config and self.wrap_config.get("projection") == "ellipse":
            rect = polygon.boundingRect()
            self.scene.addEllipse(rect, pen, brush)
        else:
            self.scene.addPolygon(polygon, pen, brush)
        if self.wrap_config:
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
                (bounds[3] - bounds[1]) * self.scale
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
                    rect.center().y() - label_rect.height() / 2
                )

    def _draw_abstract_dots(self):
        """Render agents as a grid of dots in abstract mode."""
        self.abstract_dot_items = []
        if not self.is_abstract:
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
        self.scene.clear()
        if self.is_abstract or not self.arena_vertices:
            self._draw_abstract_dots()
            return
        self.draw_arena()
        scale = self.scale
        offset_x = self.offset_x
        offset_y = self.offset_y

        if self.objects_shapes is not None:
            for entities in self.objects_shapes.values():
                for entity in entities:
                    vertices = entity.vertices()
                    for dx, dy in self._wrap_offsets(vertices):
                        entity_vertices = [
                            QPointF(
                                (vertex.x + dx) * scale + offset_x,
                                (vertex.y + dy) * scale + offset_y
                            )
                            for vertex in vertices
                        ]
                        entity_color = QColor(entity.color())
                        entity_polygon = QPolygonF(entity_vertices)
                        self.scene.addPolygon(entity_polygon, QPen(entity_color, .1), QBrush(entity_color))

        if self.agents_shapes is not None:
            for key, entities in self.agents_shapes.items():
                for idx, entity in enumerate(entities):
                    vertices = entity.vertices()
                    offsets = self._wrap_offsets(vertices)
                    for dx, dy in offsets:
                        entity_vertices = [
                            QPointF(
                                (vertex.x + dx) * scale + offset_x,
                                (vertex.y + dy) * scale + offset_y
                            )
                            for vertex in vertices
                        ]
                        entity_color = QColor(entity.color())
                        entity_polygon = QPolygonF(entity_vertices)
                        self.scene.addPolygon(entity_polygon, QPen(entity_color, .1), QBrush(entity_color))
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
                                QBrush(Qt.NoBrush)
                            )
                    attachments = entity.get_attachments()
                    for attachment in attachments:
                        att_vertices = attachment.vertices()
                        for dx, dy in offsets:
                            attachment_vertices = [
                                QPointF(
                                    (vertex.x + dx) * scale + offset_x,
                                    (vertex.y + dy) * scale + offset_y
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
        if self.is_abstract or not self.clicked_spin or not self.connection_features_enabled:
            return
        selected_id = self.clicked_spin
        center = self._agent_centers.get(selected_id)
        if center is None:
            return
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

    def _connection_features_active(self) -> bool:
        """Return True when connection overlays or graphs must be rendered."""
        if not self.connection_features_enabled:
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
        if not self.connection_features_enabled:
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
                    "meta": meta
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
                    node_a["pos"].y - node_b["pos"].y
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
        if self.view_mode == "static":
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
                0.5 + radius * math.sin(angle)
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
        enable_a = bool(meta_a.get("msg_enable"))
        enable_b = bool(meta_b.get("msg_enable"))
        if not (enable_a and enable_b):
            return False
        range_a = float(meta_a.get("msg_comm_range", 0.0))
        range_b = float(meta_b.get("msg_comm_range", 0.0))
        if range_a <= 0 or range_b <= 0:
            return False
        limit = min(range_a, range_b)
        return math.isinf(limit) or distance <= limit

    def _should_link_detection(self, meta_a, meta_b, distance):
        """Return True if either agent can detect the other."""
        range_a = float(meta_a.get("detection_range", math.inf))
        range_b = float(meta_b.get("detection_range", math.inf))
        cond_a = range_a > 0 and (math.isinf(range_a) or distance <= range_a)
        cond_b = range_b > 0 and (math.isinf(range_b) or distance <= range_b)
        return cond_a or cond_b

    def _update_graph_views(self):
        """Refresh the auxiliary graph widgets with the latest data."""
        if not self.graph_views or not self.connection_features_enabled:
            return
        layout = self._graph_layout_coords
        for mode, widget in self.graph_views.items():
            graph_data = self.connection_graphs.get(mode, {"nodes": [], "edges": []})
            highlight = self._build_graph_highlight(mode)
            widget.update_graph(graph_data["nodes"], graph_data["edges"], layout, highlight)

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


class NetworkGraphWidget(QWidget):
    """Simple widget that renders an interaction graph."""

    def __init__(self, title: str, edge_color: QColor, title_color = "black"):
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
                    pad_y + norm[1] * draw_h
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
                    pad_y + norm_y * draw_h
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
        for idx_a, idx_b in edges:
            if idx_a not in coords or idx_b not in coords:
                continue
            edge_key = tuple(sorted((idx_a, idx_b)))
            if highlight_active:
                color = self.edge_color if edge_key in highlight_edges else dim_edge_color
                width = 2.0 if edge_key in highlight_edges else 1.0
            else:
                color = self.edge_color
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
            highlight_nodes = highlight.get("nodes", set()) or set()
            selected_index = highlight.get("selected")
        highlight_active = bool(highlight_edges or highlight_nodes)
        for idx, node in enumerate(nodes):
            if idx not in coords:
                continue
            px, py = coords[idx]
            fill_color = QColor(node.get("color") or "#ffffff")
            node_brush = QBrush(fill_color if (not highlight_active or idx in highlight_nodes) else self._dim_color(fill_color))
            ellipse = self._scene.addEllipse(
                px - node_radius,
                py - node_radius,
                node_radius * 2,
                node_radius * 2,
                node_pen,
                node_brush
            )
            ellipse.setToolTip(node.get("label", ""))
            text_value = node.get("short_label") or node.get("label", "")
            label = self._scene.addText(text_value)
            label.setDefaultTextColor(Qt.black)
            label_rect = label.boundingRect()
            label.setPos(
                px - label_rect.width() / 2,
                py - node_radius - label_rect.height() - 2
            )
            if highlight_active and idx not in highlight_nodes:
                ellipse.setOpacity(0.35)
                label.setOpacity(0.35)
            if selected_index is not None and idx == selected_index:
                halo_pen = QPen(Qt.black, 1.5)
                halo_pen.setCosmetic(True)
                self._scene.addEllipse(
                    px - node_radius - 4,
                    py - node_radius - 4,
                    (node_radius + 4) * 2,
                    (node_radius + 4) * 2,
                    halo_pen
                )

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
