"""
PalettePanel — sidebar showing color swatches, brush size slider, and save button.

ColorSwatch caches QFont and QPen objects to avoid per-frame allocations.
Exposes current_index so AnnotatorWindow can read the active color without
maintaining a separate Brush object.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QFrame, QApplication,
)
from PyQt5.QtCore import Qt, QEvent, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen, QFont, QMouseEvent, QTabletEvent


class BrushSlider(QSlider):
    """QSlider with a pointing-hand cursor and a closed-hand cursor while dragging."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.PointingHandCursor)
        super().mouseReleaseEvent(e)

from app.config import (PALETTE_NAMES, PALETTE_RGB,
                        DEFAULT_BRUSH_RADIUS, BRUSH_RADIUS_MIN, BRUSH_RADIUS_MAX)


class ColorSwatch(QWidget):
    clicked = pyqtSignal(int)

    # Cached shared resources — created once, reused in every paintEvent
    _font:     QFont | None = None
    _pen_sel:  QPen  | None = None
    _pen_norm: QPen  | None = None
    _pen_text: QPen  | None = None
    _pen_hint: QPen  | None = None
    _pen_gold: QPen  | None = None

    @classmethod
    def _init_shared(cls):
        if cls._font is not None:
            return
        cls._font     = QFont(); cls._font.setPointSize(9)
        cls._pen_sel  = QPen(QColor(255, 255, 255), 2)
        cls._pen_norm = QPen(QColor(80, 80, 80), 1)
        cls._pen_text = QPen(QColor(220, 220, 220))
        cls._pen_hint = QPen(QColor(140, 140, 140))
        cls._pen_gold = QPen(QColor(255, 200, 0), 2)

    def __init__(self, index: int, name: str, rgb: tuple,
                 key_hint: str, parent=None):
        super().__init__(parent)
        ColorSwatch._init_shared()
        self.index    = index
        self.name     = name
        self.rgb      = rgb
        self.key_hint = key_hint
        self._selected = False
        self._brush    = QBrush(QColor(*rgb))
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(f"{name}  #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
        self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, val: bool):
        if self._selected != val:
            self._selected = val
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r   = self.rect().adjusted(2, 2, -2, -2)
        box = r.adjusted(0, 0, -r.width() + 28, 0)

        p.setBrush(self._brush)
        p.setPen(self._pen_sel if self._selected else self._pen_norm)
        p.drawRect(box)

        p.setFont(self._font)
        p.setPen(self._pen_text)
        p.drawText(r.adjusted(34, 0, -28, 0),
                   Qt.AlignVCenter | Qt.AlignLeft, self.name)

        p.setPen(self._pen_hint)
        p.drawText(r.adjusted(r.width() - 24, 0, 0, 0),
                   Qt.AlignVCenter | Qt.AlignRight, f"[{self.key_hint}]")

        if self._selected:
            p.setPen(self._pen_gold)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.index)


