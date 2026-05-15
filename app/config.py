"""Application-wide constants."""
from __future__ import annotations
import numpy as np

PALETTE: dict[str, tuple[int, int, int]] = {
    "Red":     (255,   0,   0),
    "Blue":    (  0,   0, 255),
    "Green":   (  0, 255,   0),
    "Yellow":  (255, 255,   0),
    "Magenta": (255,   0, 255),
    "Cyan":    (  0, 231, 231),
    "Purple":  (160,   0, 255),
    "Teal":    (  0, 128, 128),
    "Orange":  (255, 153,   0),
    "White":   (255, 255, 255),
}

PALETTE_NAMES: list[str]   = list(PALETTE.keys())
PALETTE_RGB:   np.ndarray  = np.array(list(PALETTE.values()), dtype=np.uint8)

UNDO_HISTORY_SIZE = 20

DEFAULT_BRUSH_RADIUS = 15
BRUSH_RADIUS_MIN     = 1
BRUSH_RADIUS_MAX     = 100
BRUSH_RADIUS_STEP    = 2

