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


def rgb_to_hue(colors_uint8: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c     = colors_uint8.astype(np.float32) / 255.0
    maxc  = c.max(axis=1)
    minc  = c.min(axis=1)
    delta = maxc - minc
    sat   = np.where(maxc > 0, delta / maxc, 0.0)
    H     = np.zeros(len(c))
    mr = (maxc == c[:, 0]) & (delta > 0)
    mg = (maxc == c[:, 1]) & (delta > 0)
    mb = (maxc == c[:, 2]) & (delta > 0)
    H[mr] = (60 * ((c[mr, 1] - c[mr, 2]) / delta[mr])) % 360
    H[mg] = (60 * ((c[mg, 2] - c[mg, 0]) / delta[mg]) + 120) % 360
    H[mb] = (60 * ((c[mb, 0] - c[mb, 1]) / delta[mb]) + 240) % 360
    return H, sat


def snap_to_palette(colors: np.ndarray) -> np.ndarray:
    SAT_THRESHOLD = 0.25
    hues, sats = rgb_to_hue(colors)
    pal_hues, _ = rgb_to_hue(PALETTE_RGB)
    colors_lab  = rgb_to_lab(colors)
    palette_lab = rgb_to_lab(PALETTE_RGB)
    saturated   = sats >= SAT_THRESHOLD
    result      = np.zeros(len(colors), dtype=np.int32)
    if saturated.any():
        h     = hues[saturated]
        diffs = np.abs(h[:, None] - pal_hues[None, :]) % 360
        circ  = np.minimum(diffs, 360 - diffs)
        result[saturated] = np.argmin(circ, axis=1)
    if (~saturated).any():
        lab_dists = np.sum(
            (colors_lab[~saturated, None] - palette_lab[None]) ** 2, axis=2)
        result[~saturated] = np.argmin(lab_dists, axis=1)
    return PALETTE_RGB[result]


def colors_are_palette_exact(colors: np.ndarray) -> np.ndarray:
    """Return boolean mask — True where color exactly matches a palette entry."""
    # Broadcast comparison: (N,3) vs (P,3) → (N,P) → reduce over palette axis
    match = np.all(colors[:, None, :] == PALETTE_RGB[None, :, :], axis=2)
    return match.any(axis=1)
