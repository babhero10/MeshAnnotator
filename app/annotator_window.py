"""
AnnotatorWindow — application main window.

Orchestrates ViewerWidget, AnnotationModel, Brush, FileManager.
All domain logic goes through AnnotationModel; ViewerWidget only displays.

Fixes applied:
- Key 1/3/7/0 shortcut conflict resolved: numpad uses Qt.KeypadModifier (no scan codes)
- Color key 1 now works correctly (was always intercepted by view shortcut before)
- _save_current() returns bool; navigation aborts if save fails
- set_view() public API used instead of accessing private _camera
- Menu bar added for discoverability
- F1 shows keyboard shortcut help
"""
from __future__ import annotations

import os
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QFileDialog,
    QMessageBox, QShortcut, QSplitter, QAction, QMenu,
    QDialog, QTextEdit,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QKeySequence

from app.viewer import ViewerWidget
from app.palette_panel import PalettePanel
from app.annotation_model import AnnotationModel
from app.file_manager import FileManager, load_config, save_config
from app.config import PALETTE_RGB, BRUSH_RADIUS_MIN, BRUSH_RADIUS_MAX, BRUSH_RADIUS_STEP
from utils.ply_io import read_ply, write_ply
from utils.color_utils import snap_to_palette, colors_are_palette_exact


_BTN_STYLE = (
    "QPushButton { background: #3a3a3a; color: #ccc; border: 1px solid #555;"
    " border-radius: 3px; padding: 3px 10px; }"
    "QPushButton:hover { background: #4a4a4a; }"
    "QPushButton:pressed { background: #555; }"
)


