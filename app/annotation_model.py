"""
AnnotationModel — domain model for a single annotated mesh.

Single Responsibility: holds geometry + per-vertex colors, owns undo/redo.
Uses collections.deque for O(1) append/evict (fixes list.pop(0) O(n) bug).
"""
from __future__ import annotations

from collections import deque
import numpy as np
import open3d as o3d

from app.config import PALETTE_RGB, UNDO_HISTORY_SIZE


class AnnotationModel:
    def __init__(self):
        self.vertices: np.ndarray | None = None  # Nx3 float32
        self.faces:    np.ndarray | None = None  # Mx3 int32
        self.colors:   np.ndarray | None = None  # Nx3 uint8

        self._undo: deque[np.ndarray] = deque(maxlen=UNDO_HISTORY_SIZE)
        self._redo: deque[np.ndarray] = deque(maxlen=UNDO_HISTORY_SIZE)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, vertices: np.ndarray, faces: np.ndarray, colors: np.ndarray):
        self.vertices = vertices
        self.faces    = faces
        self.colors   = colors
        self._undo.clear()
        self._redo.clear()

    @property
    def loaded(self) -> bool:
        return self.vertices is not None

    def make_o3d_mesh(self) -> o3d.geometry.TriangleMesh:
        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices      = o3d.utility.Vector3dVector(self.vertices.astype(np.float64))
        mesh.triangles     = o3d.utility.Vector3iVector(self.faces)
        mesh.vertex_colors = o3d.utility.Vector3dVector(
            self.colors.astype(np.float64) / 255.0)
        return mesh

    def apply_colors_to_mesh(self, mesh: o3d.geometry.TriangleMesh):
        mesh.vertex_colors = o3d.utility.Vector3dVector(
            self.colors.astype(np.float64) / 255.0)

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def save_snapshot(self):
        """Capture current colors before a new stroke for undo."""
        if self.colors is not None:
            self._undo.append(self.colors.copy())
            self._redo.clear()

    def paint_with_mask(self, mask: np.ndarray, color: np.ndarray) -> bool:
        """Apply color to vertices indicated by a precomputed boolean mask.
        Returns True if any vertex was changed."""
        if not self.loaded or not mask.any():
            return False
        self.colors = self.colors.copy()
        self.colors[mask] = color
        return True

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.colors.copy())
        self.colors = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.colors.copy())
        self.colors = self._redo.pop()
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
