# Tooth Annotator

Desktop GUI for annotating 3D tooth mesh PLY files with vertex colors from a fixed 10-color palette.

## Install

```bash
pip install open3d pyqt5 plyfile numpy
```

Or from the requirements file:

```bash
pip install -r requirements.txt
```

## Run

```bash
cd tooth_annotator
python main.py
```

On first launch a folder picker appears. Select the folder containing your PLY files.
The last folder is remembered in `~/.tooth_annotator/config.json`.

## Config

`~/.tooth_annotator/config.json`:

```json
{
  "input_dir":   "/path/to/input",
  "output_dir":  "/path/to/output",
  "last_index":  0,
  "brush_radius": 15,
  "snap_on_load": true
}
```

Set `output_dir` to write saves to a separate folder. Defaults to `input_dir`.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `.` | Next file |
| `,` | Previous file |
| `Ctrl+S` | Save current file |
| `1`–`9`, `0` | Select palette color 1–10 |
| `[` | Decrease brush radius |
| `]` | Increase brush radius |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |
| `F` | Frame / fit mesh to view |
| `Numpad 1` | Front view |
| `Numpad 3` | Right view |
| `Numpad 7` | Top view |
| `Numpad 0` | Reset view |

## Mouse / Tablet Navigation

| Input | Action |
|-------|--------|
| Middle mouse drag | Rotate (orbit) |
| Shift + Middle drag | Pan |
| Scroll wheel | Zoom |
| Left click / drag | Paint vertices |
| Tablet pen drag | Paint (pressure scales brush radius 50–100%) |
| Tablet eraser tip | Paint White regardless of active color |

## Palette

| # | Name | Hex |
|---|------|-----|
| 1 | Red | #FF0000 |
| 2 | Blue | #0000FF |
| 3 | Green | #00FF00 |
| 4 | Yellow | #FFFF00 |
| 5 | Magenta | #FF00FF |
| 6 | Cyan | #00E7E7 |
| 7 | Purple | #A000FF |
| 8 | Teal | #008080 |
| 9 | Orange | #FF9900 |
| 0 | White | #FFFFFF |

## Verify saved files

```bash
python verify.py --folder /path/to/dataset_final/
```

Output:
```
✅ 100_E.ply  — OK  (2 color(s): Red, White)
✅ 101_N.ply  — OK  (3 color(s): Blue, Green, White)
...
============================================
✅ All 47 meshes have exact palette colors.
```
