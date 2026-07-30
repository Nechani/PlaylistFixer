from __future__ import annotations
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

APP_NAME = "Playlist Fixer"

def get_app_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "PlaylistFixer"
    return Path.home() / ".playlist_fixer"

def main():
    QCoreApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)

    app_data = get_app_data_dir()
    app_data.mkdir(parents=True, exist_ok=True)

    w = MainWindow(app_data)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
