import os
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".tooth_annotator" / "config.json"

DEFAULT_CONFIG = {
    "input_dir": "",
    "output_dir": "",
    "last_index": 0,
    "brush_radius": 15,
    "snap_on_load": True,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


class FileManager:
    def __init__(self):
        self.files = []
        self.current_index = 0
        self.input_dir = ""
        self.output_dir = ""

    def load_folder(self, folder: str):
        self.input_dir = folder
        self.files = sorted(
            str(p) for p in Path(folder).glob("*.ply")
        )
        self.current_index = 0

    def set_index(self, idx: int):
        self.current_index = max(0, min(idx, len(self.files) - 1))

    @property
    def current_file(self) -> str:
        if not self.files:
            return ""
        return self.files[self.current_index]

    @property
    def current_filename(self) -> str:
        return os.path.basename(self.current_file)

    @property
    def count(self) -> int:
        return len(self.files)

    def has_next(self) -> bool:
        return self.current_index < len(self.files) - 1

    def has_prev(self) -> bool:
        return self.current_index > 0

    def output_path(self, filename: str) -> str:
        out = self.output_dir or self.input_dir
        os.makedirs(out, exist_ok=True)
        return os.path.join(out, filename)
