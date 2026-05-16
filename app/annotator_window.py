"""
AnnotatorWindow — application main window.

Orchestrates ViewerWidget, AnnotationModel, Brush, FileManager.
All domain logic goes through AnnotationModel; ViewerWidget only displays.
"""
from __future__ import annotations

import os
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QFileDialog,
    QMessageBox, QSplitter, QDialog, QTextEdit, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut, QAction, QColor, QPalette

from app.viewer import ViewerWidget
from app.palette_panel import PalettePanel
from app.annotation_model import AnnotationModel
from app.file_manager import FileManager, load_config, save_config
from app.config import PALETTE_RGB, BRUSH_RADIUS_MIN, BRUSH_RADIUS_MAX, BRUSH_RADIUS_STEP
from utils.ply_io import read_ply, write_ply
from utils.color_utils import snap_to_palette, colors_are_palette_exact

# ── Shared button styles ──────────────────────────────────────────────────────
_BTN = (
    "QPushButton {"
    "  background: #252535; color: #b8b8c8; border: 1px solid #35354a;"
    "  border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
    "QPushButton:hover { background: #2e2e42; border-color: #5294e2; color: #d8d8f0; }"
    "QPushButton:pressed { background: #1e1e2e; }"
    "QPushButton:disabled { background: #1c1c26; color: #444455; border-color: #2a2a38; }"
)
_BTN_TOGGLE = (
    _BTN +
    "QPushButton:checked { background: #1e3255; border-color: #5294e2; color: #8ac0ff; }"
    "QPushButton:checked:hover { background: #243a63; }"
)
_BTN_GROUP_LEFT = _BTN.replace("border-radius: 4px", "border-radius: 4px 0 0 4px")
_BTN_GROUP_MID  = _BTN.replace("border-radius: 4px", "border-radius: 0").replace(
    "border: 1px solid", "border-top: 1px solid; border-bottom: 1px solid;"
    " border-right: 1px solid; border-left: none; border-color")
_BTN_GROUP_RIGHT = _BTN.replace("border-radius: 4px", "border-radius: 0 4px 4px 0").replace(
    "border: 1px solid", "border-top: 1px solid; border-bottom: 1px solid;"
    " border-right: 1px solid; border-left: none; border-color")

_TOPBAR_STYLE = (
    "background: #141420;"
    "border-bottom: 1px solid #252538;"
)

_WINDOW_STYLE = "background-color: #0f0f18; color: #d0d0e0;"

_MENU_STYLE = (
    "QMenuBar { background: #141420; color: #a0a0b8; font-size: 11px;"
    "  border-bottom: 1px solid #252538; }"
    "QMenuBar::item { padding: 4px 10px; }"
    "QMenuBar::item:selected { background: #252538; color: #d0d0e8; }"
    "QMenu { background: #1a1a2a; color: #c0c0d8; border: 1px solid #303048;"
    "  padding: 4px 0; }"
    "QMenu::item { padding: 5px 28px 5px 16px; }"
    "QMenu::item:selected { background: #253560; color: #e0e0f8; }"
    "QMenu::separator { height: 1px; background: #282840; margin: 3px 8px; }"
)

_STATUS_STYLE = (
    "QStatusBar { background: #141420; color: #505068; font-size: 11px;"
    "  border-top: 1px solid #252538; }"
    "QStatusBar::item { border: none; }"
)


