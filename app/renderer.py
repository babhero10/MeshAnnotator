"""
MeshRenderer — wraps Open3D OffscreenRenderer.

Single Responsibility: renderer lifecycle (create, resize, render).
Normals are computed only on geometry load, never on color-only updates.
"""
from __future__ import annotations

import numpy as np
import open3d as o3d
from open3d.visualization import rendering

_FOV = 60.0


class MeshRenderer:
    def __init__(self, width: int, height: int):
        self._w = max(width, 16)
        self._h = max(height, 16)
        self._renderer: rendering.OffscreenRenderer | None = None
        self._scene = None
        self._last_image: np.ndarray | None = None
        self._initializing = False  # re-entrancy guard for OffscreenRenderer creation

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _ensure(self) -> bool:
        if self._renderer is None:
            if self._initializing:
                return False  # re-entrant call during OffscreenRenderer construction
            self._initializing = True
            try:
                self._renderer = rendering.OffscreenRenderer(self._w, self._h)
                self._scene    = self._renderer.scene
                self._init_lighting()
            finally:
                self._initializing = False
        return self._renderer is not None

    def _init_lighting(self):
        s = self._scene
        s.set_background([0.22, 0.22, 0.22, 1.0])
        # All shading is computed in software by viewer.py using view-space lights.
        # The renderer uses defaultUnlit so Open3D contributes zero world-space lighting.
        s.scene.enable_indirect_light(False)
        s.scene.set_indirect_light_intensity(0)

    def resize(self, width: int, height: int) -> bool:
        """Invalidate renderer on size change; return True if resize occurred."""
        w, h = max(width, 16), max(height, 16)
        if w == self._w and h == self._h:
            return False
        self._w, self._h = w, h
        # OffscreenRenderer has no resize method — must recreate
        self._renderer   = None
        self._scene      = None
        self._last_image = None
        return True

    # ------------------------------------------------------------------
    # Mesh upload
    # ------------------------------------------------------------------

    @staticmethod
    def _material() -> rendering.MaterialRecord:
        m = rendering.MaterialRecord()
        m.shader     = "defaultUnlit"   # vertex colors passed through unchanged
        m.base_color = [1.0, 1.0, 1.0, 1.0]
        return m

    def _put_mesh(self, mesh: o3d.geometry.TriangleMesh):
        if self._scene.has_geometry("mesh"):
            self._scene.remove_geometry("mesh")
        self._scene.add_geometry("mesh", mesh, self._material())

    def upload_geometry(self, mesh: o3d.geometry.TriangleMesh,
                        compute_normals: bool = True):
        """Upload mesh geometry. Set compute_normals=False when restoring after resize."""
        if not self._ensure():
            return
        if compute_normals:
            mesh.compute_vertex_normals()
        self._put_mesh(mesh)

    def update_colors(self, mesh: o3d.geometry.TriangleMesh):
        """Re-upload mesh with updated vertex colors only — normals unchanged."""
        if not self._ensure():
            return
        self._put_mesh(mesh)

    # ------------------------------------------------------------------
    # Wireframe (Open3D LineSet — depth-tested, no 2D overlay artifacts)
    # ------------------------------------------------------------------

    def add_wireframe(self, vertices: np.ndarray, edges: np.ndarray):
        """Add all-edge wireframe as a LineSet rendered in the 3D scene."""
        if not self._ensure():
            return
        if self._scene.has_geometry("wireframe"):
            self._scene.remove_geometry("wireframe")
        ls = o3d.geometry.LineSet()
        ls.points = o3d.utility.Vector3dVector(vertices.astype(np.float64))
        ls.lines  = o3d.utility.Vector2iVector(edges)
        ls.colors = o3d.utility.Vector3dVector(
            np.full((len(edges), 3), 0.12))  # dark grey
        mat = rendering.MaterialRecord()
        mat.shader     = "unlitLine"
        mat.line_width = 1.0
        self._scene.add_geometry("wireframe", ls, mat)

    def remove_wireframe(self):
        if self._scene is not None and self._scene.has_geometry("wireframe"):
            self._scene.remove_geometry("wireframe")

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def setup_camera(self, target: np.ndarray, position: np.ndarray, up: np.ndarray):
        if self._ensure():
            self._renderer.setup_camera(
                _FOV, target.tolist(), position.tolist(), up.tolist())

    # ------------------------------------------------------------------
    # Render / project
    # ------------------------------------------------------------------

    def get_view_matrix(self) -> np.ndarray | None:
        """Return the current 4×4 camera view matrix."""
        if self._scene is None:
            return None
        return np.array(self._scene.camera.get_view_matrix(), dtype=np.float64)

    def render_depth_view_space(self) -> np.ndarray | None:
        """Render depth as positive view-space distances (camera plane to surface).
        Uses z_in_view_space=True so values are unaffected by Filament's reversed-Z."""
        if not self._ensure():
            return None
        return np.asarray(
            self._renderer.render_to_depth_image(z_in_view_space=True), dtype=np.float32)

    def render(self) -> np.ndarray | None:
        """Render scene; return HxWx3 uint8 array or None."""
        if not self._ensure():
            return None
        self._last_image = np.asarray(
            self._renderer.render_to_image(), dtype=np.uint8).copy()
        return self._last_image

    def project_vertices(self, vertices: np.ndarray) -> np.ndarray | None:
        """Project Nx3 world coords → Nx2 render-buffer pixel coords."""
        coords, _ = self.project_vertices_with_depth(vertices)
        return coords

    def project_vertices_with_depth(self, vertices: np.ndarray
                                    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Project Nx3 world coords → (Nx2 screen pixels, N window-space depths [0..1]).

        Window-space depth is (NDC_z + 1) / 2. Vertices behind the camera have depth > 1.
        """
        if self._scene is None or self._last_image is None:
            return None, None
        rh, rw = self._last_image.shape[:2]
        cam  = self._scene.camera
        view = np.array(cam.get_view_matrix(),       dtype=np.float64)
        proj = np.array(cam.get_projection_matrix(), dtype=np.float64)
        vh   = np.hstack([vertices.astype(np.float64),
                          np.ones((len(vertices), 1))])
        clip = (proj @ view @ vh.T).T
        wc   = clip[:, 3:4]
        safe = np.where(np.abs(wc) < 1e-8, 1e-8, wc)
        ndc  = clip[:, :3] / safe
        sx   = (ndc[:, 0] + 1.0) * 0.5 * rw
        sy   = (1.0 - ndc[:, 1]) * 0.5 * rh
        wd   = (ndc[:, 2] + 1.0) * 0.5   # window-space depth matching render_depth()
        return np.stack([sx, sy], axis=1), wd.astype(np.float32)

    @property
    def last_image(self) -> np.ndarray | None:
        return self._last_image

    @property
    def size(self) -> tuple[int, int]:
        return self._w, self._h
