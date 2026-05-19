"""ArcballCamera — orbits around a target center (Blender-style middle-mouse)."""
from __future__ import annotations
import numpy as np


def _rot_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues' rotation matrix around a unit axis."""
    c, s = np.cos(angle), np.sin(angle)
    t = 1.0 - c
    x, y, z = axis
    return np.array([
        [t*x*x + c,   t*x*y - s*z, t*x*z + s*y],
        [t*x*y + s*z, t*y*y + c,   t*y*z - s*x],
        [t*x*z - s*y, t*y*z + s*x, t*z*z + c  ],
    ])


def _orthonormalize(m: np.ndarray) -> np.ndarray:
    """Gram-Schmidt on columns to prevent drift."""
    r = m[:, 0]; r /= np.linalg.norm(r)
    u = m[:, 1] - np.dot(m[:, 1], r) * r; u /= np.linalg.norm(u)
    b = np.cross(r, u)
    return np.column_stack([r, u, b])


class ArcballCamera:
    def __init__(self, center, distance: float):
        self.center   = np.array(center, dtype=np.float64)
        self.distance = float(distance)
        # Columns: right, up, back  (camera sits at center + distance*back)
        self._rot        = np.eye(3, dtype=np.float64)
        self._upside_down = False
        self.reset_view()

    def _set_from_angles(self, theta: float, phi: float):
        x = np.sin(phi) * np.cos(theta)
        y = np.cos(phi)
        z = np.sin(phi) * np.sin(theta)
        back  = np.array([x, y, z])
        world_up = np.array([0.0, 1.0, 0.0])
        right = np.cross(world_up, back)
        right /= np.linalg.norm(right)
        up = np.cross(back, right)
        self._rot = np.column_stack([right, up, back])
        self._upside_down = False

    def rotate(self, dx: float, dy: float, sx: float = 0.003, sy: float = 0.003):
        # Hysteresis on flip state to avoid jitter at the pole boundary
        cam_up_y = self._rot[1, 1]
        if self._upside_down and cam_up_y > 0.1:
            self._upside_down = False
        elif not self._upside_down and cam_up_y < -0.1:
            self._upside_down = True
        flip = -1.0 if self._upside_down else 1.0

        Ry = _rot_matrix(np.array([0.0, 1.0, 0.0]), flip * dx * sx)
        right = self._rot[:, 0].copy()
        Rv = _rot_matrix(right, -dy * sy)
        self._rot = _orthonormalize(Rv @ Ry @ self._rot)

    def pan(self, dx: float, dy: float, sensitivity: float = 0.001):
        right = self._rot[:, 0]
        up    = self._rot[:, 1]
        self.center += (-right * dx + up * dy) * self.distance * sensitivity

    def zoom(self, delta: float, sensitivity: float = 0.1):
        self.distance = max(0.01, self.distance * (1.0 - delta * sensitivity))

    def get_position(self) -> np.ndarray:
        return self.center + self.distance * self._rot[:, 2]

    def get_forward(self) -> np.ndarray:
        return -self._rot[:, 2]

    def set_front_view(self):
        self._set_from_angles(0.0, np.pi / 2)

    def set_right_view(self):
        self._set_from_angles(np.pi / 2, np.pi / 2)

    def set_top_view(self):
        self._set_from_angles(0.0, 0.05)

    def reset_view(self):
        self._set_from_angles(0.3, 1.2)
