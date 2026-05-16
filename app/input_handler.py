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

from PyQt5.QtCore import Qt, QEvent, QPoint, pyqtSignal, QObject
from PyQt5.QtGui import QTabletEvent


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
    _TABLET_BARREL = Qt.MiddleButton | Qt.RightButton

    def __init__(self, brush_radius: int = 15,
                 mouse_nav_button: Qt.MouseButton = Qt.MiddleButton,
                 parent=None):
        super().__init__(parent)
        self.brush_radius     = brush_radius
        self.mouse_nav_button = mouse_nav_button
        self._painting        = False
        self._tablet_active   = False
        self._nav_active      = False
        self._nav_mode        = NavMode.ROTATE
        self._last_pos        = QPoint()
        self._mouse_nav_btn   = Qt.MiddleButton  # which button started mouse-path nav
        # Eraser state is set from TabletEnterProximity (application-level event),
        # which reports pointer type reliably even on buggy XP-Pen Linux drivers.
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
        pos    = pos if pos is not None else event.pos()
        etype  = event.type()
        mod    = event.modifiers()
        barrel = bool(event.buttons() & self._TABLET_BARREL)

        # Nav release — MUST be checked before the barrel block.
        # At TabletRelease time, event.buttons() has already cleared the barrel bit,
        # so 'barrel' is False here.  If we only checked inside 'if barrel:', nav would
        # never end and the viewport would stay stuck in rotation/pan mode.
        if self._nav_active and etype == QEvent.TabletRelease:
            self._nav_active = False
            self.nav_ended.emit()
            event.accept()
            return True

        # When the barrel button is configured as a MOUSE button (e.g. XP-Pen → Middle Click),
        # Qt delivers the press as mousePressEvent (not TabletPress), so _nav_active is set
        # by handle_mouse_press(). Subsequent pen movements still arrive as TabletMove events
        # with no barrel bit set. We must forward those movements to navigation here.
        if self._nav_active and not barrel and etype == QEvent.TabletMove:
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            self._last_pos = pos
            if dx or dy:
                self.nav_moved.emit(dx, dy)
            event.accept()
            return True

        if barrel:
            # Start nav on TabletPress OR TabletMove with barrel held.
            # On XP-Pen the barrel button fires as TabletMove (hover), not TabletPress.
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
        is_eraser = self._detect_eraser(event)
        col_ov    = 9 if is_eraser else -1
        eff_r     = self.brush_radius * (0.5 + pres * 0.5)

        if etype == QEvent.TabletPress:
            self._tablet_active = True
            if not self._painting:
                # Guard: some XP-Pen driver versions fire mousePressEvent(Left)
                # before TabletPress.  handle_mouse_press() will have already set
                # _painting=True and emitted paint_started.  Don't emit it again or
                # the undo stack gets a duplicate snapshot for a single stroke.
                self._painting = True
                self.paint_started.emit()
            self.paint_moved.emit(float(pos.x()), float(pos.y()), eff_r, col_ov)
        elif etype == QEvent.TabletMove and self._painting:
            self.paint_moved.emit(float(pos.x()), float(pos.y()), eff_r, col_ov)
        elif etype == QEvent.TabletRelease:
            self._painting      = False
            self._tablet_active = False
            self.paint_ended.emit()

        event.accept()
        return True

    def _detect_eraser(self, event: QTabletEvent) -> bool:
        # Use proximity-derived state, not per-event pointerType().
        # XP-Pen Linux drivers often mis-report pen tip as Eraser in Move/Press events,
        # but TabletEnterProximity reliably distinguishes the two ends.
        return self._eraser_mode

    # ------------------------------------------------------------------
    # Mouse (used when tablet not active)
    # ------------------------------------------------------------------

    # XP-Pen Linux drivers may map the barrel button to either MiddleButton or
    # RightButton depending on driver settings.  When the barrel fires as a pure
    # mouse event (not a tablet event), we need to accept both buttons.
    _MOUSE_NAV_BUTTONS = Qt.MiddleButton | Qt.RightButton

    def handle_mouse_press(self, event,
                           pos: QPoint | None = None) -> bool:
        if self._tablet_active and event.button() == Qt.LeftButton:
            return True  # suppress synthetic duplicate from tablet driver
        if event.button() == Qt.LeftButton:
            px = float(pos.x() if pos is not None else event.x())
            py = float(pos.y() if pos is not None else event.y())
            if not self._painting:
                self._painting = True
                self.paint_started.emit()
            self.paint_moved.emit(px, py, float(self.brush_radius), -1)
            return True
        if event.button() & self._MOUSE_NAV_BUTTONS:
            self._mouse_nav_btn = event.button()
            self._nav_mode      = self._nav_mode_from(event.modifiers())
            self._nav_active    = True
            self._last_pos      = pos if pos is not None else event.pos()
            self.nav_started.emit(self._nav_mode)
            return True
        return False

    def handle_mouse_move(self, event,
                          pos: QPoint | None = None) -> bool:
        if self._tablet_active and not (event.buttons() & self._MOUSE_NAV_BUTTONS):
            return True
        if self._painting and (event.buttons() & Qt.LeftButton):
            px = float(pos.x() if pos is not None else event.x())
            py = float(pos.y() if pos is not None else event.y())
            self.paint_moved.emit(px, py, float(self.brush_radius), -1)
            return True
        if self._nav_active and (event.buttons() & self._mouse_nav_btn):
            lp = pos if pos is not None else event.pos()
            dx = lp.x() - self._last_pos.x()
            dy = lp.y() - self._last_pos.y()
            self._last_pos = lp
            self.nav_moved.emit(dx, dy)
            return True
        return False

    def handle_mouse_release(self, event) -> bool:
        if self._tablet_active and event.button() == Qt.LeftButton:
            return True
        if event.button() == Qt.LeftButton and self._painting:
            self._painting = False
            self.paint_ended.emit()
            return True
        # Accept any nav button release, not just the one that started nav.
        # Covers the case where press came via the tablet path and release via mouse.
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
        if mod & Qt.ControlModifier:
            return NavMode.ZOOM
        if mod & Qt.ShiftModifier:
            return NavMode.PAN
        return NavMode.ROTATE

    @property
    def is_painting(self) -> bool:
        return self._painting

    @property
    def is_navigating(self) -> bool:
        return self._nav_active
