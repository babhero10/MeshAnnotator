"""
PalettePanel — sidebar showing palette selector, color swatches, brush controls,
and save button.

Supports multiple named palettes: create, switch, and edit via the selector row
at the top. Swatches are rebuilt dynamically when the active palette changes.
Colors beyond slot 10 have no numpad shortcut (badge shows "–").
"""
from __future__ import annotations

import app.config as _cfg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QFrame, QApplication, QComboBox,
    QDialog, QDialogButtonBox, QScrollArea, QLineEdit,
    QColorDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QEvent, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPainter, QBrush, QPen, QFont,
    QMouseEvent, QTabletEvent, QLinearGradient, QPainterPath,
)

from app.config import DEFAULT_BRUSH_RADIUS, BRUSH_RADIUS_MIN, BRUSH_RADIUS_MAX

# ── shared colors ─────────────────────────────────────────────────────────────
_ACCENT      = QColor("#5294e2")
_BG_HOVER    = QColor(255, 255, 255, 14)
_BORDER_IDLE = QColor(45, 45, 55)
_TEXT_DIM    = QColor(130, 130, 140)
_TEXT_BRIGHT = QColor(230, 230, 235)
_KEY_BADGE   = QColor(48, 48, 58)

# ── editor dialog style ───────────────────────────────────────────────────────
_DLG_STYLE = (
    "QDialog { background: #1e1e2e; color: #d0d0e0; }"
    "QLabel  { color: #d0d0e0; }"
    "QLineEdit { background: #2a2a3a; color: #d0d0e0; "
    "  border: 1px solid #404058; border-radius: 4px; padding: 2px 6px; }"
    "QScrollArea { border: none; background: #1e1e2e; }"
    "QScrollBar:vertical { background: #1e1e2e; width: 6px; }"
    "QScrollBar::handle:vertical { background: #404058; border-radius: 3px; }"
    "QPushButton { background: #2a2a3a; color: #d0d0e0; "
    "  border: 1px solid #404058; border-radius: 4px; padding: 4px 10px; }"
    "QPushButton:hover { background: #3a3a50; }"
    "QDialogButtonBox QPushButton { min-width: 72px; padding: 5px 12px; }"
)


# ── Palette editor components ──────────────────────────────────────────────────

class _ColorRow(QWidget):
    """One editable color slot in the palette editor."""
    removed = pyqtSignal(object)

    def __init__(self, name: str, rgb: list, parent=None):
        super().__init__(parent)
        self._rgb = list(rgb)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(6)

        self._swatch = QPushButton()
        self._swatch.setFixedSize(32, 32)
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.setToolTip("Click to change color")
        self._refresh_swatch()
        self._swatch.clicked.connect(self._pick_color)

        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("Color name")

        rm = QPushButton("✕")
        rm.setFixedSize(24, 24)
        rm.setToolTip("Remove this color")
        rm.setStyleSheet(
            "QPushButton { background: #3a2020; color: #e07070; "
            "  border: 1px solid #503030; border-radius: 4px; font-size: 10px; }"
            "QPushButton:hover { background: #5a2828; }")
        rm.clicked.connect(lambda: self.removed.emit(self))

        row.addWidget(self._swatch)
        row.addWidget(self._name_edit, stretch=1)
        row.addWidget(rm)

    def _refresh_swatch(self):
        r, g, b = self._rgb
        self._swatch.setStyleSheet(
            f"QPushButton {{ background: rgb({r},{g},{b}); "
            f"border: 1px solid #505060; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 2px solid #5294e2; }}")

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(*self._rgb), self, "Choose Color")
        if c.isValid():
            self._rgb = [c.red(), c.green(), c.blue()]
            self._refresh_swatch()

    def data(self) -> dict:
        return {"name": self._name_edit.text().strip() or "Color",
                "rgb": list(self._rgb)}