class ShortcutHelpDialog(QDialog):
    _TEXT = """<style>
    body { color: #ccc; font-family: monospace; font-size: 12px; }
    b    { color: #fff; }
    h3   { color: #aaa; margin-bottom: 4px; }
    td   { padding: 2px 12px 2px 0; }
    </style>
    <body>
    <h3>Navigation</h3>
    <table>
      <tr><td><b>Middle-drag</b></td><td>Rotate</td></tr>
      <tr><td><b>Shift + Middle-drag</b></td><td>Pan</td></tr>
      <tr><td><b>Ctrl + Middle-drag</b></td><td>Zoom</td></tr>
      <tr><td><b>Scroll wheel</b></td><td>Zoom</td></tr>
      <tr><td><b>F</b></td><td>Frame mesh</td></tr>
      <tr><td><b>Numpad 1 / 3 / 7 / 0</b></td><td>Front / Right / Top / Reset view</td></tr>
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
    <p style="color:#666; font-size:10px;">Works with both RightButton and MiddleButton barrel mappings (XP-Pen default is Right).</p>
    </body>"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setModal(False)
        self.resize(440, 500)
        self.setStyleSheet("background: #1e1e1e;")
        layout = QVBoxLayout(self)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setHtml(self._TEXT)
        txt.setStyleSheet("background: #1e1e1e; border: none;")
        layout.addWidget(txt)
        close = QPushButton("Close")
        close.setStyleSheet(_BTN_STYLE)
        close.clicked.connect(self.close)
        layout.addWidget(close)


class AnnotatorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tooth Annotator")
        self.resize(1280, 820)
        self.setStyleSheet("background-color: #1e1e1e; color: #ddd;")

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

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        topbar = QWidget()
        topbar.setFixedHeight(40)
        topbar.setStyleSheet("background: #252525; border-bottom: 1px solid #383838;")
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(12, 4, 12, 4)
        tb.setSpacing(6)

        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet("color: #bbb; font-size: 12px;")
        tb.addWidget(self._file_label)
        tb.addStretch()

        # View preset buttons
        for label, view in [("Front", "front"), ("Right", "right"),
                             ("Top", "top"), ("⟳ Reset", "reset")]:
            btn = QPushButton(label)
            btn.setStyleSheet(_BTN_STYLE)
            btn.setFixedWidth(54 if label != "⟳ Reset" else 62)
            btn.clicked.connect(lambda _, v=view: self._viewer.set_view(v))
            tb.addWidget(btn)

        tb.addSpacing(8)

        self._wire_btn = QPushButton("Wireframe")
        self._wire_btn.setCheckable(True)
        self._wire_btn.setStyleSheet(
            "QPushButton { background: #3a3a3a; color: #ccc; border: 1px solid #555;"
            " border-radius: 3px; padding: 3px 10px; }"
            "QPushButton:hover { background: #4a4a4a; }"
            "QPushButton:checked { background: #4a6080; border-color: #6090b0; }"
        )
        # Connection deferred to _connect_signals() where _viewer exists
        tb.addWidget(self._wire_btn)

        tb.addSpacing(8)
        self._prev_btn = QPushButton("◀")
        self._next_btn = QPushButton("▶")
        _BTN_DIS = (_BTN_STYLE +
                    "QPushButton:disabled { background: #2a2a2a; color: #555;"
                    " border-color: #333; }")
        for btn in (self._prev_btn, self._next_btn):
            btn.setStyleSheet(_BTN_DIS)
            btn.setFixedWidth(32)
            btn.setEnabled(False)   # disabled until a folder is loaded
        tb.addWidget(self._prev_btn)
        tb.addWidget(self._next_btn)
        root.addWidget(topbar)

        # Main area
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #383838; width: 2px; }")

        self._viewer = ViewerWidget()
        splitter.addWidget(self._viewer)

        self._palette = PalettePanel()
        splitter.addWidget(self._palette)
        splitter.setSizes([1060, 200])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        root.addWidget(splitter, stretch=1)

        # Status bar
        self._status = QStatusBar()
        self._status.setStyleSheet(
            "QStatusBar { background: #252525; color: #777; font-size: 11px; }"
            "QStatusBar::item { border: none; }"
        )
        self.setStatusBar(self._status)
        self._tablet_label = QLabel("  Mouse")
        self._tablet_label.setStyleSheet("color: #555; font-size: 10px;")
        self._status.addPermanentWidget(self._tablet_label)
        self._status.showMessage("Ready — open a folder to begin")

    def _build_menu(self):
        mb = self.menuBar()
        mb.setStyleSheet(
            "QMenuBar { background: #252525; color: #ccc; }"
            "QMenuBar::item:selected { background: #3a3a3a; }"
            "QMenu { background: #2a2a2a; color: #ccc; border: 1px solid #444; }"
            "QMenu::item:selected { background: #3a5a7a; }"
        )

        # File
        file_menu = mb.addMenu("File")
        self._add_action(file_menu, "Open Folder…", self._pick_folder, "Ctrl+O")
        file_menu.addSeparator()
        self._add_action(file_menu, "Save", self._save_current, "Ctrl+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "Previous", self._go_prev, ",")
        self._add_action(file_menu, "Next",     self._go_next, ".")
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", self.close)

        # Edit
        edit_menu = mb.addMenu("Edit")
        self._add_action(edit_menu, "Undo", self._undo, "Ctrl+Z")
        self._add_action(edit_menu, "Redo", self._redo, "Ctrl+Y")

        # View
        view_menu = mb.addMenu("View")
        self._add_action(view_menu, "Frame Mesh",    self._viewer.frame_mesh, "F")
        self._add_action(view_menu, "Toggle Wireframe", self._toggle_wireframe, "W")
        view_menu.addSeparator()
        self._add_action(view_menu, "Front View",  lambda: self._viewer.set_view("front"))
        self._add_action(view_menu, "Right View",  lambda: self._viewer.set_view("right"))
        self._add_action(view_menu, "Top View",    lambda: self._viewer.set_view("top"))
        self._add_action(view_menu, "Reset View",  lambda: self._viewer.set_view("reset"))

        # Help
        help_menu = mb.addMenu("Help")
        self._add_action(help_menu, "Keyboard Shortcuts", self._show_shortcuts, "F1")

    def _add_action(self, menu: QMenu, label: str, slot, shortcut: str = "") -> QAction:
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _connect_signals(self):
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        # Wire btn: Qt auto-flips checked state on click; we only need to sync viewer.
        # For keyboard shortcut W, _toggle_wireframe also manually flips the button.
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
        # Note: 1/3/7/0 for views and 1-0 for colors are handled in keyPressEvent
        # to avoid conflicts. Menu bar handles Ctrl+S, Ctrl+Z, Ctrl+Y, F, W, F1.

    def keyPressEvent(self, e):
        key = e.key()
        mod = e.modifiers()

        # Numpad view presets — distinguished by Qt.KeypadModifier (cross-platform)
        if mod & Qt.KeypadModifier:
            view_map = {
                Qt.Key_1: "front",
                Qt.Key_3: "right",
                Qt.Key_7: "top",
                Qt.Key_0: "reset",
            }
            if key in view_map:
                self._viewer.set_view(view_map[key])
                return

        # Color selection 1–9, 0 (regular keyboard only, no modifiers)
        # Use a set to avoid the '' in "123..." substring-match false positive
        char = e.text()
        if char in {"1","2","3","4","5","6","7","8","9","0"} and not mod:
            idx = (int(char) - 1) if char != "0" else 9
            self._set_color(idx)
            return

        super().keyPressEvent(e)

    # ------------------------------------------------------------------
    # Folder / file loading
    # ------------------------------------------------------------------

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
            f"Loaded {self._file_mgr.current_filename} — {len(verts):,} vertices")

    def _update_title(self):
        fn     = self._file_mgr.current_filename
        idx    = self._file_mgr.current_index + 1
        total  = self._file_mgr.count
        marker = " *" if self._unsaved else ""
        self._file_label.setText(f"File {idx} / {total} — {fn}{marker}")
        self.setWindowTitle(f"Tooth Annotator — {fn}{marker}")

    def _update_nav_buttons(self):
        self._prev_btn.setEnabled(self._file_mgr.has_prev())
        self._next_btn.setEnabled(self._file_mgr.has_next())

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

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
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Yes:
            if not self._save_current():
                return False  # save failed → don't navigate
        return True

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Palette / brush
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _on_palette_color_selected(self, idx: int):
        self._set_color(idx)

    def _set_color(self, idx: int):
        idx = idx % len(PALETTE_RGB)
        self._viewer.active_color = PALETTE_RGB[idx].copy()
        self._palette.select_color(idx)

    @pyqtSlot(int)
    def _on_brush_radius_changed(self, r: int):
        self._brush_radius       = r
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

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_current(self) -> bool:
        """Write PLY. Returns True on success, False on failure."""
        if not self._model.loaded:
            return True
        out_path = self._file_mgr.output_path(self._file_mgr.current_filename)
        try:
            write_ply(out_path, self._model.vertices,
                      self._model.faces, self._model.colors)
        except Exception as ex:
            QMessageBox.critical(self, "Save Error", str(ex))
            return False

        # Verify in-memory instead of re-reading from disk
        bad = (~colors_are_palette_exact(self._model.colors)).sum()
        n   = len(self._model.colors)
        n_cols = len({tuple(c) for c in self._model.colors.tolist()})
        if bad:
            self._status.showMessage(
                f"Saved {self._file_mgr.current_filename} — "
                f"⚠ {bad} non-palette vertex/vertices")
        else:
            self._status.showMessage(
                f"Saved {self._file_mgr.current_filename} — "
                f"{n:,} vertices, {n_cols} colors")

        self._unsaved = False
        self._update_title()
        return True

    # ------------------------------------------------------------------
    # Wireframe (keyboard/menu path — button click takes the direct path)
    # ------------------------------------------------------------------

    def _toggle_wireframe(self):
        """Called from menu action / W key. Button click goes directly to viewer."""
        self._viewer.toggle_wireframe()
        # Button click auto-flips checked; keyboard shortcut does not → sync manually
        self._wire_btn.setChecked(not self._wire_btn.isChecked())

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_shortcuts(self):
        dlg = ShortcutHelpDialog(self)
        dlg.show()

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, e):
        if self._unsaved:
            reply = QMessageBox.question(
                self, "Unsaved Changes", "Save before quitting?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                e.ignore()
                return
            if reply == QMessageBox.Yes:
                if not self._save_current():
                    e.ignore()   # save failed — abort close to prevent data loss
                    return
        e.accept()
