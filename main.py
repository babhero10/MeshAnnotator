"""
Entry point for Tooth Annotator.

Wayland note: Qt5 tablet support is broken on Wayland. If WAYLAND_DISPLAY is set
and QT_QPA_PLATFORM is not configured, we force X11 (xcb) automatically so
XPen/tablet events are delivered correctly. Override with QT_QPA_PLATFORM=wayland
if needed.

Proximity events (TabletLeaveProximity) are delivered at the application level,
not the widget level. ToothAnnotatorApp intercepts them to clear stuck input state.
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

# Allow imports from project root
sys.path.insert(0, os.path.dirname(__file__))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QTabletEvent

from app.annotator_window import AnnotatorWindow


class ToothAnnotatorApp(QApplication):
    """Intercepts application-level tablet proximity events.

    TabletEnterProximity is the only reliable source of pointer type on XP-Pen
    Linux drivers. We use it to tell InputHandler which end of the pen is active,
    rather than trusting the per-event pointerType() which is often wrong.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self._viewer = None

    def set_viewer(self, viewer):
        self._viewer = viewer

    def event(self, e: QEvent) -> bool:
        if self._viewer is not None:
            t = e.type()
            if t == QEvent.TabletEnterProximity:
                # PyQt5 passes the real QTabletEvent subclass here
                is_eraser = getattr(e, 'pointerType', lambda: None)() == QTabletEvent.Eraser
                self._viewer.input_handler.set_eraser_from_proximity(is_eraser)
            elif t == QEvent.TabletLeaveProximity:
                self._viewer.input_handler.set_eraser_from_proximity(False)
                self._viewer.input_handler.reset()
        return super().event(e)


def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # These must be set BEFORE QApplication is created — Qt ignores them otherwise.
    # AA_EnableHighDpiScaling is critical for tablets: without it, pen coordinates
    # reported by Qt may be in physical pixels while widget sizes are in logical pixels,
    # causing misaligned brush placement on HiDPI displays.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = ToothAnnotatorApp(sys.argv)
    app.setApplicationName("Tooth Annotator")

    win = AnnotatorWindow()
    app.set_viewer(win.viewer)

    win.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