class PaletteEditorDialog(QDialog):
    """Modal dialog for editing a palette's name and color slots."""

    def __init__(self, palette_name: str, colors: list,
                 used_names: set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Palette")
        self.setMinimumWidth(380)
        self.setStyleSheet(_DLG_STYLE)
        self._used_names = set(used_names)
        self._rows: list[_ColorRow] = []

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Name field ──
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(palette_name)
        self._name_edit.setMinimumWidth(200)
        name_row.addWidget(self._name_edit, stretch=1)
        root.addLayout(name_row)

        # ── Scrollable color list ──
        self._inner = QWidget()
        self._inner.setStyleSheet("background: #1e1e2e;")
        self._rows_layout = QVBoxLayout(self._inner)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)

        scroll = QScrollArea()
        scroll.setWidget(self._inner)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(220)
        scroll.setMaximumHeight(420)
        root.addWidget(scroll)

        for c in colors:
            self._add_row(c.get("name", ""), c.get("rgb", [128, 128, 128]))

        # ── Add color ──
        add_btn = QPushButton("＋  Add Color")
        add_btn.clicked.connect(lambda: self._add_row("New Color", [128, 128, 128]))
        root.addWidget(add_btn)

        # ── OK / Cancel ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _add_row(self, name: str, rgb: list):
        row = _ColorRow(name, rgb, self._inner)
        row.removed.connect(self._remove_row)
        self._rows_layout.addWidget(row)
        self._rows.append(row)

    def _remove_row(self, row: _ColorRow):
        if len(self._rows) <= 1:
            QMessageBox.information(self, "Cannot Remove",
                                    "A palette must have at least one color.")
            return
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Palette name cannot be empty.")
            return
        if name in self._used_names:
            QMessageBox.warning(self, "Duplicate Name",
                                f'A palette named "{name}" already exists.')
            return
        self.accept()

    def result_data(self) -> tuple[str, list]:
        return (self._name_edit.text().strip(),
                [r.data() for r in self._rows])


# ── Palette panel components ───────────────────────────────────────────────────

class BrushSlider(QSlider):
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
        display_r = max(3, int(self._radius / BRUSH_RADIUS_MAX * max_r))
        glow = QColor(82, 148, 226, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(cx - display_r - 3, cy - display_r - 3,
                      (display_r + 3) * 2, (display_r + 3) * 2)
        p.setPen(QPen(_ACCENT, 1.5))
        p.setBrush(QBrush(QColor(82, 148, 226, 55)))
        p.drawEllipse(cx - display_r, cy - display_r,
                      display_r * 2, display_r * 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_ACCENT))
        p.drawEllipse(cx - 2, cy - 2, 4, 4)


class ColorSwatch(QWidget):
    clicked = pyqtSignal(int)

    _font_name: QFont | None = None
    _font_bold: QFont | None = None
    _font_key:  QFont | None = None

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

        self._color       = QColor(*rgb)
        self._color_light = self._color.lighter(130)
        self._color_faint = QColor(rgb[0], rgb[1], rgb[2], 28)
        self._brush       = QBrush(self._color)

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

        p.setPen(Qt.PenStyle.NoPen)
        if self._selected:
            p.setBrush(QBrush(self._color_faint))
            p.drawRoundedRect(r, 5, 5)
        elif self._hover:
            p.setBrush(QBrush(_BG_HOVER))
            p.drawRoundedRect(r, 5, 5)

        box = QRectF(8, 7, 26, h - 14)
        p.setBrush(self._brush)
        p.setPen(QPen(self._color_light if self._selected else _BORDER_IDLE, 1))
        p.drawRoundedRect(box, 4, 4)

        p.setFont(self._font_bold if self._selected else self._font_name)
        p.setPen(QPen(_TEXT_BRIGHT if self._selected else _TEXT_DIM))
        label_r = QRectF(42, 0, w - 70, h)
        p.drawText(label_r,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.name)

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

        if self._selected:
            p.setPen(QPen(self._color_light, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 5, 5)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)


class _SectionLabel(QLabel):
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


_COMBO_STYLE = (
    "QComboBox { background: #2a2a3a; color: #d0d0e0; "
    "  border: 1px solid #404058; border-radius: 4px; "
    "  padding: 1px 6px; font-size: 11px; }"
    "QComboBox:hover { border-color: #5294e2; }"
    "QComboBox::drop-down { border: none; width: 18px; }"
    "QComboBox::down-arrow { width: 8px; height: 8px; }"
    "QComboBox QAbstractItemView { background: #2a2a3a; color: #d0d0e0; "
    "  border: 1px solid #404058; selection-background-color: #3a4a7a; }"
)

_SEL_BTN = (
    "QPushButton { background: #2a2a3a; color: #a0a0d0; "
    "  border: 1px solid #404058; border-radius: 4px; font-size: 13px; }"
    "QPushButton:hover { background: #3a3a50; border-color: #5294e2; }"
)

_NEW_BTN = (
    "QPushButton { background: #253525; color: #80c880; "
    "  border: 1px solid #3a5a3a; border-radius: 4px; "
    "  font-size: 15px; font-weight: bold; }"
    "QPushButton:hover { background: #3a5a3a; }"
)


