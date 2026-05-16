"""
PalettePanel — sidebar showing color swatches, brush size slider, and save button.

Redesigned with modern Qt6 aesthetics: per-color tinted selection, hover states,
rounded swatches, brush circle preview, and a cleaner visual hierarchy.
"""
from __future__ import annotations

import math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QFrame, QApplication,
)
from PyQt6.QtCore import Qt, QEvent, QPointF, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPainter, QBrush, QPen, QFont, QFontMetrics,
    QMouseEvent, QTabletEvent, QLinearGradient, QPainterPath,
)

from app.config import (PALETTE_NAMES, PALETTE_RGB,
                        DEFAULT_BRUSH_RADIUS, BRUSH_RADIUS_MIN, BRUSH_RADIUS_MAX)

# ── shared palette ────────────────────────────────────────────────────────────
_ACCENT      = QColor("#5294e2")
_BG_HOVER    = QColor(255, 255, 255, 14)
_BORDER_IDLE = QColor(45, 45, 55)
_TEXT_DIM    = QColor(130, 130, 140)
_TEXT_BRIGHT = QColor(230, 230, 235)
_KEY_BADGE   = QColor(48, 48, 58)


class BrushSlider(QSlider):
    """QSlider with pointer cursor and drag-hand feedback."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().mouseReleaseEvent(e)


class BrushPreview(QWidget):
    """Small widget that draws a circle proportional to the current brush radius."""

    def __init__(self, radius: int, parent=None):
        super().__init__(parent)
        self._radius = radius
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_radius(self, r: int):
        self._radius = r
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        max_r  = min(cx, cy) - 2
        # Map brush range to display circle (min → 3 px, max → max_r)
        display_r = max(3, int(self._radius / BRUSH_RADIUS_MAX * max_r))
        # Soft glow ring
        glow = QColor(82, 148, 226, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(cx - display_r - 3, cy - display_r - 3,
                      (display_r + 3) * 2, (display_r + 3) * 2)
        # Main circle
        p.setPen(QPen(_ACCENT, 1.5))
        p.setBrush(QBrush(QColor(82, 148, 226, 55)))
        p.drawEllipse(cx - display_r, cy - display_r,
                      display_r * 2, display_r * 2)
        # Center dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_ACCENT))
        p.drawEllipse(cx - 2, cy - 2, 4, 4)


class ColorSwatch(QWidget):
    clicked = pyqtSignal(int)

    _font_name:  QFont | None = None
    _font_bold:  QFont | None = None
    _font_key:   QFont | None = None

    @classmethod
    def _init_fonts(cls):
        if cls._font_name is not None:
            return
        cls._font_name = QFont()
        cls._font_name.setPointSize(9)
        cls._font_bold = QFont()
        cls._font_bold.setPointSize(9)
        cls._font_bold.setWeight(QFont.Weight.DemiBold)
        cls._font_key = QFont()
        cls._font_key.setPointSize(8)

    def __init__(self, index: int, name: str, rgb: tuple,
                 key_hint: str, parent=None):
        super().__init__(parent)
        ColorSwatch._init_fonts()
        self.index    = index
        self.name     = name
        self.rgb      = rgb
        self.key_hint = key_hint
        self._selected = False
        self._hover    = False

        # precompute color variants
        self._color        = QColor(*rgb)
        self._color_light  = self._color.lighter(130)
        self._color_faint  = QColor(rgb[0], rgb[1], rgb[2], 28)
        self._brush        = QBrush(self._color)

        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(f"{name}  #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_selected(self, val: bool):
        if self._selected != val:
            self._selected = val
            self.update()

    def enterEvent(self, _event):
        self._hover = True
        self.update()

    def leaveEvent(self, _event):
        self._hover = False
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r    = QRectF(1, 1, w - 2, h - 2)

        # ── Background ────────────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        if self._selected:
            p.setBrush(QBrush(self._color_faint))
            p.drawRoundedRect(r, 5, 5)
        elif self._hover:
            p.setBrush(QBrush(_BG_HOVER))
            p.drawRoundedRect(r, 5, 5)

        # ── Color box ─────────────────────────────────────────────────────
        box = QRectF(8, 7, 26, h - 14)
        p.setBrush(self._brush)
        p.setPen(QPen(self._color_light if self._selected else _BORDER_IDLE, 1))
        p.drawRoundedRect(box, 4, 4)

        # ── Label ─────────────────────────────────────────────────────────
        p.setFont(self._font_bold if self._selected else self._font_name)
        p.setPen(QPen(_TEXT_BRIGHT if self._selected else _TEXT_DIM))
        label_r = QRectF(42, 0, w - 70, h)
        p.drawText(label_r,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.name)

        # ── Key badge ─────────────────────────────────────────────────────
        badge_w, badge_h = 20, 16
        badge_x = w - badge_w - 6
        badge_y = (h - badge_h) // 2
        badge_r = QRectF(badge_x, badge_y, badge_w, badge_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_KEY_BADGE))
        p.drawRoundedRect(badge_r, 3, 3)
        p.setFont(self._font_key)
        p.setPen(QPen(QColor(160, 160, 175)))
        p.drawText(badge_r, Qt.AlignmentFlag.AlignCenter, self.key_hint)

        # ── Selection border ──────────────────────────────────────────────
        if self._selected:
            p.setPen(QPen(self._color_light, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 5, 5)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)


class _SectionLabel(QLabel):
    """Compact uppercase section header."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "color: #8080a0; font-weight: bold; font-size: 9px;"
            " letter-spacing: 2px; padding: 0px;")


