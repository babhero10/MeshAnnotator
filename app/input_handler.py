"""
InputHandler — tablet and mouse input state machine.

Single Responsibility: translate raw Qt input events into semantic signals
(paint_started, paint_moved, paint_ended, nav_started, nav_moved, nav_ended).

XPen/tablet fixes applied here:
- Pressure applied at TabletPress (first contact), not only on TabletMove
- Eraser detection with Linux fallback (some drivers report UnknownPointer)
- Configurable barrel button (default MiddleButton; set RightButton for XPen)
- reset() clears stuck _tablet_active when pen leaves widget or proximity ends
"""
from __future__ import annotations
from enum import Enum, auto

from PyQt6.QtCore import Qt, QEvent, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QTabletEvent


class NavMode(Enum):
    ROTATE = auto()
    PAN    = auto()
    ZOOM   = auto()


class InputHandler(QObject):
    paint_started = pyqtSignal()
    paint_moved   = pyqtSignal(float, float, float, int)  # x, y, radius, color_override
    paint_ended   = pyqtSignal()
    nav_started   = pyqtSignal(NavMode)
    nav_moved     = pyqtSignal(int, int)                  # dx, dy
    nav_ended     = pyqtSignal()

    # XP-Pen Linux maps the barrel button to RightButton.
    # Wacom and most others use MiddleButton.
    # We accept both so no driver config is needed.
    _TABLET_BARREL = Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton

    def __init__(self, brush_radius: int = 15,
                 mouse_nav_button: Qt.MouseButton = Qt.MouseButton.MiddleButton,
                 parent=None):
        super().__init__(parent)
        self.brush_radius     = brush_radius
        self.mouse_nav_button = mouse_nav_button
        self._painting        = False
        self._tablet_active   = False
        self._nav_active      = False
        self._nav_mode        = NavMode.ROTATE
        self._last_pos        = QPoint()
        self._mouse_nav_btn   = Qt.MouseButton.MiddleButton
        self._eraser_mode     = False

    def set_eraser_from_proximity(self, is_eraser: bool):
        """Called on TabletEnterProximity to know which end of the pen is active."""
        self._eraser_mode = is_eraser

    # ------------------------------------------------------------------
    # State reset
    # ------------------------------------------------------------------

    def reset(self):
        """Force-clear all active states. Call from leaveEvent or TabletLeaveProximity."""
        if self._painting:
            self._painting = False
            self.paint_ended.emit()
        if self._nav_active:
            self._nav_active = False
            self.nav_ended.emit()
        self._tablet_active = False

    # ------------------------------------------------------------------
    # Tablet
    # ------------------------------------------------------------------

    def handle_tablet(self, event: QTabletEvent,
                      pos: QPoint | None = None) -> bool:
        pos    = pos if pos is not None else event.position().toPoint()
        etype  = event.type()
        mod    = event.modifiers()
        barrel = bool(event.buttons() & self._TABLET_BARREL)

        # Nav release — MUST be checked before the barrel block.
        if self._nav_active and etype == QEvent.Type.TabletRelease:
            self._nav_active = False
            self.nav_ended.emit()
            event.accept()
            return True

        # Barrel held but nav started via mouse path — forward moves to nav.
        if self._nav_active and not barrel and etype == QEvent.Type.TabletMove:
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            self._last_pos = pos
            if dx or dy:
                self.nav_moved.emit(dx, dy)
            event.accept()
            return True

        if barrel:
            if not self._nav_active:
                self._nav_mode   = self._nav_mode_from(mod)
                self._nav_active = True
                self._last_pos   = pos
                self.nav_started.emit(self._nav_mode)
            else:
                dx = pos.x() - self._last_pos.x()
                dy = pos.y() - self._last_pos.y()
                self._last_pos = pos
                if dx or dy:
                    self.nav_moved.emit(dx, dy)
            event.accept()
            return True

        pres      = event.pressure()
        is_eraser = self._eraser_mode
        col_ov    = 9 if is_eraser else -1
        eff_r     = self.brush_radius * (0.5 + pres * 0.5)

        if etype == QEvent.Type.TabletPress:
            self._tablet_active = True
            if not self._painting:
                self._painting = True
                self.paint_started.emit()
            self.paint_moved.emit(float(pos.x()), float(pos.y()), eff_r, col_ov)
        elif etype == QEvent.Type.TabletMove and self._painting:
            self.paint_moved.emit(float(pos.x()), float(pos.y()), eff_r, col_ov)
        elif etype == QEvent.Type.TabletRelease:
            self._painting      = False
            self._tablet_active = False
            self.paint_ended.emit()

        event.accept()
        return True

    # ------------------------------------------------------------------
    # Mouse (used when tablet not active)
    # ------------------------------------------------------------------

    _MOUSE_NAV_BUTTONS = Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton

    def handle_mouse_press(self, event,
                           pos: QPoint | None = None) -> bool:
        if self._tablet_active and event.button() == Qt.MouseButton.LeftButton:
            return True  # suppress synthetic duplicate from tablet driver
        if event.button() == Qt.MouseButton.LeftButton:
            px = float(pos.x() if pos is not None else int(event.position().x()))
            py = float(pos.y() if pos is not None else int(event.position().y()))
            if not self._painting:
                self._painting = True
                self.paint_started.emit()
            self.paint_moved.emit(px, py, float(self.brush_radius), -1)
            return True
        if event.button() & self._MOUSE_NAV_BUTTONS:
            self._mouse_nav_btn = event.button()
            self._nav_mode      = self._nav_mode_from(event.modifiers())
            self._nav_active    = True
            self._last_pos      = pos if pos is not None else event.position().toPoint()
            self.nav_started.emit(self._nav_mode)
            return True
        return False

    def handle_mouse_move(self, event,
                          pos: QPoint | None = None) -> bool:
        if self._tablet_active and not (event.buttons() & self._MOUSE_NAV_BUTTONS):
            return True
        if self._painting and (event.buttons() & Qt.MouseButton.LeftButton):
            px = float(pos.x() if pos is not None else int(event.position().x()))
            py = float(pos.y() if pos is not None else int(event.position().y()))
            self.paint_moved.emit(px, py, float(self.brush_radius), -1)
            return True
        if self._nav_active and (event.buttons() & self._mouse_nav_btn):
            lp = pos if pos is not None else event.position().toPoint()
            dx = lp.x() - self._last_pos.x()
            dy = lp.y() - self._last_pos.y()
            self._last_pos = lp
            self.nav_moved.emit(dx, dy)
            return True
        return False

    def handle_mouse_release(self, event) -> bool:
        if self._tablet_active and event.button() == Qt.MouseButton.LeftButton:
            return True
        if event.button() == Qt.MouseButton.LeftButton and self._painting:
            self._painting = False
            self.paint_ended.emit()
            return True
        if (event.button() & self._MOUSE_NAV_BUTTONS) and self._nav_active:
            self._nav_active = False
            self.nav_ended.emit()
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nav_mode_from(mod) -> NavMode:
        if mod & Qt.KeyboardModifier.ControlModifier:
            return NavMode.ZOOM
        if mod & Qt.KeyboardModifier.ShiftModifier:
            return NavMode.PAN
        return NavMode.ROTATE

    @property
    def is_painting(self) -> bool:
        return self._painting

    @property
    def is_navigating(self) -> bool:
        return self._nav_active
