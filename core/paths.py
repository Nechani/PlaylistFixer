# core/paths.py
from __future__ import annotations
import sys
from pathlib import Path

def base_dir() -> Path:
    """
    Portable base dir:
    - If frozen (PyInstaller exe): folder containing the exe
    - Else (python run): folder containing app.py (project root)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # app.py is in project root; core is one level below
    return Path(__file__).resolve().parents[1]

def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def data_dir() -> Path:
    return ensure_dir(base_dir() / "data")

def reports_dir() -> Path:
    return ensure_dir(data_dir() / "reports")

def logs_dir() -> Path:
    return ensure_dir(base_dir() / "logs")

def index_path() -> Path:
    return data_dir() / "music_index.json"

def stats_path() -> Path:
    return data_dir() / "music_index.stats.json"

def settings_path() -> Path:
    return data_dir() / "settings.json"
