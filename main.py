"""
Entry point for Tooth Annotator.

Wayland note: Qt6 tablet support on Wayland is still maturing. If WAYLAND_DISPLAY
is set and QT_QPA_PLATFORM is not configured, we force X11 (xcb) so XPen/tablet
events are delivered correctly. Override with QT_QPA_PLATFORM=wayland if needed.

Proximity events (TabletLeaveProximity) are delivered at the application level,
not the widget level. ToothAnnotatorApp intercepts them to clear stuck input state.

notify() globally corrects mouse-event positions on Linux/X11 tablets.
Qt computes event.position() by transforming the tablet's global coordinates,
but can get the wrong widget origin after focus moves between widgets.
Recomputing from globalPosition() + mapFromGlobal() is always correct and
fixes clicks in the palette panel, menu bar, and every other widget.
"""
from __future__ import annotations

import sys
import os

# Force X11 before any Qt import when running under Wayland
if (sys.platform.startswith("linux")
        and "WAYLAND_DISPLAY" in os.environ
        and "QT_QPA_PLATFORM" not in os.environ):
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    print("[tooth_annotator] Forced QT_QPA_PLATFORM=xcb for tablet compatibility. "
          "Set QT_QPA_PLATFORM=wayland to override.", flush=True)

sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QEvent, QPointF
from PyQt6.QtGui import QTabletEvent, QMouseEvent, QPointingDevice

from app.annotator_window import AnnotatorWindow


_MOUSE_EVENT_TYPES = frozenset({
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseMove,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
})


class ToothAnnotatorApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self._viewer = None

    def set_viewer(self, viewer):
        self._viewer = viewer

    def notify(self, obj, event) -> bool:
        if event.type() in _MOUSE_EVENT_TYPES and isinstance(obj, QWidget):
            global_pt = event.globalPosition().toPoint()
            correct   = obj.mapFromGlobal(global_pt)
            if correct != event.position().toPoint():
                fixed = QMouseEvent(
                    event.type(),
                    QPointF(correct),
                    event.globalPosition(),
                    event.button(),
                    event.buttons(),
                    event.modifiers(),
                )
                return super().notify(obj, fixed)
        return super().notify(obj, event)

    def event(self, e: QEvent) -> bool:
        if self._viewer is not None:
            t = e.type()
            if t == QEvent.Type.TabletEnterProximity:
                is_eraser = (e.pointerType() == QPointingDevice.PointerType.Eraser)
                self._viewer.input_handler.set_eraser_from_proximity(is_eraser)
            elif t == QEvent.Type.TabletLeaveProximity:
                self._viewer.input_handler.set_eraser_from_proximity(False)
                self._viewer.input_handler.reset()
                self._viewer.restore_cursor()
        return super().event(e)


def main():
    # Qt6 enables HiDPI scaling automatically — no setAttribute calls needed.
    app = ToothAnnotatorApp(sys.argv)
    app.setApplicationName("Mesh Annotator")

    win = AnnotatorWindow()
    app.set_viewer(win.viewer)

    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
