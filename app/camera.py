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


class OrbitCamera:
    """Flexible Orbit camera — orbits around a target center without 'walls'.
    
    Uses an incremental rotation matrix to allow free rotation in any direction
    while staying locked to the model's center.
    """
    def __init__(self, center: np.ndarray | list, distance: float):
        self.center   = np.array(center, dtype=np.float64)
        self.distance = float(distance)
        # Columns: right, up, back
        self._rot = np.eye(3, dtype=np.float64)
        self.reset_view()

    def rotate(self, dx: float, dy: float, sx: float = 0.003, sy: float = 0.003):
        """Update orientation matrix. No clamping = no 'walls'."""
        # 1. Horizontal rotation around world Up [0, 1, 0]
        # This keeps the 'turntable' feel.
        Ry = _rot_matrix(np.array([0.0, 1.0, 0.0]), -dx * sx)
        
        # 2. Vertical rotation around camera Right vector (first column)
        right = self._rot[:, 0]
        Rx = _rot_matrix(right, -dy * sy)
        
        # Apply both and orthonormalize to prevent matrix drift
        self._rot = _orthonormalize(Rx @ Ry @ self._rot)

    def pan(self, dx: float, dy: float, sensitivity: float = 0.001):
        """Move the center point in the camera's local plane."""
        right = self._rot[:, 0]
        up    = self._rot[:, 1]
        self.center += (-right * dx + up * dy) * self.distance * sensitivity

    def zoom(self, delta: float, sensitivity: float = 0.1):
        """Adjust distance to center."""
        self.distance = max(0.01, self.distance * (1.0 - delta * sensitivity))

    def get_position(self) -> np.ndarray:
        """Camera is at center + distance * back_vector."""
        return self.center + self.distance * self._rot[:, 2]

    def get_up(self) -> np.ndarray:
        """Returns the camera's local Up vector."""
        return self._rot[:, 1]

    def _set_from_angles(self, theta: float, phi: float):
        """Helper to initialize matrix from spherical coordinates."""
        # This is only used for presets to get a clean starting matrix
        x = np.sin(phi) * np.sin(theta)
        y = np.cos(phi)
        z = np.sin(phi) * np.cos(theta)
        back = np.array([x, y, z])
        back /= np.linalg.norm(back)
        
        world_up = np.array([0.0, 1.0, 0.0])
        right = np.cross(world_up, back)
        rn = np.linalg.norm(right)
        if rn < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        else:
            right /= rn
        up = np.cross(back, right)
        self._rot = np.column_stack([right, up, back])

    def set_front_view(self):
        self._set_from_angles(0.0, np.pi / 2.0)

    def set_right_view(self):
        self._set_from_angles(-np.pi / 2.0, np.pi / 2.0)

    def set_top_view(self):
        self._set_from_angles(0.0, 0.01)

    def reset_view(self):
        self._set_from_angles(0.3, 1.2)