class PalettePanel(QWidget):
    color_selected           = pyqtSignal(int)
    brush_radius_changed     = pyqtSignal(int)
    save_requested           = pyqtSignal()
    palette_switch_requested = pyqtSignal(str)
    palette_new_requested    = pyqtSignal()
    palette_edit_requested   = pyqtSignal()

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

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet("background: #181820;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 10)
        layout.setSpacing(3)

        # ── Palette selector ──────────────────────────────────────────────
        layout.addWidget(_SectionLabel("PALETTE"))
        layout.addSpacing(2)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(4)
        sel_row.setContentsMargins(0, 0, 0, 0)

        self._palette_combo = QComboBox()
        self._palette_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._palette_combo.setFixedHeight(26)
        self._palette_combo.setStyleSheet(_COMBO_STYLE)
        self._palette_combo.currentTextChanged.connect(self._on_combo_changed)
        sel_row.addWidget(self._palette_combo, stretch=1)

        new_btn = QPushButton("+")
        new_btn.setFixedSize(26, 26)
        new_btn.setToolTip("New palette (copies current)")
        new_btn.setStyleSheet(_NEW_BTN)
        new_btn.clicked.connect(self.palette_new_requested)
        sel_row.addWidget(new_btn)

        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(26, 26)
        edit_btn.setToolTip("Edit current palette")
        edit_btn.setStyleSheet(_SEL_BTN)
        edit_btn.clicked.connect(self.palette_edit_requested)
        sel_row.addWidget(edit_btn)

        layout.addLayout(sel_row)
        layout.addSpacing(4)
        layout.addWidget(_Divider())
        layout.addSpacing(4)

        # ── Colors section ────────────────────────────────────────────────
        layout.addWidget(_SectionLabel("COLORS"))
        layout.addSpacing(4)

        self._swatches_widget = QWidget()
        self._swatches_widget.setStyleSheet("background: transparent;")
        self._swatches_layout = QVBoxLayout(self._swatches_widget)
        self._swatches_layout.setContentsMargins(0, 0, 0, 0)
        self._swatches_layout.setSpacing(0)

        swatch_scroll = QScrollArea()
        swatch_scroll.setWidget(self._swatches_widget)
        swatch_scroll.setWidgetResizable(True)
        swatch_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        swatch_scroll.setMinimumHeight(80)
        swatch_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { background: #181820; width: 6px; }"
            "QScrollBar::handle:vertical { background: #404058; border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        layout.addWidget(swatch_scroll, stretch=1)

        self.rebuild_swatches()

        layout.addSpacing(6)
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
            "QPushButton:pressed { background: #1a4a2e; border-color: #2a7a44; }"
        )
        save_btn.clicked.connect(self.save_requested)
        layout.addWidget(save_btn)

        hint = QLabel("Ctrl+S")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #707088; font-size: 9px;")
        layout.addWidget(hint)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_palette_names(self, names: list[str], active: str):
        """Populate the palette combobox without triggering a switch signal."""
        self._palette_combo.blockSignals(True)
        self._palette_combo.clear()
        for name in names:
            self._palette_combo.addItem(name)
        idx = next((i for i, n in enumerate(names) if n == active), 0)
        self._palette_combo.setCurrentIndex(idx)
        self._palette_combo.blockSignals(False)

    def rebuild_swatches(self):
        """Clear and repopulate color swatches from the module-level palette."""
        while self._swatches_layout.count():
            item = self._swatches_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._swatches.clear()

        names   = _cfg.PALETTE_NAMES
        rgb_arr = _cfg.PALETTE_RGB
        for i in range(len(names)):
            if i < 9:
                key = str(i + 1)
            elif i == 9:
                key = "0"
            else:
                key = "–"
            rgb    = tuple(int(x) for x in rgb_arr[i])
            swatch = ColorSwatch(i, names[i], rgb, key)
            swatch.clicked.connect(self._on_swatch_clicked)
            self._swatches_layout.addWidget(swatch)
            self._swatches.append(swatch)

        idx = min(self._current_index, max(0, len(self._swatches) - 1))
        self._current_index = idx
        for i, sw in enumerate(self._swatches):
            sw.set_selected(i == idx)

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

    # ── Internal slots ─────────────────────────────────────────────────────────

    def _on_combo_changed(self, name: str):
        if name:
            self.palette_switch_requested.emit(name)

    def _on_swatch_clicked(self, index: int):
        self.select_color(index)
        self.color_selected.emit(index)

    def _on_slider_changed(self, v: int):
        self._brush_preview.set_radius(v)
        self._brush_value_label.setText(f"{v} px")
        self.brush_radius_changed.emit(v)

    # ── Tablet forwarding ──────────────────────────────────────────────────────

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
