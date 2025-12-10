# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Auxiliary GUI panels."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt


class DetachedPanelWindow(QWidget):
    """Window container for detached auxiliary panels."""

    def __init__(self, title: str, close_callback: Callable | None = None):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.Window, True)  # type: ignore[attr-defined]
        self._close_callback = close_callback
        self.setAttribute(Qt.WA_DeleteOnClose, False)  # type: ignore[attr-defined]
        self._force_close = False

    def closeEvent(self, event):
        if self._close_callback:
            self._close_callback()
        if self._force_close:
            event.accept()
            return
        event.ignore()
        self.hide()

    def force_close(self):
        """Close the window bypassing the hide-on-close behavior."""
        self._force_close = True
        try:
            self.close()
        finally:
            self._force_close = False
