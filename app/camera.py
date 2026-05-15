"""ArcballCamera — orbits around a target center (Blender-style middle-mouse)."""
from __future__ import annotations
import numpy as np


class ArcballCamera:
    def __init__(self, center, distance: float):
        self.center   = np.array(center, dtype=np.float64)
        self.distance = float(distance)
        self.theta    = 0.0   # horizontal angle (radians)
        self.phi      = 1.0   # vertical angle (radians)

    def rotate(self, dx: float, dy: float, sensitivity: float = 0.005):
        self.theta += dx * sensitivity
        self.phi    = float(np.clip(self.phi - dy * sensitivity, 0.05, np.pi - 0.05))

    def pan(self, dx: float, dy: float, sensitivity: float = 0.001):
        fwd   = self.get_forward()
        right = np.cross(fwd, [0, 1, 0])
        norm  = np.linalg.norm(right)
        right = right / norm if norm > 1e-6 else np.array([1.0, 0.0, 0.0])
        up    = np.cross(right, fwd)
        self.center += (-right * dx + up * dy) * self.distance * sensitivity

    def zoom(self, delta: float, sensitivity: float = 0.1):
        self.distance = max(0.01, self.distance * (1.0 - delta * sensitivity))

    def get_position(self) -> np.ndarray:
        x = self.distance * np.sin(self.phi) * np.cos(self.theta)
        y = self.distance * np.cos(self.phi)
        z = self.distance * np.sin(self.phi) * np.sin(self.theta)
        return self.center + np.array([x, y, z])

    def get_forward(self) -> np.ndarray:
        pos  = self.get_position()
        diff = self.center - pos
        norm = np.linalg.norm(diff)
        return diff / norm if norm > 1e-10 else np.array([0.0, 0.0, -1.0])

    def set_front_view(self):
        self.theta, self.phi = 0.0, np.pi / 2

    def set_right_view(self):
        self.theta, self.phi = np.pi / 2, np.pi / 2

    def set_top_view(self):
        self.theta, self.phi = 0.0, 0.05

    def reset_view(self):
        self.theta, self.phi = 0.3, 1.2