class _Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setStyleSheet("color: #2a2a38;")
        self.setFixedHeight(1)


class PalettePanel(QWidget):
    color_selected       = pyqtSignal(int)
    brush_radius_changed = pyqtSignal(int)
    save_requested       = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        self._swatches:      list[ColorSwatch] = []
        self._current_index: int = 0
        self._tablet_child:  QWidget | None = None
        self._build_ui()

    @property
    def current_index(self) -> int:
        return self._current_index

    def _build_ui(self):
        self.setStyleSheet("background: #181820;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 10)
        layout.setSpacing(3)

        # ── Colors section ────────────────────────────────────────────────
        layout.addWidget(_SectionLabel("COLORS"))
        layout.addSpacing(4)

        key_hints = [str(i) for i in range(1, 10)] + ["0"]
        for i, (name, key) in enumerate(zip(PALETTE_NAMES, key_hints)):
            rgb    = tuple(int(x) for x in PALETTE_RGB[i])
            swatch = ColorSwatch(i, name, rgb, key)
            swatch.clicked.connect(self._on_swatch_clicked)
            layout.addWidget(swatch)
            self._swatches.append(swatch)

        layout.addSpacing(10)
        layout.addWidget(_Divider())
        layout.addSpacing(6)

        # ── Brush section ─────────────────────────────────────────────────
        layout.addWidget(_SectionLabel("BRUSH SIZE"))
        layout.addSpacing(4)

        self._brush_preview = BrushPreview(DEFAULT_BRUSH_RADIUS)
        layout.addWidget(self._brush_preview)

        self._brush_slider = BrushSlider(Qt.Orientation.Horizontal)
        self._brush_slider.setMinimum(BRUSH_RADIUS_MIN)
        self._brush_slider.setMaximum(BRUSH_RADIUS_MAX)
        self._brush_slider.setValue(DEFAULT_BRUSH_RADIUS)
        self._brush_slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            "  background: #2a2a38; height: 4px; border-radius: 2px; }"
            "QSlider::handle:horizontal {"
            "  background: #5294e2; width: 14px; height: 14px;"
            "  margin: -5px 0; border-radius: 7px; border: 2px solid #6aaaf8; }"
            "QSlider::sub-page:horizontal {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "    stop:0 #2a5a9a, stop:1 #5294e2);"
            "  border-radius: 2px; }"
        )
        self._brush_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._brush_slider)

        self._brush_value_label = QLabel(f"{DEFAULT_BRUSH_RADIUS} px")
        self._brush_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._brush_value_label.setStyleSheet(
            "color: #5294e2; font-size: 10px; font-weight: bold;")
        layout.addWidget(self._brush_value_label)

        layout.addStretch()
        layout.addWidget(_Divider())
        layout.addSpacing(8)

        # ── Save button ───────────────────────────────────────────────────
        save_btn = QPushButton("  Save")
        save_btn.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "    stop:0 #2e7a4a, stop:1 #1e5a36);"
            "  color: #c8f0d8; border: 1px solid #3a9a5a;"
            "  border-radius: 5px; padding: 8px 0; font-size: 12px;"
            "  font-weight: bold; letter-spacing: 1px; }"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "    stop:0 #3a9a5a, stop:1 #2a7044); }"
            "QPushButton:pressed {"
            "  background: #1a4a2e; border-color: #2a7a44; }"
        )
        save_btn.clicked.connect(self.save_requested)
        layout.addWidget(save_btn)

        hint = QLabel("Ctrl+S")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #707088; font-size: 9px;")
        layout.addWidget(hint)

        self.select_color(0)

    def _on_slider_changed(self, v: int):
        self._brush_preview.set_radius(v)
        self._brush_value_label.setText(f"{v} px")
        self.brush_radius_changed.emit(v)

    def tabletEvent(self, event: QTabletEvent):
        local = self.mapFromGlobal(event.globalPosition().toPoint())
        t     = event.type()

        if t == QEvent.Type.TabletPress:
            self._tablet_child = self.childAt(local)
            mtype = QEvent.Type.MouseButtonPress
            btn   = Qt.MouseButton.LeftButton
            btns  = Qt.MouseButton.LeftButton
        elif t == QEvent.Type.TabletMove:
            mtype = QEvent.Type.MouseMove
            btn   = Qt.MouseButton.NoButton
            # Only report button held if a press was already tracked; otherwise
            # hover pressure leaks into the slider and makes it jump mid-stroke.
            btns  = (Qt.MouseButton.LeftButton
                     if self._tablet_child is not None and event.pressure() > 0.05
                     else Qt.MouseButton.NoButton)
        elif t == QEvent.Type.TabletRelease:
            mtype = QEvent.Type.MouseButtonRelease
            btn   = Qt.MouseButton.LeftButton
            btns  = Qt.MouseButton.NoButton
            child = self._tablet_child
            self._tablet_child = None
            target = child if child is not None else self
            child_local = target.mapFrom(self, local)
            QApplication.sendEvent(target,
                QMouseEvent(mtype, QPointF(child_local), event.globalPosition(),
                            btn, btns, event.modifiers()))
            event.accept()
            return
        else:
            event.ignore()
            return

        target = (self._tablet_child if self._tablet_child is not None
                  else self.childAt(local))
        if target is None:
            target = self
        child_local = target.mapFrom(self, local)
        QApplication.sendEvent(target,
            QMouseEvent(mtype, QPointF(child_local), event.globalPosition(),
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
        self._brush_preview.set_radius(radius)
        self._brush_value_label.setText(f"{radius} px")
