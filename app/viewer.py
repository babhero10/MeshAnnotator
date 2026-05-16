"""
ViewerWidget — thin Qt widget for 3D mesh display and annotation.

Wireframe: rendered as an Open3D LineSet in the 3D scene (depth-tested),
not as a 2D pixel overlay. Eliminates back-face edge bleed-through.

Scroll: _apply_camera() called immediately on wheel events so the render
fires on the next 16 ms tick instead of waiting for a 200 ms debounce.
"""
from __future__ import annotations

import time
import numpy as np
import open3d as o3d

from PyQt6.QtWidgets import QWidget, QSizePolicy, QApplication
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QTabletEvent

from app.camera import ArcballCamera
from app.renderer import MeshRenderer
from app.input_handler import InputHandler, NavMode
from app.config import PALETTE_RGB

# ── Blender-Solid-style view-space studio lights ───────────────────────────────
# Directions are in camera/view space: +X right, +Y up, -Z into screen.
# Direction = where light travels (from source toward surface).
# Shading is computed in Python so it is guaranteed camera-fixed regardless of
# what Open3D does with its world-space IBL or directional light internals.
_VS_LIGHTS = [
    # (view-space direction,              light RGB,               weight)
    (np.array([ 0.45, -0.75, -0.50]),  np.array([1.00, 0.97, 0.93]),  0.65),  # key
    (np.array([-0.75, -0.10, -0.65]),  np.array([0.72, 0.82, 1.00]),  0.22),  # fill
    (np.array([ 0.00, -0.20,  0.98]),  np.array([0.55, 0.62, 0.80]),  0.20),  # rim
]
_VS_LIGHTS = [(d / np.linalg.norm(d), c, w) for d, c, w in _VS_LIGHTS]
_AMBIENT    = 0.18   # minimum brightness so dark faces are never pitch-black


def _shade_colors(normals: np.ndarray, view_R: np.ndarray,
                  colors: np.ndarray) -> np.ndarray:
    """Lambertian diffuse shading in view space — pure numpy, no specular."""
    N_vs    = (view_R @ normals.T).T                    # Nx3 normals in view space
    shading = np.full((len(normals), 3), _AMBIENT, dtype=np.float32)
    for d_vs, light_rgb, weight in _VS_LIGHTS:
        # dot(N, -d_vs): negative because d_vs points *toward* the surface
        NdotL    = np.maximum(0.0, -(N_vs @ d_vs))     # N,
        shading += NdotL[:, np.newaxis] * (light_rgb * weight)
    np.clip(shading, 0.0, 1.0, out=shading)
    result = colors.astype(np.float32) * shading
    np.clip(result, 0, 255, out=result)
    return result.astype(np.uint8)


def _all_mesh_edges(faces: np.ndarray) -> np.ndarray:
    """All unique undirected edges — fully vectorized, no Python loop."""
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = edges[order]
    mask  = np.ones(len(edges), dtype=bool)
    mask[1:] = np.any(edges[1:] != edges[:-1], axis=1)
    return edges[mask].astype(np.int32)


