from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import zipfile
from datetime import datetime

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QComboBox, QFormLayout, QLineEdit, QApplication
)

APP_NAME = "Playlist Fixer"
APP_VERSION = "v0.1.0"
MAINTAINER = "Ne"
CONTACT_EMAIL = "plfixne@gmail.com"

LANG_OPTIONS = [
    ("en", "English"),
    ("ja", "日本語"),
    ("zh_TW", "繁體中文"),
]

class AboutDialog(QDialog):
    languageChanged = Signal(str)

    def __init__(self, app_data_dir: Path, current_lang: str):
        super().__init__()
        self.setWindowTitle("About / Help")
        self.setMinimumWidth(520)
        self._app_data_dir = app_data_dir
        self._current_lang = current_lang
        self._selected_lang = current_lang

        root = QVBoxLayout(self)

        title = QLabel(f"{APP_NAME}")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        root.addWidget(QLabel(f"Version: {APP_VERSION}"))

        root.addSpacing(8)

        form = QFormLayout()
        maint = QLineEdit(MAINTAINER); maint.setReadOnly(True)
        email = QLineEdit(CONTACT_EMAIL); email.setReadOnly(True)
        form.addRow("Maintainer", maint)
        form.addRow("Contact", email)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy Email")
        copy_btn.clicked.connect(self._copy_email)
        btn_row.addWidget(copy_btn)

        open_mail = QPushButton("Open Mail Client")
        open_mail.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"mailto:{CONTACT_EMAIL}")))
        btn_row.addWidget(open_mail)
        root.addLayout(btn_row)

        root.addSpacing(10)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language"))
        self.lang_combo = QComboBox()
        for code, label in LANG_OPTIONS:
            self.lang_combo.addItem(label, code)
        idx = max(0, self.lang_combo.findData(current_lang))
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self.lang_combo, 1)
        root.addLayout(lang_row)

        hint = QLabel("Language takes effect after restart.")
        hint.setStyleSheet("color: #666;")
        root.addWidget(hint)

        root.addSpacing(10)

        export_btn = QPushButton("Export bug report bundle")
        export_btn.clicked.connect(self._export_bug_bundle)
        root.addWidget(export_btn)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def selected_language(self) -> str:
        return self._selected_lang

    def _copy_email(self):
        QApplication.clipboard().setText(CONTACT_EMAIL)
        QMessageBox.information(self, "Copied", "Email copied to clipboard.")

    def _on_lang_changed(self):
        code = self.lang_combo.currentData()
        if isinstance(code, str):
            self._selected_lang = code
            if code != self._current_lang:
                self.languageChanged.emit(code)

    def _export_bug_bundle(self):
        out_dir = self._app_data_dir / "bug_reports"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = out_dir / f"bug_bundle_{ts}.zip"

        app_info = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "maintainer": MAINTAINER,
            "contact": CONTACT_EMAIL,
            "timestamp": ts,
        }

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("app_info.json", json.dumps(app_info, ensure_ascii=False, indent=2))

            cfg = self._app_data_dir / "run_config.json"
            if cfg.exists():
                z.write(cfg, "run_config.json")

            reports_dir = self._app_data_dir / "reports"
            rr = reports_dir / "repair_report.csv"
            if rr.exists():
                z.write(rr, "reports/repair_report.csv")

            logs_dir = self._app_data_dir / "logs"
            if logs_dir.exists():
                for p in logs_dir.rglob("*"):
                    if p.is_file():
                        z.write(p, f"logs/{p.name}")

        QMessageBox.information(self, "Exported", f"Bug bundle exported:\n{zip_path}")
