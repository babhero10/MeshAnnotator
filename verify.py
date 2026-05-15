#!/usr/bin/env python3
"""Standalone verification script — checks all PLY files in a folder for exact palette colors."""

import sys
import os
import argparse
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from utils.ply_io import read_ply
from utils.color_utils import colors_are_palette_exact
from app.config import PALETTE_NAMES, PALETTE_RGB


def verify_folder(folder: str):
    ply_files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".ply"))
    if not ply_files:
        print(f"No PLY files found in {folder}")
        return

    all_ok = True
    for fname in ply_files:
        path = os.path.join(folder, fname)
        try:
            _, _, colors = read_ply(path)
        except Exception as ex:
            print(f"❌ {fname}  — ERROR: {ex}")
            all_ok = False
            continue

        bad_mask = ~colors_are_palette_exact(colors)
        n_bad = bad_mask.sum()
        if n_bad == 0:
            n_used = len(set(map(tuple, colors.tolist())))
            used_names = [
                PALETTE_NAMES[i]
                for i, p in enumerate(PALETTE_RGB)
                if any(np.all(colors == p, axis=1))
            ]
            print(f"✅ {fname}  — OK  ({n_used} color(s): {', '.join(used_names)})")
        else:
            bad_colors = colors[bad_mask]
            unique_bad = np.unique(bad_colors, axis=0)
            print(f"❌ {fname}  — {n_bad} non-palette vertices")
            for c in unique_bad[:5]:
                print(f"     #{c[0]:02X}{c[1]:02X}{c[2]:02X}  rgb({c[0]},{c[1]},{c[2]})")
            if len(unique_bad) > 5:
                print(f"     ... and {len(unique_bad) - 5} more unique colors")
            all_ok = False

    print()
    print("=" * 44)
    if all_ok:
        print(f"✅ All {len(ply_files)} meshes have exact palette colors.")
    else:
        n_bad_files = sum(
            1 for f in ply_files
            if not _check_file(os.path.join(folder, f))
        )
        print(f"⚠  {n_bad_files} / {len(ply_files)} files have non-palette colors.")


def _check_file(path: str) -> bool:
    try:
        _, _, colors = read_ply(path)
        return bool(colors_are_palette_exact(colors).all())
    except Exception:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify PLY palette colors")
    parser.add_argument("--folder", required=True, help="Folder containing PLY files")
    args = parser.parse_args()
    verify_folder(args.folder)
