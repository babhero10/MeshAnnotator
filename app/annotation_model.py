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

        self._adjacency: list | None = None   # per-vertex neighbor index arrays
        self._selection: np.ndarray | None = None  # bool[N]

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, vertices: np.ndarray, faces: np.ndarray, colors: np.ndarray):
        self.vertices = vertices
        self.faces    = faces
        self.colors   = colors
        self._undo.clear()
        self._redo.clear()
        self._adjacency = None
        self._selection = None
        self._build_adjacency()

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
    # Adjacency (built once per mesh load)
    # ------------------------------------------------------------------

    def _build_adjacency(self):
        if self.faces is None or self.vertices is None:
            return
        n = len(self.vertices)
        f = self.faces
        src = np.concatenate([f[:, 0], f[:, 1], f[:, 2],
                               f[:, 1], f[:, 2], f[:, 0]])
        dst = np.concatenate([f[:, 1], f[:, 2], f[:, 0],
                               f[:, 0], f[:, 1], f[:, 2]])
        order  = np.argsort(src, kind='stable')
        src_s  = src[order]
        dst_s  = dst[order]
        splits = np.searchsorted(src_s, np.arange(n + 1))
        self._adjacency = [dst_s[splits[i]:splits[i + 1]] for i in range(n)]

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    @property
    def selection(self) -> np.ndarray | None:
        return self._selection

    @property
    def has_selection(self) -> bool:
        return self._selection is not None and bool(self._selection.any())

    @property
    def selection_count(self) -> int:
        return int(self._selection.sum()) if self._selection is not None else 0

    def select_cluster(self, seed_idx: int, add: bool = False) -> int:
        """BFS flood-fill from seed_idx, selecting all connected vertices
        that share the same color.  Returns the new selection count."""
        if self._adjacency is None or self.colors is None:
            return 0
        seed_color = self.colors[seed_idx]
        n    = len(self.vertices)
        mask = (self._selection.copy()
                if (add and self._selection is not None)
                else np.zeros(n, dtype=bool))
        visited            = mask.copy()
        visited[seed_idx]  = True
        stack              = [seed_idx]
        while stack:
            v = stack.pop()
            if not np.array_equal(self.colors[v], seed_color):
                continue
            mask[v] = True
            for nb in self._adjacency[v]:
                if not visited[nb]:
                    visited[nb] = True
                    stack.append(nb)
        self._selection = mask
        return int(mask.sum())

    def expand_selection(self) -> int:
        """Grow selection by one vertex ring.  Returns new count."""
        if self._selection is None or self._adjacency is None:
            return 0
        sel_idx = np.where(self._selection)[0]
        if len(sel_idx) == 0:
            return 0
        neighbors   = np.concatenate([self._adjacency[v] for v in sel_idx])
        new_sel     = self._selection.copy()
        new_sel[neighbors] = True
        self._selection    = new_sel
        return int(new_sel.sum())

    def shrink_selection(self) -> int:
        """Remove boundary vertices (those with a non-selected neighbor).
        Returns new count."""
        if self._selection is None or self._adjacency is None:
            return 0
        new_sel = self._selection.copy()
        for v in np.where(self._selection)[0]:
            nbs = self._adjacency[v]
            if len(nbs) > 0 and not self._selection[nbs].all():
                new_sel[v] = False
        self._selection = new_sel
        return int(new_sel.sum())

    def clear_selection(self):
        self._selection = None

    def fill_selection(self, color: np.ndarray) -> bool:
        """Paint all selected vertices with color.  Returns True if anything changed."""
        if not self.has_selection:
            return False
        return self.paint_with_mask(self._selection, color)

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
