from __future__ import annotations
from pathlib import Path
import json
import zipfile
from datetime import datetime

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QFormLayout, QLineEdit, QApplication
)

from core.paths import logs_dir, reports_dir
from core.version import APP_VERSION

APP_NAME = "Playlist Fixer"
MAINTAINER = "Ne"
CONTACT_EMAIL = "plfixne@gmail.com"

class AboutDialog(QDialog):
    def __init__(self, app_data_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About / Help")
        self.setMinimumWidth(520)
        self._app_data_dir = app_data_dir

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

        links = QHBoxLayout()
        github_btn = QPushButton("Open GitHub")
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/Nechani"))
        )
        links.addWidget(github_btn)
        kofi_btn = QPushButton("Open Ko-fi")
        kofi_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ko-fi.com/nechani"))
        )
        links.addWidget(kofi_btn)
        root.addLayout(links)

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

    def _copy_email(self):
        QApplication.clipboard().setText(CONTACT_EMAIL)
        QMessageBox.information(self, "Copied", "Email copied to clipboard.")

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

            for settings_name in ("settings.json", "run_config.json"):
                settings_file = self._app_data_dir / settings_name
                if settings_file.exists():
                    z.write(settings_file, f"settings/{settings_name}")

            report_root = reports_dir()
            if report_root.exists():
                for p in report_root.rglob("*"):
                    if p.is_file():
                        z.write(p, f"reports/{p.relative_to(report_root).as_posix()}")

            log_root = logs_dir()
            if log_root.exists():
                for p in log_root.rglob("*"):
                    if p.is_file():
                        z.write(p, f"logs/{p.relative_to(log_root).as_posix()}")

        QMessageBox.information(self, "Exported", f"Bug bundle exported:\n{zip_path}")
