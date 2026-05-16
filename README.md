# Mesh Annotator

Desktop GUI for painting per-vertex colors on 3D mesh PLY files.  
Designed for dental mesh annotation but works on any PLY with vertex data.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![PyQt6](https://img.shields.io/badge/PyQt6-6.4%2B-green)
![Open3D](https://img.shields.io/badge/open3d-0.19%2B-orange)

---

## Features

- **Paint mode** — brush painting with pressure-sensitive tablet support (XP-Pen, Wacom)
- **Select mode** — one-click color-cluster selection with expand / shrink / fill
- **Multi-palette** — create, rename, and switch between unlimited custom palettes
- **Wireframe overlay** — depth-correct edge rendering with adjustable density
- **Undo / Redo** — 20-step history
- **Folder navigation** — step through all PLY files in a folder with prev/next/jump
- **Auto snap** — non-palette colors in loaded files are snapped to the nearest palette color on load
- **Verify script** — CLI tool to audit a dataset for off-palette vertices

---

## Requirements

- Python 3.10+
- See `requirements.txt`

---

## Installation

```bash
git clone <repo-url>
cd tooth_annotator
pip install -r requirements.txt
```

> **Conda users:** create an environment first:
> ```bash
> conda create -n annotator python=3.11
> conda activate annotator
> pip install -r requirements.txt
> ```

---

## Running

```bash
python main.py
```

On first launch a folder picker appears. Select any folder containing `.ply` files.  
The last-used folder and settings are persisted in `~/.tooth_annotator/config.json`.

### Wayland note

On Linux with Wayland, the app automatically runs under XCB (X11 compatibility layer) for reliable tablet input. Override with:

```bash
QT_QPA_PLATFORM=wayland python main.py
```

---

## Interface Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ File label   [Front][Right][Top][Reset]  [Wireframe] [Select]  │  ← Top bar
│                                          [density]  [◀][#][▶] │
├──────────────────────────────────────┬──────────────────────────┤
│                                      │  Palette name selector   │
│                                      │  ┌──┐┌──┐┌──┐┌──┐┌──┐  │
│          3D Viewport                 │  │  ││  ││  ││  ││  │  │
│                                      │  └──┘└──┘└──┘└──┘└──┘  │
│    Paint with brush or               │  ┌──┐┌──┐┌──┐┌──┐┌──┐  │
│    click to select clusters          │  │  ││  ││  ││  ││  │  │
│                                      │  └──┘└──┘└──┘└──┘└──┘  │
│                                      │  Brush radius slider     │
│                                      │  [Save]  [New] [Edit]   │
└──────────────────────────────────────┴──────────────────────────┤
│ Status bar                                              Mouse   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Keyboard Shortcuts

### Navigation

| Key | Action |
|-----|--------|
| `Middle-drag` | Rotate (orbit) |
| `Shift + Middle-drag` | Pan |
| `Ctrl + Middle-drag` | Zoom |
| `Scroll wheel` | Zoom |
| `F` | Frame / fit mesh to view |
| `Numpad 1` | Front view |
| `Numpad 3` | Right view |
| `Numpad 7` | Top view |
| `Numpad 0` | Reset view |

### Files

| Key | Action |
|-----|--------|
| `.` (period) | Next file |
| `,` (comma) | Previous file |
| `Ctrl+S` | Save current file |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |

### Paint Mode

| Key | Action |
|-----|--------|
| `Left-click / drag` | Paint vertices under brush |
| `1` – `9`, `0` | Select palette color 1–10 |
| `[` | Decrease brush radius |
| `]` | Increase brush radius |
| `W` | Toggle wireframe |

### Select Mode

| Key / Action | What it does |
|---|---|
| `S` | Toggle between Paint and Select mode |
| `Click` | BFS flood-fill — select the entire connected region of the same color under the cursor |
| `Shift + Click` | Add another cluster to the existing selection |
| `=` / `+` | Expand selection outward by one vertex ring |
| `-` | Shrink selection inward by one vertex ring (removes boundary vertices) |
| `Enter` | Fill all selected vertices with the active palette color (undo-aware) |
| `Esc` | Clear selection and return to Paint mode |

Selected vertices are highlighted in **cyan** in the viewport.

---

## Mouse & Tablet Input

| Input | Action |
|-------|--------|
| Left click / drag | Paint (Paint mode) or pick vertex (Select mode) |
| Middle-drag | Rotate |
| Shift + Middle-drag | Pan |
| Ctrl + Middle-drag | Zoom |
| Scroll wheel | Zoom |
| Tablet pen tip | Paint (pressure scales brush radius 50–100%) |
| Tablet eraser end | Erase (paints White regardless of active color) |
| Tablet barrel button | Navigate — drag to rotate; +Shift pan; +Ctrl zoom |

Both `MiddleButton` and `RightButton` barrel mappings are supported automatically (covers XP-Pen and Wacom without driver config).

---

## Palette System

The app ships with a default 10-color palette. You can create unlimited named palettes.

### Default palette

| Key | Name | Hex |
|-----|------|-----|
| `1` | Red | `#FF0000` |
| `2` | Blue | `#0000FF` |
| `3` | Green | `#00FF00` |
| `4` | Yellow | `#FFFF00` |
| `5` | Magenta | `#FF00FF` |
| `6` | Cyan | `#00E7E7` |
| `7` | Purple | `#A000FF` |
| `8` | Teal | `#008080` |
| `9` | Orange | `#FF9900` |
| `0` | White | `#FFFFFF` |

### Managing palettes

- **New** — clones the current palette under a new name, then opens the editor
- **Edit** — rename the palette and change individual color names and RGB values
- **Switch** — dropdown at the top of the palette panel

Palettes are stored in `~/.tooth_annotator/config.json` and persist across sessions.

---

## Wireframe

Toggle with `W` or the **Wireframe** button in the top bar.

The density slider controls what fraction of edges are shown (1–100%).  
At less than 100% only the sharpest edges (highest dihedral angle) are kept, giving a clean silhouette without inner noise on dense meshes.

---

## Config File

Location: `~/.tooth_annotator/config.json`

```json
{
  "input_dir":      "/path/to/ply/files",
  "output_dir":     "",
  "last_index":     0,
  "brush_radius":   15,
  "snap_on_load":   true,
  "wireframe":      false,
  "palettes":       [...],
  "active_palette": "Default"
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `input_dir` | `""` | Last-opened folder |
| `output_dir` | `""` | Where saves go; defaults to `input_dir` when empty |
| `last_index` | `0` | Which file in the folder was open last session |
| `brush_radius` | `15` | Brush size in pixels |
| `snap_on_load` | `true` | Snap non-palette colors to nearest palette color on load |
| `wireframe` | `false` | Wireframe visibility persisted across sessions |
| `palettes` | `[...]` | List of named palettes with colors |
| `active_palette` | `"Default"` | Name of the currently selected palette |

---

## Verify Script

Checks every PLY file in a folder for off-palette vertices:

```bash
python verify.py --folder /path/to/dataset/
```

Example output:

```
✅ 100_E.ply  — OK  (2 color(s): Red, White)
✅ 101_N.ply  — OK  (3 color(s): Blue, Green, White)
❌ 102_X.ply  — 341 non-palette vertices
     #FE0102  rgb(254,1,2)
     ...
============================================
✅ All 47 meshes have exact palette colors.
```

---

## Project Structure

```
tooth_annotator/
├── main.py                  # Entry point, Qt application class, tablet/mouse fix
├── verify.py                # CLI dataset verification tool
├── requirements.txt
├── app/
│   ├── annotator_window.py  # Main window, menu, toolbar, orchestration
│   ├── viewer.py            # 3D viewport widget, render loop, cursor
│   ├── annotation_model.py  # Mesh data, paint, undo/redo, selection, adjacency
│   ├── palette_panel.py     # Palette UI, color swatches, brush slider
│   ├── input_handler.py     # Tablet + mouse input state machine
│   ├── camera.py            # Arcball camera (rotate, pan, zoom)
│   ├── renderer.py          # Open3D offscreen renderer wrapper
│   ├── file_manager.py      # PLY file list, folder navigation, config I/O
│   └── config.py            # App-wide constants, palette arrays
└── utils/
    ├── ply_io.py            # PLY read / write (vertex + face + color)
    └── color_utils.py       # Palette snapping, exact-match checks
```