def _compute_edge_angles(vertices: np.ndarray, faces: np.ndarray,
                         edges: np.ndarray) -> np.ndarray:
    """Per-edge dihedral angle in [0, π]. Boundary edges get π (most important).

    Higher angle = sharper crease = more important to display.
    Fully vectorized — no Python loop over faces.
    """
    n_v = len(vertices)

    # Face normals
    e1 = vertices[faces[:, 1]] - vertices[faces[:, 0]]
    e2 = vertices[faces[:, 2]] - vertices[faces[:, 0]]
    fn = np.cross(e1, e2).astype(np.float64)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-10)

    # For every face produce 3 (sorted-edge-key, face-id) pairs
    f_e   = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    f_e_s = np.sort(f_e, axis=1)
    fi_rep = np.tile(np.arange(len(faces)), 3)
    fe_key = f_e_s[:, 0].astype(np.int64) * (n_v + 1) + f_e_s[:, 1].astype(np.int64)

    # Build sorted lookup: edge key → original edge index
    e_key  = edges[:, 0].astype(np.int64) * (n_v + 1) + edges[:, 1].astype(np.int64)
    order  = np.argsort(e_key)
    s_ekey = e_key[order]

    # Match each face-edge to its edge index
    idx   = np.clip(np.searchsorted(s_ekey, fe_key), 0, len(s_ekey) - 1)
    valid = s_ekey[idx] == fe_key
    ei    = order[idx[valid]]   # original edge indices
    fi    = fi_rep[valid]       # corresponding face indices

    # Group by edge (sort) to find the two faces per interior edge
    so   = np.argsort(ei, stable=True)
    s_ei = ei[so];  s_fi = fi[so]

    uniq, cnt = np.unique(s_ei, return_counts=True)
    interior  = uniq[cnt == 2]
    starts    = np.searchsorted(s_ei, interior)
    fi1, fi2  = s_fi[starts], s_fi[starts + 1]

    cos_a    = np.clip((fn[fi1] * fn[fi2]).sum(axis=1), -1.0, 1.0)
    dihedral = np.arccos(cos_a).astype(np.float32)

    angles           = np.full(len(edges), np.pi, dtype=np.float32)
    angles[interior] = dihedral
    return angles