class ShortcutHelpDialog(QDialog):
    _TEXT = """<style>
    body { color: #c0c0d8; font-family: monospace; font-size: 12px;
           background: #141420; }
    b    { color: #8ac0ff; }
    h3   { color: #5294e2; margin-bottom: 4px; margin-top: 12px;
           font-size: 11px; letter-spacing: 1px; text-transform: uppercase; }
    td   { padding: 3px 14px 3px 0; }
    </style>
    <body>
    <h3>Navigation</h3>
    <table>
      <tr><td><b>Middle-drag</b></td><td>Rotate</td></tr>
      <tr><td><b>Shift + Middle-drag</b></td><td>Pan</td></tr>
      <tr><td><b>Ctrl + Middle-drag</b></td><td>Zoom</td></tr>
      <tr><td><b>Scroll wheel</b></td><td>Zoom</td></tr>
      <tr><td><b>F</b></td><td>Frame mesh</td></tr>
      <tr><td><b>Numpad 1 / 3 / 7 / 0</b></td><td>Front / Right / Top / Reset</td></tr>
    </table>
    <h3>Annotation</h3>
    <table>
      <tr><td><b>Left-click / drag</b></td><td>Paint</td></tr>
      <tr><td><b>1 – 9, 0</b></td><td>Select color 1–10</td></tr>
      <tr><td><b>[ / ]</b></td><td>Decrease / Increase brush size</td></tr>
      <tr><td><b>W</b></td><td>Toggle wireframe</td></tr>
    </table>
    <h3>Files</h3>
    <table>
      <tr><td><b>Ctrl+S</b></td><td>Save</td></tr>
      <tr><td><b>, (comma)</b></td><td>Previous file</td></tr>
      <tr><td><b>. (period)</b></td><td>Next file</td></tr>
      <tr><td><b>Ctrl+Z</b></td><td>Undo</td></tr>
      <tr><td><b>Ctrl+Y / Ctrl+Shift+Z</b></td><td>Redo</td></tr>
    </table>
    <h3>Tablet (XP-Pen / Wacom)</h3>
    <table>
      <tr><td><b>Pen tip</b></td><td>Paint (pressure-sensitive radius)</td></tr>
      <tr><td><b>Eraser end</b></td><td>Erase (sets White color)</td></tr>
      <tr><td><b>Barrel button</b></td><td>Navigate — drag to rotate</td></tr>
      <tr><td><b>Barrel + Shift</b></td><td>Pan</td></tr>
      <tr><td><b>Barrel + Ctrl</b></td><td>Zoom</td></tr>
    </table>
    <p style="color:#404055; font-size:10px; margin-top:10px;">
      Works with both RightButton and MiddleButton barrel mappings.</p>
    </body>"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(460, 520)
        self.setStyleSheet("background: #141420;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setHtml(self._TEXT)
        txt.setStyleSheet(
            "background: #141420; border: 1px solid #252538; border-radius: 4px;")
        layout.addWidget(txt)

        close = QPushButton("Close")
        close.setStyleSheet(_BTN)
        close.setFixedWidth(80)
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)


class AnnotatorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tooth Annotator")
        self.resize(1300, 840)
        self.setStyleSheet(_WINDOW_STYLE)

        self._cfg      = load_config()
        self._file_mgr = FileManager()
        self._model    = AnnotationModel()
        self._unsaved  = False
        self._brush_radius: int = self._cfg.get("brush_radius", 15)

        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._install_shortcuts()

        self._viewer.brush_radius = self._brush_radius
        self._palette.set_brush_radius(self._brush_radius)

        input_dir = self._cfg.get("input_dir", "")
        if input_dir and os.path.isdir(input_dir):
            self._load_folder(input_dir, self._cfg.get("last_index", 0))
        else:
            self._pick_folder()

    @property
    def viewer(self) -> ViewerWidget:
        return self._viewer

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        # Main area
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #252538; width: 2px; }"
            "QSplitter::handle:hover { background: #5294e2; }"
        )

        self._viewer = ViewerWidget()
        splitter.addWidget(self._viewer)

        self._palette = PalettePanel()
        splitter.addWidget(self._palette)
        splitter.setSizes([1070, 210])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        root.addWidget(splitter, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self._status.setStyleSheet(_STATUS_STYLE)
        self.setStatusBar(self._status)

        self._tablet_label = QLabel("  Mouse")
        self._tablet_label.setStyleSheet("color: #404055; font-size: 10px;")
        self._status.addPermanentWidget(self._tablet_label)
        self._status.showMessage("Ready — open a folder to begin")

    def _build_topbar(self) -> QWidget:
        topbar = QWidget()
        topbar.setFixedHeight(44)
        topbar.setStyleSheet(_TOPBAR_STYLE)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(12, 6, 12, 6)
        tb.setSpacing(6)

        # File label (left)
        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet(
            "color: #7878a0; font-size: 11px; padding: 0 4px;")
        tb.addWidget(self._file_label)
        tb.addStretch()

        # View preset button group (center-right)
        views = [("Front", "front"), ("Right", "right"),
                 ("Top", "top"), ("↺ Reset", "reset")]
        for i, (label, view) in enumerate(views):
            btn = QPushButton(label)
            btn.setFixedWidth(54 if label != "↺ Reset" else 62)
            btn.setStyleSheet(_BTN)
            btn.clicked.connect(lambda _, v=view: self._viewer.set_view(v))
            tb.addWidget(btn)

        tb.addSpacing(8)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #252538;")
        tb.addWidget(sep)

        tb.addSpacing(8)

        # Wireframe toggle
        self._wire_btn = QPushButton("Wireframe")
        self._wire_btn.setCheckable(True)
        self._wire_btn.setStyleSheet(_BTN_TOGGLE)
        tb.addWidget(self._wire_btn)

        tb.addSpacing(8)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #252538;")
        tb.addWidget(sep2)

        tb.addSpacing(8)

        # Navigation buttons
        self._prev_btn = QPushButton("◀")
        self._next_btn = QPushButton("▶")
        for btn in (self._prev_btn, self._next_btn):
            btn.setStyleSheet(_BTN)
            btn.setFixedWidth(32)
            btn.setEnabled(False)
        tb.addWidget(self._prev_btn)
        tb.addWidget(self._next_btn)

        return topbar

    def _build_menu(self):
        mb = self.menuBar()
        mb.setStyleSheet(_MENU_STYLE)

        file_menu = mb.addMenu("File")
        self._add_action(file_menu, "Open Folder…", self._pick_folder, "Ctrl+O")
        file_menu.addSeparator()
        self._add_action(file_menu, "Save", self._save_current, "Ctrl+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "Previous", self._go_prev, ",")
        self._add_action(file_menu, "Next",     self._go_next, ".")
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", self.close)

        edit_menu = mb.addMenu("Edit")
        self._add_action(edit_menu, "Undo", self._undo, "Ctrl+Z")
        self._add_action(edit_menu, "Redo", self._redo, "Ctrl+Y")

        view_menu = mb.addMenu("View")
        self._add_action(view_menu, "Frame Mesh",       self._viewer.frame_mesh, "F")
        self._add_action(view_menu, "Toggle Wireframe", self._toggle_wireframe,  "W")
        view_menu.addSeparator()
        self._add_action(view_menu, "Front View", lambda: self._viewer.set_view("front"))
        self._add_action(view_menu, "Right View", lambda: self._viewer.set_view("right"))
        self._add_action(view_menu, "Top View",   lambda: self._viewer.set_view("top"))
        self._add_action(view_menu, "Reset View", lambda: self._viewer.set_view("reset"))

        help_menu = mb.addMenu("Help")
        self._add_action(help_menu, "Keyboard Shortcuts", self._show_shortcuts, "F1")

    def _add_action(self, menu, label: str, slot, shortcut: str = "") -> QAction:
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _connect_signals(self):
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        self._wire_btn.clicked.connect(self._viewer.toggle_wireframe)
        self._palette.color_selected.connect(self._on_palette_color_selected)
        self._palette.brush_radius_changed.connect(self._on_brush_radius_changed)
        self._palette.save_requested.connect(self._save_current)
        self._viewer.stroke_begin.connect(self._on_stroke_begin)
        self._viewer.paint_stroke.connect(self._on_paint_stroke)
        self._viewer.stroke_end.connect(self._on_stroke_end)

    def _install_shortcuts(self):
        def sc(key, fn):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

        sc("Ctrl+Shift+Z", self._redo)
        sc("[", self._brush_decrease)
        sc("]", self._brush_increase)

    def keyPressEvent(self, e):
        key = e.key()
        mod = e.modifiers()

        if mod & Qt.KeyboardModifier.KeypadModifier:
            view_map = {
                Qt.Key.Key_1: "front",
                Qt.Key.Key_3: "right",
                Qt.Key.Key_7: "top",
                Qt.Key.Key_0: "reset",
            }
            if key in view_map:
                self._viewer.set_view(view_map[key])
                return

        char = e.text()
        if char in {"1","2","3","4","5","6","7","8","9","0"} and not mod:
            idx = (int(char) - 1) if char != "0" else 9
            self._set_color(idx)
            return

        super().keyPressEvent(e)

    # ── Folder / file loading ──────────────────────────────────────────────

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open PLY Folder")
        if folder:
            self._load_folder(folder, 0)

    def _load_folder(self, folder: str, index: int = 0):
        self._file_mgr.load_folder(folder)
        if not self._file_mgr.files:
            QMessageBox.warning(self, "Empty Folder", "No PLY files found.")
            return
        out_dir = self._cfg.get("output_dir", "") or folder
        self._file_mgr.output_dir = out_dir
        self._file_mgr.set_index(index)
        self._cfg["input_dir"] = folder
        save_config(self._cfg)
        self._update_nav_buttons()
        self._load_current_file()

    def _load_current_file(self):
        path = self._file_mgr.current_file
        if not path:
            return
        try:
            verts, faces, colors = read_ply(path)
        except Exception as ex:
            QMessageBox.critical(self, "Load Error",
                                 f"Failed to load:\n{path}\n\n{ex}")
            return

        if self._cfg.get("snap_on_load", True):
            colors = snap_to_palette(colors)

        self._model.load(verts, faces, colors)
        self._unsaved = False
        self._viewer.load_mesh(verts, faces, colors)
        self._update_title()
        self._update_nav_buttons()
        self._status.showMessage(
            f"Loaded  {self._file_mgr.current_filename}  —  {len(verts):,} vertices")

    def _update_title(self):
        fn     = self._file_mgr.current_filename
        idx    = self._file_mgr.current_index + 1
        total  = self._file_mgr.count
        marker = "  ●" if self._unsaved else ""
        self._file_label.setText(
            f"<span style='color:#404060'>{idx} / {total}</span>"
            f"  <span style='color:#9090b8'>{fn}</span>"
            f"<span style='color:#e05050'>{marker}</span>")
        self.setWindowTitle(
            f"Tooth Annotator  —  {fn}{'  ●' if self._unsaved else ''}")

    def _update_nav_buttons(self):
        self._prev_btn.setEnabled(self._file_mgr.has_prev())
        self._next_btn.setEnabled(self._file_mgr.has_next())

    # ── Navigation ─────────────────────────────────────────────────────────

    def _go_next(self):
        if not self._file_mgr.has_next():
            return
        if not self._maybe_save_prompt():
            return
        self._file_mgr.current_index += 1
        self._cfg["last_index"] = self._file_mgr.current_index
        save_config(self._cfg)
        self._load_current_file()

    def _go_prev(self):
        if not self._file_mgr.has_prev():
            return
        if not self._maybe_save_prompt():
            return
        self._file_mgr.current_index -= 1
        self._cfg["last_index"] = self._file_mgr.current_index
        save_config(self._cfg)
        self._load_current_file()

    def _maybe_save_prompt(self) -> bool:
        if not self._unsaved:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes", "Save before continuing?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No  |
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Yes:
            if not self._save_current():
                return False
        return True

    # ── Painting ───────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_stroke_begin(self):
        self._model.save_snapshot()

    @pyqtSlot(float, float, float, int)
    def _on_paint_stroke(self, x: float, y: float,
                         radius: float, color_override: int):
        if not self._model.loaded:
            return
        color = (PALETTE_RGB[color_override] if color_override >= 0
                 else PALETTE_RGB[self._palette.current_index])
        xr, yr, r_buf = self._viewer.to_render_coords(x, y, radius)
        mask = self._viewer.compute_paint_mask(xr, yr, r_buf)
        if mask is None:
            return
        changed = self._model.paint_with_mask(mask, color)
        if changed:
            self._viewer.update_colors(self._model.colors)
            if not self._unsaved:
                self._unsaved = True
                self._update_title()

    @pyqtSlot()
    def _on_stroke_end(self):
        pass

    # ── Palette / brush ────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_palette_color_selected(self, idx: int):
        self._set_color(idx)

    def _set_color(self, idx: int):
        idx = idx % len(PALETTE_RGB)
        self._viewer.active_color = PALETTE_RGB[idx].copy()
        self._palette.select_color(idx)

    @pyqtSlot(int)
    def _on_brush_radius_changed(self, r: int):
        self._brush_radius        = r
        self._viewer.brush_radius = r
        self._cfg["brush_radius"] = r
        save_config(self._cfg)

    def _brush_decrease(self):
        self._set_brush_radius(max(BRUSH_RADIUS_MIN,
                                   self._brush_radius - BRUSH_RADIUS_STEP))

    def _brush_increase(self):
        self._set_brush_radius(min(BRUSH_RADIUS_MAX,
                                   self._brush_radius + BRUSH_RADIUS_STEP))

    def _set_brush_radius(self, r: int):
        self._brush_radius        = r
        self._viewer.brush_radius = r
        self._palette.set_brush_radius(r)
        self._cfg["brush_radius"] = r
        save_config(self._cfg)

    # ── Undo / Redo ────────────────────────────────────────────────────────

    def _undo(self):
        if self._model.undo():
            self._viewer.update_colors(self._model.colors)
            self._unsaved = True
            self._update_title()

    def _redo(self):
        if self._model.redo():
            self._viewer.update_colors(self._model.colors)
            self._unsaved = True
            self._update_title()

    # ── Save ───────────────────────────────────────────────────────────────

    def _save_current(self) -> bool:
        if not self._model.loaded:
            return True
        out_path = self._file_mgr.output_path(self._file_mgr.current_filename)
        try:
            write_ply(out_path, self._model.vertices,
                      self._model.faces, self._model.colors)
        except Exception as ex:
            QMessageBox.critical(self, "Save Error", str(ex))
            return False

        bad    = (~colors_are_palette_exact(self._model.colors)).sum()
        n      = len(self._model.colors)
        n_cols = len({tuple(c) for c in self._model.colors.tolist()})
        if bad:
            self._status.showMessage(
                f"Saved  {self._file_mgr.current_filename}"
                f"  —  ⚠ {bad} non-palette vertex/vertices")
        else:
            self._status.showMessage(
                f"Saved  {self._file_mgr.current_filename}"
                f"  —  {n:,} vertices · {n_cols} colors")

        self._unsaved = False
        self._update_title()
        return True

    # ── Wireframe ──────────────────────────────────────────────────────────

    def _toggle_wireframe(self):
        self._viewer.toggle_wireframe()
        self._wire_btn.setChecked(not self._wire_btn.isChecked())

    # ── Help ───────────────────────────────────────────────────────────────

    def _show_shortcuts(self):
        dlg = ShortcutHelpDialog(self)
        dlg.show()

    # ── Close ──────────────────────────────────────────────────────────────

    def closeEvent(self, e):
        if self._unsaved:
            reply = QMessageBox.question(
                self, "Unsaved Changes", "Save before quitting?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No  |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                e.ignore()
                return
            if reply == QMessageBox.StandardButton.Yes:
                if not self._save_current():
                    e.ignore()
                    return
        e.accept()
