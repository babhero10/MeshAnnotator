"""PLY read/write utilities. Colors stored as exact uint8 — no float conversion."""
from __future__ import annotations
import numpy as np
from plyfile import PlyData, PlyElement


def read_ply(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (vertices Nx3 float32, faces Mx3 int32, colors Nx3 uint8)."""
    plydata = PlyData.read(path)
    v = plydata["vertex"]
    vertices = np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float32)

    if all(c in v.data.dtype.names for c in ("red", "green", "blue")):
        colors = np.stack([v["red"], v["green"], v["blue"]], axis=1).astype(np.uint8)
    else:
        colors = np.full((len(vertices), 3), 255, dtype=np.uint8)

    faces = np.vstack(plydata["face"]["vertex_indices"]).astype(np.int32)
    return vertices, faces, colors


def write_ply(path: str, vertices: np.ndarray,
              faces: np.ndarray, colors: np.ndarray):
    """Write PLY with exact uint8 colors."""
    vertex_data = np.zeros(len(vertices), dtype=[
        ("x", "f4"), ("y", "f4"), ("z", "f4"),
        ("red", "u1"), ("green", "u1"), ("blue", "u1"),
    ])
    vertex_data["x"]     = vertices[:, 0]
    vertex_data["y"]     = vertices[:, 1]
    vertex_data["z"]     = vertices[:, 2]
    vertex_data["red"]   = colors[:, 0]
    vertex_data["green"] = colors[:, 1]
    vertex_data["blue"]  = colors[:, 2]

    faces_i32 = faces.astype(np.int32)
    face_data = np.empty(len(faces_i32), dtype=[("vertex_indices", "O")])
    face_data["vertex_indices"] = list(faces_i32)

    PlyData([
        PlyElement.describe(vertex_data, "vertex"),
        PlyElement.describe(face_data,   "face"),
    ], text=False).write(path)
