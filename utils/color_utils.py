"""Color math utilities: LAB conversion, hue, palette snapping."""
from __future__ import annotations
import numpy as np
from app.config import PALETTE_RGB


def rgb_to_lab(colors_uint8: np.ndarray) -> np.ndarray:
    c      = colors_uint8.astype(np.float32) / 255.0
    linear = np.where(c > 0.04045,
                      ((c + 0.055) / 1.055) ** 2.4,
                      c / 12.92)
    M = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
    xyz  = linear @ M.T
    xyz /= np.array([0.95047, 1.00000, 1.08883])
    eps, kap = 0.008856, 903.3
    f = np.where(xyz > eps, xyz ** (1 / 3), (kap * xyz + 16) / 116)
    L = 116 * f[:, 1] - 16
    a = 500 * (f[:, 0] - f[:, 1])
    b = 200 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def snap_to_palette(colors: np.ndarray) -> np.ndarray:
    """Map every vertex color to the nearest palette entry by CIE-LAB distance.

    LAB distance is perceptually uniform, so palette entries with the same hue
    but different lightness/chroma (e.g. Cyan vs Teal) are always distinguished
    correctly. The old hue-only path for saturated colors caused same-hue pairs
    to collapse onto whichever entry appeared first in the palette.
    """
    colors_lab  = rgb_to_lab(colors)
    palette_lab = rgb_to_lab(PALETTE_RGB)
    dists  = np.sum((colors_lab[:, None] - palette_lab[None]) ** 2, axis=2)
    result = np.argmin(dists, axis=1)
    return PALETTE_RGB[result]


def colors_are_palette_exact(colors: np.ndarray) -> np.ndarray:
    """Return boolean mask — True where color exactly matches a palette entry."""
    # Broadcast comparison: (N,3) vs (P,3) → (N,P) → reduce over palette axis
    match = np.all(colors[:, None, :] == PALETTE_RGB[None, :, :], axis=2)
    return match.any(axis=1)
