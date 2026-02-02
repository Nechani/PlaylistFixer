from __future__ import annotations
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator, QLocale
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

APP_NAME = "Playlist Fixer"

def get_app_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "PlaylistFixer"
    return Path.home() / ".playlist_fixer"

def load_translator(app: QApplication, app_data_dir: Path) -> str:
    cfg = app_data_dir / "run_config.json"
    pref = None
    if cfg.exists():
        try:
            import json
            data = json.loads(cfg.read_text(encoding="utf-8"))
            pref = data.get("language")
        except Exception:
            pref = None

    if not pref:
        sysloc = QLocale.system().name()
        if sysloc.startswith("ja"):
            pref = "ja"
        elif sysloc.startswith("zh"):
            pref = "zh_TW"
        else:
            pref = "en"

    translator = QTranslator()
    qm = Path(__file__).parent / "resources" / "i18n" / f"{pref}.qm"
    if qm.exists() and translator.load(str(qm)):
        app.installTranslator(translator)
    return pref

def main():
    QCoreApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)

    app_data = get_app_data_dir()
    app_data.mkdir(parents=True, exist_ok=True)

    load_translator(app, app_data)

    w = MainWindow(app_data)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