class PalettePanel(QWidget):
    color_selected       = pyqtSignal(int)
    brush_radius_changed = pyqtSignal(int)
    save_requested       = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self._swatches:      list[ColorSwatch] = []
        self._current_index: int = 0
        self._tablet_child:  QWidget | None = None  # child grabbed on TabletPress
        self._build_ui()

    @property
    def current_index(self) -> int:
        return self._current_index

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(2)

        title = QLabel("PALETTE")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #888; font-weight: bold; font-size: 10px; letter-spacing: 1px;")
        layout.addWidget(title)

        layout.addSpacing(4)

        key_hints = [str(i) for i in range(1, 10)] + ["0"]
        for i, (name, key) in enumerate(zip(PALETTE_NAMES, key_hints)):
            rgb    = tuple(int(x) for x in PALETTE_RGB[i])
            swatch = ColorSwatch(i, name, rgb, key)
            swatch.clicked.connect(self._on_swatch_clicked)
            layout.addWidget(swatch)
            self._swatches.append(swatch)

        layout.addSpacing(12)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #3a3a3a;")
        layout.addWidget(sep)

        layout.addSpacing(4)

        brush_label = QLabel("Brush Size")
        brush_label.setStyleSheet("color: #888; font-size: 10px;")
        brush_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(brush_label)

        self._brush_slider = BrushSlider(Qt.Horizontal)
        self._brush_slider.setMinimum(BRUSH_RADIUS_MIN)
        self._brush_slider.setMaximum(BRUSH_RADIUS_MAX)
        self._brush_slider.setValue(DEFAULT_BRUSH_RADIUS)
        self._brush_slider.setStyleSheet(
            "QSlider::groove:horizontal { background: #3a3a3a; height: 4px; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: #6090c0; width: 14px; height: 14px;"
            " margin: -5px 0; border-radius: 7px; }"
            "QSlider::sub-page:horizontal { background: #4a7aaa; border-radius: 2px; }"
        )
        self._brush_slider.valueChanged.connect(self.brush_radius_changed)
        layout.addWidget(self._brush_slider)

        self._brush_value_label = QLabel(f"{DEFAULT_BRUSH_RADIUS} px")
        self._brush_value_label.setAlignment(Qt.AlignCenter)
        self._brush_value_label.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(self._brush_value_label)
        self._brush_slider.valueChanged.connect(
            lambda v: self._brush_value_label.setText(f"{v} px"))

        layout.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #3a3a3a;")
        layout.addWidget(sep2)

        layout.addSpacing(6)

        save_btn = QPushButton("Save  Ctrl+S")
        save_btn.setStyleSheet(
            "QPushButton { background: #2a6a3a; color: #ddd; border: 1px solid #3a8a4a;"
            " border-radius: 4px; padding: 7px; font-size: 12px; }"
            "QPushButton:hover { background: #3a7a4a; }"
            "QPushButton:pressed { background: #1e5a2e; }"
        )
        save_btn.clicked.connect(self.save_requested)
        layout.addWidget(save_btn)

        self.select_color(0)

    def tabletEvent(self, event: QTabletEvent):
        """Convert tablet events to correctly-positioned mouse events.

        Child widgets (ColorSwatch, QSlider, QPushButton) don't override
        tabletEvent, so Qt propagates it here.  We recompute the local
        position from globalPos() — which is always the correct screen
        coordinate — rather than trusting event.pos(), which carries the
        same wrong widget-offset bug as on the viewer side.

        _tablet_child tracks which child was pressed so that drag moves
        stay routed to the same widget (mirrors mouse-grab behaviour).
        """
        local = self.mapFromGlobal(event.globalPos())
        t     = event.type()

        if t == QEvent.TabletPress:
            self._tablet_child = self.childAt(local)
            mtype, btn, btns = QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton
        elif t == QEvent.TabletMove:
            mtype = QEvent.MouseMove
            btn   = Qt.NoButton
            btns  = Qt.LeftButton if event.pressure() > 0.05 else Qt.NoButton
        elif t == QEvent.TabletRelease:
            mtype, btn, btns = QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton
            child = self._tablet_child
            self._tablet_child = None
            target = child if child is not None else self
            child_local = target.mapFrom(self, local)
            QApplication.sendEvent(target,
                QMouseEvent(mtype, QPointF(child_local), event.globalPos(),
                            btn, btns, event.modifiers()))
            event.accept()
            return
        else:
            event.ignore()
            return

        # For Press and Move: use grabbed child (or hit-test for Press)
        target = (self._tablet_child if self._tablet_child is not None
                  else self.childAt(local))
        if target is None:
            target = self
        child_local = target.mapFrom(self, local)
        QApplication.sendEvent(target,
            QMouseEvent(mtype, QPointF(child_local), event.globalPos(),
                        btn, btns, event.modifiers()))
        event.accept()

    def _on_swatch_clicked(self, index: int):
        self.select_color(index)
        self.color_selected.emit(index)

    def select_color(self, index: int):
        self._current_index = index
        for i, sw in enumerate(self._swatches):
            sw.set_selected(i == index)

    def set_brush_radius(self, radius: int):
        self._brush_slider.blockSignals(True)
        self._brush_slider.setValue(radius)
        self._brush_slider.blockSignals(False)
        self._brush_value_label.setText(f"{radius} px")