class ViewerWidget(QWidget):
    paint_stroke = pyqtSignal(float, float, float, int)
    stroke_begin = pyqtSignal()
    stroke_end   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking, True)

        self._renderer = MeshRenderer(max(self.width(), 16), max(self.height(), 16))
        self._input    = InputHandler(brush_radius=15, parent=self)
        self._camera: ArcballCamera | None = None
        self._mesh:   o3d.geometry.TriangleMesh | None = None

        self._needs_redraw   = False
        self._nav_active     = False
        self._nav_mode       = NavMode.ROTATE
        self._verts_np:       np.ndarray | None = None
        self._verts_normals:  np.ndarray | None = None
        self._verts_2d:       np.ndarray | None = None
        self._verts_vs_depth: np.ndarray | None = None
        self._depth_buf_vs:   np.ndarray | None = None
        self._mesh_tol:       float = 1.0
        self._wire_edges:    np.ndarray | None = None
        self._proj_dirty     = True
        self._show_wireframe = False

        self._mouse_pos:       QPoint | None = None
        self._cursor_hidden:   bool = False
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(150)
        self._cursor_timer.timeout.connect(self.restore_cursor)
        self._cached_qimage:  QImage | None = None
        self._last_render_t   = 0.0
        self._pending_colors: np.ndarray | None = None

        self._brush_radius  = 15
        self.active_color   = PALETTE_RGB[0].copy()
        self._true_colors:   np.ndarray | None = None
        self._view_R:        np.ndarray | None = None
        self._shading_dirty: bool = False
        self._wire_angles:   np.ndarray | None = None   # per-edge dihedral angle
        self._wire_density:  float = 1.0                # 0-1 fraction of edges to show

        self._connect_input()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(16)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

    # ------------------------------------------------------------------
    # Brush radius (synced to InputHandler)
    # ------------------------------------------------------------------

    @property
    def brush_radius(self) -> int:
        return self._brush_radius

    @brush_radius.setter
    def brush_radius(self, value: int):
        self._brush_radius = value
        self._input.brush_radius = value

    # ------------------------------------------------------------------
    # InputHandler wiring
    # ------------------------------------------------------------------

    def _connect_input(self):
        inp = self._input
        inp.paint_started.connect(self.stroke_begin)
        inp.paint_moved.connect(self.paint_stroke)
        inp.paint_ended.connect(self.stroke_end)
        inp.nav_started.connect(self._on_nav_start)
        inp.nav_moved.connect(self._on_nav_move)
        inp.nav_ended.connect(lambda: setattr(self, '_nav_active', False))

    def _on_nav_start(self, mode: NavMode):
        self._nav_mode   = mode
        self._nav_active = True

    def _on_nav_move(self, dx: int, dy: int):
        if self._camera is None:
            return
        if self._nav_mode == NavMode.ROTATE:
            self._camera.rotate(dx, dy)
        elif self._nav_mode == NavMode.PAN:
            self._camera.pan(dx, dy)
        elif self._nav_mode == NavMode.ZOOM:
            self._camera.zoom(-dy, sensitivity=0.05)
        self._apply_camera()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_mesh(self, vertices: np.ndarray, faces: np.ndarray,
                  colors: np.ndarray):
        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices      = o3d.utility.Vector3dVector(vertices.astype(np.float64))
        mesh.triangles     = o3d.utility.Vector3iVector(faces)
        mesh.vertex_colors = o3d.utility.Vector3dVector(
            colors.astype(np.float64) / 255.0)
        self._mesh           = mesh
        self._verts_np       = vertices.copy()
        self._true_colors    = colors.copy()
        self._verts_2d       = None
        self._verts_normals  = None
        self._verts_vs_depth = None
        self._depth_buf_vs   = None
        self._proj_dirty     = True
        self._wire_edges     = _all_mesh_edges(faces)
        self._wire_angles    = None   # computed after normals are fixed below
        self._pending_colors = None
        self._shading_dirty  = True

        bbox = mesh.get_axis_aligned_bounding_box()
        diag = np.linalg.norm(
            np.asarray(bbox.get_max_bound()) - np.asarray(bbox.get_min_bound()))
        self._camera    = ArcballCamera(bbox.get_center(), distance=diag * 1.5)
        self._mesh_tol  = float(diag) * 0.01

        self._renderer.upload_geometry(mesh, compute_normals=True)

        normals  = np.asarray(mesh.vertex_normals).copy()
        centroid = self._verts_np.mean(axis=0)
        outward  = self._verts_np - centroid
        if np.einsum('ij,ij->i', normals, outward).mean() < 0:
            normals = -normals
            mesh.vertex_normals = o3d.utility.Vector3dVector(normals.astype(np.float64))
        self._verts_normals = normals
        self._wire_angles   = _compute_edge_angles(
            self._verts_np, faces, self._wire_edges)
        if self._show_wireframe:
            self._renderer.add_wireframe(self._verts_np, self._filtered_wire_edges())
        self._apply_camera()
        self._needs_redraw = True

    def update_colors(self, colors: np.ndarray):
        if self._mesh is None:
            return
        self._pending_colors = colors   # triggers shading recompute in _do_render
        self._needs_redraw   = True

    def toggle_wireframe(self):
        self._show_wireframe = not self._show_wireframe
        if self._show_wireframe and self._wire_edges is not None:
            self._renderer.add_wireframe(self._verts_np, self._filtered_wire_edges())
        else:
            self._renderer.remove_wireframe()
        self._needs_redraw = True

    def set_wire_density(self, density: float):
        """Set wireframe density (0–1). 1 = all edges; lower = only sharpest edges."""
        self._wire_density = float(density)
        if self._show_wireframe and self._wire_edges is not None:
            self._renderer.add_wireframe(self._verts_np, self._filtered_wire_edges())
            self._needs_redraw = True

    def filtered_wire_edge_count(self) -> int:
        return len(self._filtered_wire_edges()) if self._wire_edges is not None else 0

    def _filtered_wire_edges(self) -> np.ndarray:
        if self._wire_edges is None:
            return np.empty((0, 2), dtype=np.int32)
        if self._wire_density >= 1.0 or self._wire_angles is None:
            return self._wire_edges
        n_keep = max(1, int(round(len(self._wire_edges) * self._wire_density)))
        # argpartition is O(n) — faster than full sort for large edge counts
        order  = np.argpartition(self._wire_angles, -n_keep)[-n_keep:]
        return self._wire_edges[order]

    def frame_mesh(self):
        if self._mesh is None or self._camera is None:
            return
        bbox = self._mesh.get_axis_aligned_bounding_box()
        diag = np.linalg.norm(
            np.asarray(bbox.get_max_bound()) - np.asarray(bbox.get_min_bound()))
        self._camera.center   = np.array(bbox.get_center())
        self._camera.distance = diag * 1.5
        self._apply_camera()

    def set_view(self, name: str):
        if self._camera is None:
            return
        dispatch = {
            'front': self._camera.set_front_view,
            'right': self._camera.set_right_view,
            'top':   self._camera.set_top_view,
            'reset': self._camera.reset_view,
        }
        fn = dispatch.get(name)
        if fn:
            fn()
            self._apply_camera()

    def to_render_coords(self, x: float, y: float,
                         radius: float) -> tuple[float, float, float]:
        rw, rh = self._renderer.size
        ww     = max(self.width(),  1)
        wh     = max(self.height(), 1)
        return x * (rw / ww), y * (rh / wh), radius * (rw / ww)

    def compute_paint_mask(self, rx: float, ry: float,
                           rr: float) -> np.ndarray | None:
        if self._verts_2d is None:
            return None

        dx = self._verts_2d[:, 0] - rx
        dy = self._verts_2d[:, 1] - ry
        in_radius = (dx * dx + dy * dy) <= (rr * rr)

        if not in_radius.any():
            return in_radius

        if self._depth_buf_vs is not None and self._verts_vs_depth is not None:
            dh, dw = self._depth_buf_vs.shape
            px = np.clip(self._verts_2d[:, 0].astype(np.int32), 0, dw - 1)
            py = np.clip(self._verts_2d[:, 1].astype(np.int32), 0, dh - 1)
            buf = self._depth_buf_vs[py, px]
            vd  = self._verts_vs_depth
            visible = (vd > 0.0) & (vd <= buf + self._mesh_tol)
            return in_radius & visible

        if self._camera is None or self._verts_normals is None:
            return in_radius
        cam_pos = self._camera.get_position()
        to_cam  = cam_pos - self._verts_np
        return in_radius & (np.einsum('ij,ij->i', self._verts_normals, to_cam) > 0.0)

    @property
    def verts_2d(self) -> np.ndarray | None:
        return self._verts_2d

    @property
    def input_handler(self) -> InputHandler:
        return self._input

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _apply_camera(self):
        if self._camera is None:
            return
        pos    = self._camera.get_position().astype(np.float64)
        target = self._camera.center.astype(np.float64)
        up     = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        if abs(self._camera.phi) < 0.1 or abs(self._camera.phi - np.pi) < 0.1:
            up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self._renderer.setup_camera(target, pos, up)

        # Compute view-space rotation matrix for software shading (Blender Solid behavior).
        fwd   = target - pos;  fwd   /= np.linalg.norm(fwd)
        right = np.cross(fwd, up);  right /= np.linalg.norm(right)
        tup   = np.cross(right, fwd)
        self._view_R       = np.array([right, tup, -fwd], dtype=np.float64)
        self._shading_dirty = True

        self._proj_dirty   = True
        self._needs_redraw = True

    # ------------------------------------------------------------------
    # Render loop
    # ------------------------------------------------------------------

    _NAV_INTERVAL   = 1.0 / 30.0
    _PAINT_INTERVAL = 1.0 / 20.0

    def _tick(self):
        if self._needs_redraw:
            now      = time.monotonic()
            interval = (self._NAV_INTERVAL   if self._nav_active
                        else self._PAINT_INTERVAL if self._input.is_painting
                        else 0.0)
            if now - self._last_render_t >= interval:
                self._do_render()
                self._last_render_t = now
        self.update()

    def _do_render(self):
        # Accept new annotation colors from a paint stroke
        if self._pending_colors is not None:
            self._true_colors    = self._pending_colors
            self._pending_colors = None
            self._shading_dirty  = True

        # Recompute shaded display colors whenever camera or annotation colors changed
        if (self._shading_dirty and self._mesh is not None
                and self._verts_normals is not None and self._view_R is not None):
            shaded = _shade_colors(self._verts_normals, self._view_R, self._true_colors)
            self._mesh.vertex_colors = o3d.utility.Vector3dVector(
                shaded.astype(np.float64) / 255.0)
            self._renderer.update_colors(self._mesh)
            self._shading_dirty = False

        arr = self._renderer.render()
        if arr is None:
            return
        h, w = arr.shape[:2]
        self._cached_qimage = QImage(arr.data, w, h, w * 3,
                                     QImage.Format.Format_RGB888)
        self._needs_redraw  = False

        if self._proj_dirty and self._verts_np is not None:
            self._verts_2d, _ = self._renderer.project_vertices_with_depth(self._verts_np)

            view_mat = self._renderer.get_view_matrix()
            if view_mat is not None and self._verts_2d is not None:
                vh = np.hstack([self._verts_np.astype(np.float64),
                                np.ones((len(self._verts_np), 1))])
                self._verts_vs_depth = (-(view_mat @ vh.T)[2]).astype(np.float32)
                self._depth_buf_vs = self._renderer.render_depth_view_space()

            self._proj_dirty = False

    # ------------------------------------------------------------------
    # Qt paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        if self._cached_qimage is not None:
            p.drawImage(self.rect(), self._cached_qimage)
        else:
            p.fillRect(self.rect(), QColor(46, 46, 46))
        if self._mouse_pos is not None:
            self._draw_cursor(p)

    def _draw_cursor(self, p: QPainter):
        x, y = self._mouse_pos.x(), self._mouse_pos.y()
        r    = self._brush_radius
        rc   = self.active_color
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 200), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(x - r, y - r, r * 2, r * 2)
        p.setPen(QPen(QColor(int(rc[0]), int(rc[1]), int(rc[2]), 230), 1.5))
        p.drawEllipse(x - r + 2, y - r + 2, r * 2 - 4, r * 2 - 4)
        p.setPen(QPen(QColor(0, 0, 0, 220), 1.0))
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawEllipse(x - 2, y - 2, 4, 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        resized = self._renderer.resize(self.width(), self.height())
        if resized and self._mesh is not None:
            self._renderer.upload_geometry(self._mesh, compute_normals=False)
            if self._show_wireframe and self._wire_edges is not None:
                self._renderer.add_wireframe(self._verts_np, self._filtered_wire_edges())
            self._apply_camera()
        self._needs_redraw = True

    # ------------------------------------------------------------------
    # Cursor management
    # ------------------------------------------------------------------

    def _hide_cursor(self):
        if not self._cursor_hidden:
            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self._cursor_hidden = True
        self._cursor_timer.start()

    def restore_cursor(self):
        self._cursor_timer.stop()
        if self._cursor_hidden:
            QApplication.restoreOverrideCursor()
            self._cursor_hidden = False

    # ------------------------------------------------------------------
    # Input events — delegate entirely to InputHandler
    # ------------------------------------------------------------------

    def tabletEvent(self, event: QTabletEvent):
        self._hide_cursor()
        local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
        self._mouse_pos = local_pos
        self._input.handle_tablet(event, local_pos)

    def mousePressEvent(self, e):
        corrected = self.mapFromGlobal(e.globalPosition().toPoint())
        self._input.handle_mouse_press(e, corrected)

    def mouseMoveEvent(self, e):
        self._hide_cursor()
        corrected = self.mapFromGlobal(e.globalPosition().toPoint())
        self._mouse_pos = corrected
        self._input.handle_mouse_move(e, corrected)

    def mouseReleaseEvent(self, e):
        self._input.handle_mouse_release(e)

    def leaveEvent(self, e):
        self.restore_cursor()
        self._mouse_pos = None
        self._input.reset()
        self.update()

    def wheelEvent(self, e):
        if self._camera is None:
            return
        self._camera.zoom(e.angleDelta().y() / 120.0)
        self._apply_camera()
