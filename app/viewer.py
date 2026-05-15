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

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPainter, QPen, QColor, QTabletEvent

from app.camera import ArcballCamera
from app.renderer import MeshRenderer
from app.input_handler import InputHandler, NavMode
from app.config import PALETTE_RGB


def _all_mesh_edges(faces: np.ndarray) -> np.ndarray:
    """All unique undirected edges — fully vectorized, no Python loop."""
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = edges[order]
    mask  = np.ones(len(edges), dtype=bool)
    mask[1:] = np.any(edges[1:] != edges[:-1], axis=1)
    return edges[mask].astype(np.int32)


class ViewerWidget(QWidget):
    paint_stroke = pyqtSignal(float, float, float, int)
    stroke_begin = pyqtSignal()
    stroke_end   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.BlankCursor)
        # WA_TabletTracking: deliver TabletMove events even when the pen is hovering
        # (not touching). Without this the brush cursor only appears after first contact.
        self.setAttribute(Qt.WA_TabletTracking, True)
        # WA_AcceptTouchEvents intentionally omitted — interferes with tablet events

        self._renderer = MeshRenderer(max(self.width(), 16), max(self.height(), 16))
        self._input    = InputHandler(brush_radius=15, parent=self)
        self._camera: ArcballCamera | None = None
        self._mesh:   o3d.geometry.TriangleMesh | None = None

        self._needs_redraw   = False
        self._nav_active     = False
        self._nav_mode       = NavMode.ROTATE
        self._verts_np:       np.ndarray | None = None
        self._verts_normals:  np.ndarray | None = None  # Nx3 unit normals (fallback only)
        self._verts_2d:       np.ndarray | None = None  # render-buffer pixel coords Nx2
        self._verts_vs_depth: np.ndarray | None = None  # view-space depth per vertex N
        self._depth_buf_vs:   np.ndarray | None = None  # rendered view-space depth HxW
        self._mesh_tol:       float = 1.0               # world-unit depth tolerance
        self._wire_edges:    np.ndarray | None = None  # all mesh edges Mx2
        self._proj_dirty     = True
        self._show_wireframe = False

        self._mouse_pos:      QPoint | None = None
        self._cached_qimage:  QImage | None = None
        self._last_render_t   = 0.0
        # Pending color array: defers GPU upload to render time.
        # update_colors() stores the array here; _do_render() uploads it once per frame.
        self._pending_colors: np.ndarray | None = None

        self._brush_radius = 15
        self.active_color  = PALETTE_RGB[0].copy()

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
        self._mesh          = mesh
        self._verts_np      = vertices.copy()
        self._verts_2d      = None
        self._verts_normals = None
        self._verts_vs_depth = None
        self._depth_buf_vs   = None
        self._proj_dirty     = True
        self._wire_edges      = _all_mesh_edges(faces)
        self._pending_colors  = None  # clear any leftover pending from previous mesh

        bbox = mesh.get_axis_aligned_bounding_box()
        diag = np.linalg.norm(
            np.asarray(bbox.get_max_bound()) - np.asarray(bbox.get_min_bound()))
        self._camera    = ArcballCamera(bbox.get_center(), distance=diag * 1.5)
        self._mesh_tol  = float(diag) * 0.01  # world-unit tolerance for depth test

        self._renderer.upload_geometry(mesh, compute_normals=True)

        # Read back normals for paint-side visibility culling.
        # compute_vertex_normals() does NOT guarantee outward direction — it depends on
        # the PLY file's face winding order.  Dental mesh exporters commonly produce
        # inward-wound faces, so all normals end up pointing INTO the mesh.  When that
        # happens, front-facing vertices have dot(normal, to_cam) < 0 and are EXCLUDED
        # from painting while the invisible back-facing vertices are painted instead.
        #
        # Fix: check the mean alignment of normals against the centroid-to-vertex
        # direction.  For any (approximately) convex mesh the outward normal must have
        # positive agreement with that direction.  A negative mean means all normals are
        # flipped, so we flip them back.
        normals  = np.asarray(mesh.vertex_normals).copy()
        centroid = self._verts_np.mean(axis=0)
        outward  = self._verts_np - centroid            # expected outward direction
        if np.einsum('ij,ij->i', normals, outward).mean() < 0:
            normals = -normals
            # Update the mesh object too so Open3D lighting stays correct
            mesh.vertex_normals = o3d.utility.Vector3dVector(normals.astype(np.float64))
        self._verts_normals = normals
        if self._show_wireframe:
            self._renderer.add_wireframe(self._verts_np, self._wire_edges)
        self._apply_camera()
        self._needs_redraw = True

    def update_colors(self, colors: np.ndarray):
        """Queue a color update. GPU upload is deferred to the next render frame.

        On a 200 Hz tablet this is called ~200×/s; the GPU upload (remove_geometry
        + add_geometry in Open3D) only happens once per rendered frame (~10 fps).
        """
        if self._mesh is None:
            return
        self._pending_colors = colors   # store reference — no conversion yet
        self._needs_redraw   = True

    def toggle_wireframe(self):
        self._show_wireframe = not self._show_wireframe
        if self._show_wireframe and self._wire_edges is not None:
            self._renderer.add_wireframe(self._verts_np, self._wire_edges)
        else:
            self._renderer.remove_wireframe()
        self._needs_redraw = True

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
        """Public view presets: 'front', 'right', 'top', 'reset'."""
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
        """Convert widget pixel coords to render-buffer coords for paint hit-testing."""
        rw, rh = self._renderer.size
        ww     = max(self.width(),  1)
        wh     = max(self.height(), 1)
        return x * (rw / ww), y * (rh / wh), radius * (rw / ww)

    def compute_paint_mask(self, rx: float, ry: float,
                           rr: float) -> np.ndarray | None:
        """Boolean mask of vertices that are (a) within paint radius and (b) visible.

        Visibility uses a face-accurate depth test:
        - Each vertex's view-space depth is compared against the rendered depth buffer
          at its screen pixel.
        - The depth buffer records the first FACE hit by each camera ray, so back-face
          vertices that fall between front vertices (pixel gaps) are still rejected.
        - View-space depth (z_in_view_space=True) is free from Filament's reversed-Z.
        """
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
            buf = self._depth_buf_vs[py, px]   # depth of first face at each pixel
            vd  = self._verts_vs_depth
            # _mesh_tol (1 % of bbox diagonal) gives world-unit slack for normal
            # interpolation across a face without letting back faces through.
            visible = (vd > 0.0) & (vd <= buf + self._mesh_tol)
            return in_radius & visible

        # Fallback before first render: normal dot-product test
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
        pos    = self._camera.get_position().astype(np.float32)
        target = self._camera.center.astype(np.float32)
        up     = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        if abs(self._camera.phi) < 0.1 or abs(self._camera.phi - np.pi) < 0.1:
            up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        self._renderer.setup_camera(target, pos, up)
        self._proj_dirty   = True
        self._needs_redraw = True

    # ------------------------------------------------------------------
    # Render loop
    # ------------------------------------------------------------------

    _NAV_INTERVAL   = 1.0 / 30.0   # 30 fps during navigation (was 8 — too choppy)
    _PAINT_INTERVAL = 1.0 / 20.0   # 20 fps during painting (GPU upload deferred)

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
        # Flush pending color update — one GPU upload per frame regardless of
        # how many update_colors() calls happened since the last render.
        if self._pending_colors is not None:
            self._mesh.vertex_colors = o3d.utility.Vector3dVector(
                self._pending_colors.astype(np.float64) / 255.0)
            self._renderer.update_colors(self._mesh)
            self._pending_colors = None

        arr = self._renderer.render()
        if arr is None:
            return
        h, w = arr.shape[:2]
        self._cached_qimage = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
        self._needs_redraw  = False

        if self._proj_dirty and self._verts_np is not None:
            self._verts_2d, _ = self._renderer.project_vertices_with_depth(self._verts_np)

            # View-space depth per vertex: distance from the camera plane along its axis.
            # Computed from the view matrix (no projection / no reversed-Z involved).
            # In Open3D's OpenGL-convention view space the camera looks in -Z, so
            # objects in front have negative z; negate to get positive depths.
            view_mat = self._renderer.get_view_matrix()
            if view_mat is not None and self._verts_2d is not None:
                vh = np.hstack([self._verts_np.astype(np.float64),
                                np.ones((len(self._verts_np), 1))])
                self._verts_vs_depth = (-( view_mat @ vh.T)[2]).astype(np.float32)

                # Render depth in view-space (z_in_view_space=True returns the same
                # positive distances regardless of Filament's internal reversed-Z).
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
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 200), 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(x - r, y - r, r * 2, r * 2)
        p.setPen(QPen(QColor(int(rc[0]), int(rc[1]), int(rc[2]), 230), 1.5))
        p.drawEllipse(x - r + 2, y - r + 2, r * 2 - 4, r * 2 - 4)
        # Center dot: black outline + white fill for visibility on any background
        p.setPen(QPen(QColor(0, 0, 0, 220), 1.0))
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawEllipse(x - 2, y - 2, 4, 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        resized = self._renderer.resize(self.width(), self.height())
        if resized and self._mesh is not None:
            self._renderer.upload_geometry(self._mesh, compute_normals=False)
            if self._show_wireframe and self._wire_edges is not None:
                self._renderer.add_wireframe(self._verts_np, self._wire_edges)
            self._apply_camera()
        self._needs_redraw = True

    # ------------------------------------------------------------------
    # Input events — delegate entirely to InputHandler
    # ------------------------------------------------------------------

    def tabletEvent(self, event: QTabletEvent):
        self._mouse_pos = event.pos()
        self._input.handle_tablet(event)

    def mousePressEvent(self, e):
        self._input.handle_mouse_press(e)

    def mouseMoveEvent(self, e):
        self._mouse_pos = e.pos()
        self._input.handle_mouse_move(e)

    def mouseReleaseEvent(self, e):
        self._input.handle_mouse_release(e)

    def leaveEvent(self, e):
        self._mouse_pos = None
        self._input.reset()
        self.update()

    def wheelEvent(self, e):
        if self._camera is None:
            return
        self._camera.zoom(e.angleDelta().y() / 120.0)
        self._apply_camera()  # sets _needs_redraw=True → renders on next 16ms tick
