from __future__ import annotations

import os
import re
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QObject, Slot, Qt
from openpyxl import load_workbook

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QMessageBox, QCheckBox, QComboBox,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QGroupBox,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QLineEdit, QDialog, QTextBrowser, QSplitter
)

from core.runner import TaskRunner, TaskResult
from core.paths import index_path, reports_dir, settings_path, stats_path


class Worker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, func, kwargs):
        super().__init__()
        self.func = func
        self.kwargs = kwargs
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @Slot()
    def run(self):
        try:
            result = self.func(
                progress=self.progress.emit,
                cancel_flag=lambda: self._cancelled,
                **self.kwargs
            )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, app_data=None):
        super().__init__()
        self.app_data = app_data
        self.setWindowTitle("Playlist Fixer v2.1.8")

        self.runner = TaskRunner()

        self.music_roots: list[dict] = []
        self.playlists: list[Path] = []

        self.index_path = index_path()
        self.reports_path = reports_dir()

        # rows currently displayed (depends on view mode)
        self._ambiguous_rows: list[dict] = []
        self._failed_rows: list[dict] = []
        # master rows (unfiltered)
        self._ambiguous_rows_all: list[dict] = []
        self._failed_rows_all: list[dict] = []


        # maps for quick lookup: "{pl_key}::{row_id}"
        self._amb_by_id: dict[str, dict] = {}
        self._fail_by_id: dict[str, dict] = {}

        # selections keyed by stable pl_key -> {row_index(str): chosen_path}
        self._selections_by_key: dict[str, dict[str, str]] = {}

        # cache report rows per playlist key (raw report csv rows)
        self._report_rows_by_key: dict[str, list[dict]] = {}
        self._session_repaired_keys: set[str] = set()
        
        self._saved_keys: set[str] = set()
        self._persisted_progress_keys: set[str] = set()

        self._active_target: str | None = None   # "AMBIGUOUS" | "FAILED"
        self._active_pl_key: str | None = None
        self._active_row_id: str | None = None

        self._busy = False
        self._last_progress_msg = ""

        self.thread: QThread | None = None
        self.worker: Worker | None = None

        self._pending_save_keys: list[str] = []
        self._last_action: str | None = None

        # view mode: "UNRESOLVED" | "RESOLVED"
        self._view_mode: str = "UNRESOLVED"

        self._build_ui()
        self._load_music_roots()
        self._prune_saved_roots_against_index()
        self._refresh_music_roots_ui()

    # ---------- persistence ----------
    def _selection_file_for_key(self, pl_key: str) -> Path:
        return self.reports_path / f"selections_{pl_key}.json"

    def _load_selections_for_key(self, pl_key: str) -> dict[str, str]:
        p = self._selection_file_for_key(pl_key)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save_selections_for_key(self, pl_key: str, sel: dict[str, str]) -> None:
        p = self._selection_file_for_key(pl_key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Could not save selections:\n{p}\n\n{e}")

    def _progress_file_for_key(self, pl_key: str) -> Path:
        return self.reports_path / f"progress_{pl_key}.json"

    @staticmethod
    def _normalized_playlist_path(path: Path) -> str:
        try:
            return str(Path(path).resolve(strict=False)).casefold()
        except Exception:
            return str(Path(path).absolute()).casefold()

    def _has_saved_progress(self, pl_key: str, playlist: Path) -> bool:
        """Return True only for the exact saved output playlist.

        Progress files may share a canonical name with the original playlist, but
        the marker records the exact fixed playlist path that was saved. This
        prevents an untouched source playlist with the same base name from
        inheriting the fixed playlist's repair state.
        """
        progress = self._progress_file_for_key(pl_key)
        report = self.reports_path / f"repair_report_{pl_key}.csv"
        if not (progress.exists() and report.exists()):
            return False
        try:
            data = json.loads(progress.read_text(encoding="utf-8"))
            saved_path = data.get("saved_playlist") or data.get("source_playlist")
            if not saved_path:
                return False
            return self._normalized_playlist_path(Path(saved_path)) == self._normalized_playlist_path(playlist)
        except Exception:
            return False

    def _write_progress_marker(self, pl_key: str, saved_playlist: Path, source_playlist: Path) -> None:
        p = self._progress_file_for_key(pl_key)
        data = {
            "version": 2,
            "playlist_key": pl_key,
            "saved_playlist": str(saved_playlist),
            "source_playlist": str(source_playlist),
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _session_report_for(self, playlist: Path) -> Path:
        return self.runner.session_report_path_for(self.reports_path, playlist)

    def _settings_file(self) -> Path:
        # Keep user preferences outside the extracted program folder so an
        # update/re-extract does not erase saved Music Roots.
        if self.app_data:
            return Path(self.app_data) / "settings.json"
        return settings_path()

    def _load_settings(self) -> dict:
        p = self._settings_file()

        # One-time migration from builds that stored settings beside app.py.
        legacy = settings_path()
        if not p.exists() and legacy.exists() and legacy != p:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass

        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_settings(self, data: dict) -> None:
        p = self._settings_file()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Settings not saved", f"Could not save settings to:\n{p}\n\n{e}")


    def _load_music_roots(self) -> None:
        settings = self._load_settings()
        raw = settings.get("music_roots", [])
        roots: list[dict] = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str):
                    roots.append({"path": entry, "enabled": True, "imported": True})
                elif isinstance(entry, dict) and entry.get("path"):
                    roots.append({
                        "path": str(entry["path"]),
                        "enabled": bool(entry.get("enabled", True)),
                        # Anything already persisted by an older build is treated as
                        # imported initially, then verified against index stats below.
                        "imported": bool(entry.get("imported", True)),
                    })
        self.music_roots = roots

    def _indexed_root_paths(self) -> set[str]:
        p = stats_path()
        if not p.exists():
            return set()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            roots = data.get("roots", []) if isinstance(data, dict) else []
            return {str(Path(x)) for x in roots if x}
        except Exception:
            return set()

    def _prune_saved_roots_against_index(self) -> None:
        """Remove stale roots that were persisted but never made it into an index.

        Music Roots represent folders actually imported into the music database,
        not merely folders that were once selected in a file dialog.
        """
        indexed = self._indexed_root_paths()
        before = len(self.music_roots)
        if indexed:
            self.music_roots = [
                r for r in self.music_roots
                if str(Path(r.get("path", ""))) in indexed
            ]
        else:
            # No usable index means there are no confirmed imported roots yet.
            self.music_roots = []
        if len(self.music_roots) != before:
            self._save_music_roots()

    def _save_music_roots(self) -> None:
        settings = self._load_settings()
        # Pending folders are session-only. Persist only folders that have
        # successfully contributed at least one track to an index.
        settings["music_roots"] = [
            {"path": r["path"], "enabled": bool(r.get("enabled", True)), "imported": True}
            for r in self.music_roots if r.get("imported", False)
        ]
        self._save_settings(settings)

    def _enabled_music_roots(self) -> list[Path]:
        return [Path(r["path"]) for r in self.music_roots if r.get("enabled", True)]

    def on_music_root_item_changed(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.UserRole)
        if not raw:
            return
        for entry in self.music_roots:
            if entry.get("path") == str(raw):
                entry["enabled"] = item.checkState() == Qt.Checked
                break
        self._save_music_roots()
        self._update_music_roots_label()

    def _update_music_roots_label(self) -> None:
        enabled = sum(1 for r in self.music_roots if r.get("enabled", True))
        imported = sum(1 for r in self.music_roots if r.get("imported", False))
        pending = len(self.music_roots) - imported
        suffix = f" / Pending: {pending}" if pending else ""
        self.lbl_music_roots.setText(f"Enabled: {enabled} / Imported: {imported}{suffix}")

    # ---------- tiny helpers ----------
    def _is_exported_playlist(self, pl: Path) -> bool:
        stem = pl.stem.lower()
        return (
            stem.startswith("fixed_")
            or stem.startswith("draft_fixed_")
            or stem.endswith("_selected")
            or "_selected" in stem
        )

    def _show_import_hint_once(self) -> None:
        settings = self._load_settings()
        if settings.get("hide_import_hint", False):
            return

        chk = QCheckBox("Don't show this again")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Imported")
        box.setText("Playlists imported. Songs are listed as Not repaired until you run Repair (Safe).")
        box.setCheckBox(chk)
        box.exec()

        if chk.isChecked():
            settings["hide_import_hint"] = True
            self._save_settings(settings)

    def _safe_str(self, v) -> str:
        try:
            return (str(v) if v is not None else "").strip()
        except Exception:
            return ""

    # ---------- UI helpers ----------
    def _set_busy(self, busy: bool, message: str | None = None):
        self._busy = busy

        buttons = [
            getattr(self, "btn_add_music", None),
            getattr(self, "btn_remove_music", None),
            getattr(self, "btn_clear_music", None),
            getattr(self, "btn_scan", None),
            getattr(self, "btn_rescan", None),
            getattr(self, "btn_import_pl", None),
            getattr(self, "btn_repair_safe", None),
            getattr(self, "btn_open_reports", None),
            getattr(self, "btn_browse_choice", None),
            getattr(self, "btn_apply_choice", None),
            getattr(self, "btn_save_fixed", None),
        ]

        for b in buttons:
            if b is None:
                continue
            try:
                b.setEnabled(not busy)
            except Exception:
                pass

        if getattr(self, "btn_open_reports", None) is not None:
            self.btn_open_reports.setEnabled(True)

        if message is not None and getattr(self, "status_label", None) is not None:
            self.status_label.setText(message)

    def _setup_table(self, table: QTableWidget):
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # =========================
        # Music roots panel
        # =========================
        roots_box = QGroupBox("Music Roots (checked = Repair scope)")
        roots_l = QVBoxLayout(roots_box)

        roots_btn_row = QHBoxLayout()
        self.btn_add_music = QPushButton("Add Music Folder")
        self.btn_remove_music = QPushButton("Remove Selected")
        self.btn_clear_music = QPushButton("Clear All")
        roots_btn_row.addWidget(self.btn_add_music, 2)
        roots_btn_row.addWidget(self.btn_remove_music, 1)
        roots_btn_row.addWidget(self.btn_clear_music, 1)
        roots_l.addLayout(roots_btn_row)

        self.lst_music_roots = QListWidget()
        self.lst_music_roots.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst_music_roots.itemChanged.connect(self.on_music_root_item_changed)
        roots_l.addWidget(self.lst_music_roots)

        self.lbl_music_roots = QLabel("Enabled: 0 / Imported: 0")
        self.lbl_music_roots.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        roots_l.addWidget(self.lbl_music_roots)

        # =========================
        # Fixed controls area (rows)
        # =========================
        row_scan = QHBoxLayout()
        self.btn_scan = QPushButton("Scan New Folders")
        self.btn_rescan = QPushButton("Rescan Selected")
        row_scan.addWidget(self.btn_scan)
        row_scan.addWidget(self.btn_rescan)

        row2 = QHBoxLayout()
        self.btn_import_pl = QPushButton("Import Playlist(s)")
        self.btn_repair_safe = QPushButton("Repair (Safe)")
        self.btn_open_reports = QPushButton("Open Reports Folder")
        row2.addWidget(self.btn_import_pl)
        row2.addWidget(self.btn_repair_safe)
        row2.addWidget(self.btn_open_reports)

        self.status_label = QLabel("Idle")
        self.scan_count_label = QLabel("Indexed: -")
        self.scan_count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.scan_count_label, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)

        search_row = QHBoxLayout()
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("Search song / filename / path (A or B)…")
        self.btn_clear_search = QPushButton("Clear")
        search_row.addWidget(QLabel("Search:"), 0)
        search_row.addWidget(self.edt_search, 1)
        search_row.addWidget(self.btn_clear_search, 0)

        controls = QHBoxLayout()
        self.lbl_target = QLabel("Target: (none)")

        self.cmb_view = QComboBox()
        self.cmb_view.addItems(["Unresolved", "Resolved"])
        self.cmb_view.setCurrentIndex(0)

        self.btn_browse_choice = QPushButton("Browse…")
        self.btn_apply_choice = QPushButton("Apply")
        self.btn_save_fixed = QPushButton("Save Fixed Playlist")

        controls.addWidget(self.lbl_target, 4)
        controls.addWidget(QLabel("View:"), 0)
        controls.addWidget(self.cmb_view, 0)
        controls.addWidget(self.btn_browse_choice, 1)
        controls.addWidget(self.btn_apply_choice, 1)
        controls.addWidget(self.btn_save_fixed, 2)

        # =========================
        # Panes (Ambiguous / Candidates / Failed)
        # =========================
        boxA = QGroupBox("UNRESOLVED / AMBIGUOUS (select row → choose candidate → Apply → Save)")
        boxA_l = QVBoxLayout(boxA)
        self.tbl_amb = QTableWidget(0, 4)
        self.tbl_amb.setHorizontalHeaderLabels(["Playlist", "EXTINF", "Original Path", "Notes"])
        self.tbl_amb.horizontalHeader().setStretchLastSection(True)
        self._setup_table(self.tbl_amb)
        boxA_l.addWidget(self.tbl_amb)

        # Candidates pane (獨立出來)
        boxC = QGroupBox("Candidates / Picked file")
        boxC_l = QVBoxLayout(boxC)
        self.lst_candidates = QListWidget()
        boxC_l.addWidget(self.lst_candidates)

        boxF = QGroupBox("FAILED (select row → Browse → Apply → Save)")
        boxF_l = QVBoxLayout(boxF)
        self.tbl_fail = QTableWidget(0, 4)
        self.tbl_fail.setHorizontalHeaderLabels(["Playlist", "EXTINF", "Original Path", "Notes"])
        self.tbl_fail.horizontalHeader().setStretchLastSection(True)
        self._setup_table(self.tbl_fail)
        boxF_l.addWidget(self.tbl_fail)

        # Inner splitter: A / C / F
        inner_splitter = QSplitter(Qt.Vertical)
        inner_splitter.addWidget(boxA)
        inner_splitter.addWidget(boxC)
        inner_splitter.addWidget(boxF)

        # 讓 table 區域吃更多高度
        inner_splitter.setStretchFactor(0, 5)
        inner_splitter.setStretchFactor(1, 2)
        inner_splitter.setStretchFactor(2, 4)

        # =========================
        # Lower container: fixed rows + inner splitter
        # =========================
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addLayout(row_scan)
        lower_layout.addLayout(row2)
        lower_layout.addLayout(status_row)
        lower_layout.addWidget(self.progress)
        lower_layout.addLayout(search_row)
        lower_layout.addLayout(controls)
        lower_layout.addWidget(inner_splitter, 1)

        # =========================
        # Outer splitter: Roots vs Lower
        # =========================
        outer_splitter = QSplitter(Qt.Vertical)
        outer_splitter.addWidget(roots_box)
        outer_splitter.addWidget(lower)
        outer_splitter.setStretchFactor(0, 1)
        outer_splitter.setStretchFactor(1, 9)

        # Optional: reasonable default sizes (small screen friendly)
        outer_splitter.setSizes([160, 900])
        inner_splitter.setSizes([420, 220, 360])

        layout.addWidget(outer_splitter, 1)

        # =========================
        # Info button in status bar (右下角)
        # =========================
        self.lbl_build = QLabel("v2.1.8")
        self.lbl_build.setToolTip("Build identifier. If this is not visible, an older copy is running.")
        self.statusBar().addPermanentWidget(self.lbl_build)

        self.btn_info = QPushButton("ⓘ")
        self.btn_info.setToolTip("About / Links")
        self.btn_info.setFixedWidth(32)
        self.statusBar().addPermanentWidget(self.btn_info)

        # =========================
        # Signals
        # =========================
        self.btn_add_music.clicked.connect(self.on_add_music)
        self.btn_remove_music.clicked.connect(self.on_remove_music_roots)
        self.btn_clear_music.clicked.connect(self.on_clear_music_roots)

        self.btn_scan.clicked.connect(self.on_scan_index)
        self.btn_rescan.clicked.connect(self.on_rescan_selected)
        self.btn_import_pl.clicked.connect(self.on_import_playlists)
        self.btn_repair_safe.clicked.connect(self.on_repair_safe)
        self.btn_open_reports.clicked.connect(self.on_open_reports)

        self.tbl_amb.itemSelectionChanged.connect(self.on_ambiguous_selected)
        self.tbl_fail.itemSelectionChanged.connect(self.on_failed_selected)

        self.btn_apply_choice.clicked.connect(self.on_apply_choice)
        self.btn_browse_choice.clicked.connect(self.on_browse_choice)
        self.btn_save_fixed.clicked.connect(self.on_save_fixed)

        self.cmb_view.currentIndexChanged.connect(self.on_view_mode_changed)

        self.edt_search.textChanged.connect(self.on_search_changed)
        self.btn_clear_search.clicked.connect(lambda: self.edt_search.setText(""))

        self.btn_info.clicked.connect(self.on_about)

    def _refresh_music_roots_ui(self):
        self.lst_music_roots.blockSignals(True)
        self.lst_music_roots.clear()
        for entry in self.music_roots:
            path = str(entry.get("path", ""))
            available = Path(path).exists()
            imported = bool(entry.get("imported", False))
            if not imported:
                suffix = "  [Pending scan]"
            elif not available:
                suffix = "  [Unavailable]"
            else:
                suffix = ""
            it = QListWidgetItem(path + suffix)
            it.setData(Qt.UserRole, path)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if entry.get("enabled", True) else Qt.Unchecked)
            if not imported:
                it.setToolTip("This folder is temporary until Scan New Folders successfully indexes at least one track.")
            elif not available:
                it.setToolTip("This imported folder is currently unavailable.")
            self.lst_music_roots.addItem(it)
        self.lst_music_roots.blockSignals(False)
        self._update_music_roots_label()

    def _read_playlist_text(self, playlist: Path) -> str:
        """Read text playlists without silently turning a wrong encoding into mojibake."""
        raw = playlist.read_bytes()
        encodings = ("utf-8-sig", "utf-8", "utf-16", "cp950", "big5", "cp1252")
        for encoding in encodings:
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        # Last resort: keep the file importable while clearly replacing only undecodable bytes.
        return raw.decode("utf-8", errors="replace")

    def _parse_xlsx_entries(self, playlist: Path) -> list[dict]:
        """Parse a Roon XLSX export for the pre-repair preview."""
        wb = load_workbook(playlist, read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                return []
            header_map = {str(h).strip().lower(): i for i, h in enumerate(header) if h is not None}
            path_idx = header_map.get("path")
            if path_idx is None:
                raise ValueError("XLSX missing 'Path' column")

            # Use Roon metadata when present; otherwise fall back to the filename.
            title_idx = next((header_map[k] for k in ("title", "track title", "name") if k in header_map), None)
            artist_idx = next((header_map[k] for k in ("artist", "track artist", "artists") if k in header_map), None)
            entries: list[dict] = []
            for row in rows:
                if not row:
                    continue
                value = row[path_idx] if path_idx < len(row) else None
                original_path = str(value).strip() if value is not None else ""
                if not original_path:
                    continue
                title = str(row[title_idx]).strip() if title_idx is not None and title_idx < len(row) and row[title_idx] is not None else ""
                artist = str(row[artist_idx]).strip() if artist_idx is not None and artist_idx < len(row) and row[artist_idx] is not None else ""
                display = " - ".join(part for part in (artist, title) if part) or Path(original_path).stem
                entries.append({
                    "playlist": str(playlist),
                    "pl_key": self.runner.canonical_key(playlist),
                    "row_index": str(len(entries)),
                    "extinf_display": display,
                    "original_path": original_path,
                    "notes": "[NOT REPAIRED]",
                    "candidates": [],
                })
            return entries
        finally:
            wb.close()

    def _parse_playlist_entries(self, playlist: Path) -> list[dict]:
        if playlist.suffix.lower() == ".xlsx":
            return self._parse_xlsx_entries(playlist)

        text = self._read_playlist_text(playlist)
        lines = text.splitlines()
        entries: list[dict] = []
        pending_extinf = ""
        for line in lines:
            stripped = line.strip().lstrip("\ufeff")
            if not stripped:
                continue
            if stripped.upper().startswith("#EXTINF"):
                pending_extinf = stripped
                continue
            if stripped.startswith("#"):
                continue
            display = pending_extinf
            if "," in pending_extinf:
                display = pending_extinf.split(",", 1)[1].strip()
            entries.append({
                "playlist": str(playlist),
                "pl_key": self.runner.canonical_key(playlist),
                "row_index": str(len(entries)),
                "extinf_display": display or Path(stripped).stem,
                "original_path": stripped,
                "notes": "[NOT REPAIRED]",
                "candidates": [],
            })
            pending_extinf = ""
        return entries

    # ---------- view building ----------
    def _reload_reports_cache(self) -> None:
        """Load only active session reports or explicitly saved progress.

        Repair output is provisional until Save. A provisional report must not
        reappear after importing another playlist or restarting the app.
        """
        self._report_rows_by_key = {}
        self._persisted_progress_keys = set()
        self.reports_path.mkdir(parents=True, exist_ok=True)

        for pl in self.playlists:
            pl_key = self.runner.canonical_key(pl)
            report_csv = None
            if pl_key in self._session_repaired_keys:
                candidate = self._session_report_for(pl)
                if candidate.exists():
                    report_csv = candidate
            elif self._has_saved_progress(pl_key, pl):
                candidate = self.runner.report_path_for(self.reports_path, pl)
                if candidate.exists():
                    report_csv = candidate
                    self._persisted_progress_keys.add(pl_key)

            if report_csv is None:
                continue
            rows = self.runner._read_report_rows(report_csv)
            if rows:
                # Path-only M3U and Roon XLSX reports do not contain EXTINF text.
                # Reuse the imported playlist preview by row index so Resolved still
                # identifies each song instead of showing an empty title column.
                try:
                    preview = {str(r.get("row_index", "")): r for r in self._parse_playlist_entries(pl)}
                except Exception:
                    preview = {}
                for rr in rows:
                    idx = str(rr.get("row_index", rr.get("_i", "")))
                    src = preview.get(idx, {})
                    if not self._safe_str(rr.get("extinf_display")):
                        rr["extinf_display"] = self._safe_str(src.get("extinf_display"))
                    if not self._safe_str(rr.get("original_path")):
                        rr["original_path"] = self._safe_str(src.get("original_path"))
                self._report_rows_by_key[pl_key] = rows

    def _build_unresolved_rows(self) -> tuple[list[dict], list[dict]]:
        amb_all: list[dict] = []
        fail_all: list[dict] = []

        for pl in self.playlists:
            pl_key = self.runner.canonical_key(pl)

            is_exported = self._is_exported_playlist(pl)
            has_saved_progress = pl_key in self._persisted_progress_keys

            report_rows = self._report_rows_by_key.get(pl_key, [])

            # Before Repair, always show the imported file itself when there is no usable
            # report in this session. This also covers fixed_*_selected.m3u files imported
            # as a new input instead of treating them as invisible historical progress.
            if pl_key not in self._session_repaired_keys and not has_saved_progress:
                amb_all.extend(self._parse_playlist_entries(pl))
                continue

            if not report_rows:
                continue

            # --- selections sources ---
            # disk_sel: 以前 Save 過、寫在磁碟上的 selections（永遠視為已完成）
            # mem_sel : 本次 session Apply 但尚未 Save 的 selections
            disk_sel: dict[str, str] = {}
            if has_saved_progress:
                disk_sel = self._load_selections_for_key(pl_key) or {}

            mem_sel: dict[str, str] = self._selections_by_key.get(pl_key, {}) or {}

            # merged view for lookup
            merged_sel = {**disk_sel, **mem_sel}

            amb, fail = self.runner._classify_for_ui(report_rows, pl)

            # ✅ A) disk_sel：永遠 hide（因為它代表「上次已存檔」）
            if disk_sel:
                amb = [r for r in amb if str(r.get("row_index")) not in disk_sel]
                fail = [r for r in fail if str(r.get("row_index")) not in disk_sel]

            # ✅ B) mem_sel：未 Save -> 不 hide，只打標；Save 後 -> hide
            if mem_sel:
                if pl_key in self._saved_keys:
                    # 已 Save：把本次 mem_sel 也 hide
                    amb = [r for r in amb if str(r.get("row_index")) not in mem_sel]
                    fail = [r for r in fail if str(r.get("row_index")) not in mem_sel]
                else:
                    # 未 Save：保留列 + notes 打標
                    for rr in amb:
                        k = str(rr.get("row_index"))
                        if k in mem_sel:
                            rr["notes"] = f"[SELECTED] {mem_sel[k]}"
                    for rr in fail:
                        k = str(rr.get("row_index"))
                        if k in mem_sel:
                            rr["notes"] = f"[RESCUED] {mem_sel[k]}"

            # ✅ 把 merged 保存回記憶體（避免你匯入 exported 後，disk_sel 覆蓋掉本次 Apply 的 mem_sel）
            #    但注意：原始歌單你原本的設計是「不吃 disk」，所以這裡只有 exported 才會 merge disk
            if has_saved_progress and merged_sel:
                self._selections_by_key[pl_key] = merged_sel

            amb_all.extend(amb)
            fail_all.extend(fail)

        return amb_all, fail_all

    def _build_resolved_rows(self) -> tuple[list[dict], list[dict]]:
        """
        Show resolved rows (Auto + Manual).
        Notes column will show [AUTO]/[MANUAL] after_path + status.
        """
        amb_rows: list[dict] = []
        fail_rows: list[dict] = []

        # local status sets (aligned with runner logic)
        AMBIG_STATUSES = {"AMBIGUOUS", "MULTI_MATCH", "MULTIPLE_MATCH", "CONFLICT", "DUPLICATE"}
        FAIL_STATUSES = {"FAILED", "NOT_FOUND", "MISSING", "ERROR"}
        RESOLVED_STATUSES = {"KEPT", "REPAIRED", "FIXED", "OK", "DONE", "SUCCESS", "RESOLVED"}

        def pick_written_path(rr: dict) -> str:
            # strict whitelist: only these keys can be treated as "final written path"
            FINAL_KEYS = (
                "written_path", "written",
                "final_path", "final",
                "resolved_path", "resolved",
                "picked_path", "picked",
                "chosen_path", "chosen",
                "selected_path", "selected",
                "output_path", "output",
                "result_path", "result",
                "target_path", "target",
                "matched_path", "matched",
            )
            for k in FINAL_KEYS:
                v = rr.get(k)
                s = self._safe_str(v)
                if s:
                    return s
            return ""

        for pl in self.playlists:
            pl_key = self.runner.canonical_key(pl)

            has_saved_progress = pl_key in self._persisted_progress_keys

            # Show resolved rows only for this session's provisional Repair or
            # for progress that was explicitly committed with Save.
            if pl_key not in self._session_repaired_keys and not has_saved_progress:
                continue

            disk_sel = self._load_selections_for_key(pl_key) if has_saved_progress else {}
            mem_sel = self._selections_by_key.get(pl_key, {}) or {}
            selections = {**disk_sel, **mem_sel}

            report_rows = self._report_rows_by_key.get(pl_key, [])
            if not report_rows:
                continue

            for rr in report_rows:
                status = self._safe_str(rr.get("status")).upper()
                row_index = self._safe_str(rr.get("row_index", rr.get("_i", "")))
                extinf_display = self._safe_str(rr.get("extinf_display") or rr.get("extinf") or "")
                notes_raw = self._safe_str(rr.get("notes") or "")

                orig = self._safe_str(rr.get("original_path") or rr.get("original") or "")
                written = pick_written_path(rr)

                manual = bool(row_index and row_index in selections)
                after = selections.get(row_index, "").strip() if manual else (written or orig)

                # resolved 판단: manual exists OR report itself says resolved OR has a written/picked path
                auto_resolved = any(k in status for k in RESOLVED_STATUSES)
                is_resolved = manual or auto_resolved
                if not is_resolved:
                    continue

                # Decide bucket (heuristic but stable):
                # 1) if status indicates ambiguous/failed => use it
                # 2) else if notes includes multiple candidates => ambiguous
                # 3) else => failed
                bucket = ""
                if status in AMBIG_STATUSES:
                    bucket = "AMBIGUOUS"
                elif status in FAIL_STATUSES:
                    bucket = "FAILED"
                else:
                    # heuristic: candidates in notes -> ambiguous-ish
                    cands = []
                    try:
                        cands = self.runner._parse_candidates_from_notes(notes_raw) or []
                    except Exception:
                        cands = []
                    bucket = "AMBIGUOUS" if len(cands) >= 2 else "FAILED"

                source_tag = "[MANUAL]" if manual else "[AUTO]"
                status_tag = f"(status={status})" if status else ""

                row = {
                    "playlist": str(pl),
                    "pl_key": pl_key,
                    "row_index": row_index if row_index else self._safe_str(rr.get("_i", "")),
                    "extinf_display": extinf_display,
                    "original_path": orig,
                    "notes": f"{source_tag} {after} {status_tag}".strip(),
                    "candidates": (self.runner._parse_candidates_from_notes(notes_raw) if hasattr(self.runner, "_parse_candidates_from_notes") else []),
                }

                if bucket == "AMBIGUOUS":
                    amb_rows.append(row)
                else:
                    fail_rows.append(row)

        return amb_rows, fail_rows

    def _refresh_tables_from_mode(self) -> None:
        """Rebuild visible rows based on current view mode and cached report rows."""
        # clear active selection & candidates
        self.tbl_amb.clearSelection()
        self.tbl_fail.clearSelection()
        self.lst_candidates.clear()
        self._active_target = None
        self._active_pl_key = None
        self._active_row_id = None
        self.lbl_target.setText("Target: (none)")

        if self._view_mode == "RESOLVED":
            amb, fail = self._build_resolved_rows()
        else:
            amb, fail = self._build_unresolved_rows()

        # master (unfiltered)
        self._ambiguous_rows_all = amb
        self._failed_rows_all = fail

        # apply search filter (will also fill tables)
        self._apply_search_filter()

        # tiny status hint
        if self._view_mode == "RESOLVED":
            self.status_label.setText("View: Resolved (audit / fix wrong picks)")
        else:
            self.status_label.setText("View: Unresolved (needs action)")

    # ---------- actions ----------
    def on_view_mode_changed(self, idx: int):
        self._view_mode = "RESOLVED" if idx == 1 else "UNRESOLVED"
        self._refresh_tables_from_mode()

    def on_add_music(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Music Folder")
        if not folder:
            return
        p = Path(folder)

        if any(Path(r.get("path", "")) == p for r in self.music_roots):
            self.status_label.setText(f"Already added: {folder}")
            return

        self.music_roots.append({"path": str(p), "enabled": True, "imported": False})
        # Do not persist yet. A folder becomes permanent only after a scan
        # successfully imports at least one track from it.
        self._refresh_music_roots_ui()
        self.status_label.setText(f"Pending scan: {folder}")

    def on_remove_music_roots(self):
        items = self.lst_music_roots.selectedItems()
        if not items:
            return

        to_remove = set()
        for it in items:
            raw = it.data(Qt.UserRole)
            if raw:
                to_remove.add(str(raw))

        if not to_remove:
            return

        self.music_roots = [r for r in self.music_roots if str(r.get("path", "")) not in to_remove]
        self._save_music_roots()
        self._refresh_music_roots_ui()
        self.status_label.setText(f"Removed: {len(to_remove)} folder(s)")

    def on_clear_music_roots(self):
        if not self.music_roots:
            return
        self.music_roots = []
        self._save_music_roots()
        self._refresh_music_roots_ui()
        self.status_label.setText("Cleared all music folders")

    def on_scan_index(self):
        """Import only folders that have not yet been indexed.

        Checkboxes remain Repair-scope controls. Existing imported roots are
        deliberately skipped so adding one new folder never rescans a large
        established library.
        """
        if self._busy:
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return

        scan_roots = [Path(r["path"]) for r in self.music_roots if not r.get("imported", False)]
        if not scan_roots:
            QMessageBox.information(
                self,
                "No new folders",
                "There are no Pending scan folders.\n\n"
                "Use Rescan Selected only when you intentionally want to refresh an existing folder.",
            )
            return

        missing = [str(p) for p in scan_roots if not p.exists()]
        if missing:
            QMessageBox.warning(self, "Unavailable folder", "These new folders are unavailable:\n" + "\n".join(missing))
            return

        self.status_label.setText(f"Scanning {len(scan_roots)} new folder(s)…")
        self._run_task(self.runner.scan_index, music_roots=scan_roots, out_index=self.index_path)

    def on_rescan_selected(self):
        """Explicitly refresh imported roots selected by row highlight.

        Row selection controls this operation; checkbox state still controls
        Repair scope and is intentionally ignored here.
        """
        if self._busy:
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return

        selected_paths = {
            str(item.data(Qt.UserRole))
            for item in self.lst_music_roots.selectedItems()
            if item.data(Qt.UserRole)
        }
        scan_roots = [
            Path(r["path"])
            for r in self.music_roots
            if r.get("imported", False) and str(r.get("path", "")) in selected_paths
        ]
        if not scan_roots:
            QMessageBox.information(
                self,
                "Select imported folder",
                "Highlight one or more already imported folders in the list, then choose Rescan Selected.\n\n"
                "The checkbox is only for Repair scope.",
            )
            return

        missing = [str(p) for p in scan_roots if not p.exists()]
        if missing:
            QMessageBox.warning(self, "Unavailable folder", "These selected folders are unavailable:\n" + "\n".join(missing))
            return

        names = "\n".join(str(p) for p in scan_roots)
        answer = QMessageBox.question(
            self,
            "Rescan selected folders?",
            "This will reread and replace the existing index entries for:\n\n"
            + names
            + "\n\nOther imported folders will remain unchanged.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.status_label.setText(f"Rescanning {len(scan_roots)} selected folder(s)…")
        self._run_task(self.runner.scan_index, music_roots=scan_roots, out_index=self.index_path)

    def on_import_playlists(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select playlist(s)",
            "",
            "Playlists (*.m3u *.m3u8 *.xlsx);;M3U playlists (*.m3u *.m3u8);;Roon Excel exports (*.xlsx);;All files (*.*)"
        )
        if not files:
            return

        self.playlists = [Path(p) for p in files]
        self.status_label.setText(f"Loaded playlists: {len(self.playlists)}")
        
        self._show_import_hint_once()
       
        # load reports cache then refresh view
        self._selections_by_key = {}          # ✅ 清掉上一輪 Apply 的記憶體選擇
        self._session_repaired_keys = set()   # ✅ 新 session
        self._saved_keys = set()   # ✅ 新 session，尚未 Save
        self._reload_reports_cache()
        self._refresh_tables_from_mode()

    def on_repair_safe(self):
        if self._busy:
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return
        if not self.playlists:
            QMessageBox.warning(self, "No playlist", "Please import playlist(s) first.")
            return
        enabled_roots = self._enabled_music_roots()
        if not enabled_roots:
            QMessageBox.warning(self, "No music root", "Please enable at least one music folder before Repair.")
            return
        if not self.index_path.exists():
            QMessageBox.warning(self, "No index", f"Index not found: {self.index_path}\nPlease use Scan New Folders first.")
            return

        # 防呆：避免誤按 Repair 覆寫 report
        has_any_report = any(
            self._has_saved_progress(self.runner.canonical_key(pl), pl)
            for pl in self.playlists
        )

        if has_any_report:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("Repair report exists")
            box.setText(
                "Saved repair progress already exists.\n\n"
                "Resume keeps that saved progress. Re-run creates a provisional new result; "
                "the saved progress is not replaced unless you press Save.\n\n"
                "What do you want to do?"
            )

            btn_resume = box.addButton("Resume (load existing report)", QMessageBox.AcceptRole)
            btn_rerun = box.addButton("Re-run Repair (provisional)", QMessageBox.DestructiveRole)
            btn_cancel = box.addButton("Cancel", QMessageBox.RejectRole)

            box.exec()
            clicked = box.clickedButton()

            if clicked == btn_resume:
                self._session_repaired_keys = set()
                self._reload_reports_cache()
                self._refresh_tables_from_mode()
                self.status_label.setText("Resumed from saved progress.")
                return
            if clicked == btn_cancel:
                return
            # clicked == btn_rerun -> create a provisional session report

        # clear UI before repair
        self._ambiguous_rows = []
        self._failed_rows = []
        self._amb_by_id = {}
        self._fail_by_id = {}
        self._active_target = None
        self._active_pl_key = None
        self._active_row_id = None
        self.lbl_target.setText("Target: (none)")
        self._fill_table(self.tbl_amb, [])
        self._fill_table(self.tbl_fail, [])
        self.lst_candidates.clear()
        self._session_repaired_keys = {self.runner.canonical_key(pl) for pl in self.playlists}

        self._run_task(
            self.runner.repair_playlists,
            playlists=self.playlists,
            index_path=self.index_path,
            out_dir=self.reports_path,
            mode="safe",
            dry_run=False,
            enabled_roots=enabled_roots,
            session_reports=True,
        )

    def on_open_reports(self):
        try:
            self.reports_path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.reports_path))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_ambiguous_selected(self):
        if self.tbl_amb.selectionModel() and self.tbl_amb.selectionModel().hasSelection():
            self.tbl_fail.clearSelection()
            self._active_target = "AMBIGUOUS"
            self._active_pl_key, self._active_row_id = self._selected_row_id(self.tbl_amb)
            self._refresh_candidates_panel()

    def on_failed_selected(self):
        if self.tbl_fail.selectionModel() and self.tbl_fail.selectionModel().hasSelection():
            self.tbl_amb.clearSelection()
            self._active_target = "FAILED"
            self._active_pl_key, self._active_row_id = self._selected_row_id(self.tbl_fail)
            self._refresh_candidates_panel()

    def on_browse_choice(self):
        if self._active_target is None or self._active_row_id is None or self._active_pl_key is None:
            QMessageBox.warning(self, "No selection", "Please select a row from AMBIGUOUS or FAILED first.")
            return

        file, _ = QFileDialog.getOpenFileName(self, "Pick the correct audio file", "", "Audio files (*.*)")
        if not file:
            return

        self.lst_candidates.clear()
        self.lst_candidates.addItem(QListWidgetItem(file))
        self.lst_candidates.setCurrentRow(0)

    def on_apply_choice(self):
        if self._active_target is None or self._active_row_id is None or self._active_pl_key is None:
            QMessageBox.warning(self, "No selection", "Please select a row from AMBIGUOUS or FAILED first.")
            return

        chosen = self._current_candidate()
        if not chosen:
            QMessageBox.warning(self, "No file", "Please select a candidate (or Browse…) first.")
            return

        pl_key = self._active_pl_key
        row_id = self._active_row_id

        # only in-memory, do NOT persist to disk here
        self._selections_by_key.setdefault(pl_key, {})[row_id] = chosen

        tag = "[SELECTED]" if self._active_target == "AMBIGUOUS" else "[RESCUED]"
        table = self.tbl_amb if self._active_target == "AMBIGUOUS" else self.tbl_fail

        vis_row = self._selected_visual_row(table)
        if vis_row is not None:
            # overwrite Notes (works in both modes)
            if self._view_mode == "RESOLVED":
                table.setItem(vis_row, 3, QTableWidgetItem(f"[MANUAL] {chosen}"))
            else:
                table.setItem(vis_row, 3, QTableWidgetItem(f"{tag} {chosen}"))

        self.status_label.setText(f"Applied (not saved): key={pl_key} row={row_id}")

        # If in unresolved view, you might want to keep the row visible until Save.
        # If in resolved view, also keep visible to allow further audit.
        # (No auto-removal here; removal happens after Save+reload.)

    def on_save_fixed(self):
        """
        Save/export final playlists.
        This is the ONLY step that writes fixed_*_selected.m3u
        AND the ONLY step that persists selections_*.json
        """
        if self._busy:
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return
        if not self.playlists:
            QMessageBox.warning(self, "No playlist", "Please import playlist(s) first.")
            return

        jobs = []
        pending_keys: list[str] = []

        for pl in self.playlists:
            pl_key = self.runner.canonical_key(pl)
            if pl_key in self._session_repaired_keys:
                report_csv = self._session_report_for(pl)
            elif self._has_saved_progress(pl_key, pl):
                report_csv = self.runner.report_path_for(self.reports_path, pl)
            else:
                continue
            if not report_csv.exists():
                continue

            out_m3u = self.runner.export_path_for(self.reports_path, pl)
            selections = self._selections_by_key.get(pl_key, {}) or {}

            jobs.append({"report_csv": str(report_csv), "out_m3u": str(out_m3u), "selections": selections})
            pending_keys.append(pl_key)

        if not jobs:
            QMessageBox.critical(self, "Missing report", "No active Repair result or saved progress was found.\nRun Repair (Safe) first.")
            return

        self._pending_save_keys = pending_keys
        self._pending_save_sources = {self.runner.canonical_key(pl): pl for pl in self.playlists}
        self._pending_save_outputs = {
            self.runner.canonical_key(pl): self.runner.export_path_for(self.reports_path, pl)
            for pl in self.playlists
        }
        self._last_action = "SAVE"
        self._run_task(self.runner.export_fixed_multi, jobs=jobs)
    
    def on_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About Playlist Fixer")
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)

        html = """
        <h3>Playlist Fixer</h3>
        <p>
          Author: <b>Ne</b><br/>
          GitHub:
          <a href="https://github.com/Nechani">
            https://github.com/Nechani
          </a><br/>
          Support (Ko-fi):
          <a href="https://ko-fi.com/nechani">
            https://ko-fi.com/nechani
          </a>
        </p>

        <p>
          If you encounter any issues or unexpected behavior,<br/>
          feel free to contact me at
          <a href="mailto:plfixne@gmail.com">plfixne@gmail.com</a>
        </p>

        <p style="color:#666; font-size: 11px;">
          No paywall. No ads. Built for people who care about their libraries.
        </p>
        """

        view = QTextBrowser()
        view.setHtml(html)
        view.setOpenExternalLinks(True)  # ✅ 點連結用預設瀏覽器開
        view.setMinimumWidth(520)
        view.setMinimumHeight(220)

        layout.addWidget(view)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.close)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

        dlg.resize(560, 260)
        dlg.exec()

    # ---------- internals ----------
    def _rebuild_row_maps(self):
        self._amb_by_id = {}
        self._fail_by_id = {}

        for r in self._ambiguous_rows:
            pl_key = str(r.get("pl_key", "")).strip()
            row_id = str(r.get("row_index", "")).strip()
            if pl_key and row_id:
                self._amb_by_id[f"{pl_key}::{row_id}"] = r

        for r in self._failed_rows:
            pl_key = str(r.get("pl_key", "")).strip()
            row_id = str(r.get("row_index", "")).strip()
            if pl_key and row_id:
                self._fail_by_id[f"{pl_key}::{row_id}"] = r

    def _refresh_candidates_panel(self):
        self.lst_candidates.clear()

        if self._active_target is None or self._active_row_id is None or self._active_pl_key is None:
            self.lbl_target.setText("Target: (none)")
            return

        key = f"{self._active_pl_key}::{self._active_row_id}"
        r = self._amb_by_id.get(key) if self._active_target == "AMBIGUOUS" else self._fail_by_id.get(key)

        if not r:
            self.lbl_target.setText("Target: (none)")
            return

        extinf = str(r.get("extinf_display", ""))
        self.lbl_target.setText(
            f"Target: {self._active_target} | key={self._active_pl_key} | row={self._active_row_id} | {extinf}"
        )

        cands = r.get("candidates", []) or []

        if self._active_target == "FAILED":
            self.lst_candidates.addItem(QListWidgetItem("(No candidates. Use Browse…)"))
            return

        if not cands:
            self.lst_candidates.addItem(QListWidgetItem("(No candidates parsed from Notes. Use Browse…)"))
            return

        for p in cands:
            self.lst_candidates.addItem(QListWidgetItem(p))
        self.lst_candidates.setCurrentRow(0)

    def _selected_visual_row(self, table: QTableWidget) -> int | None:
        sel = table.selectionModel()
        if not sel or not sel.hasSelection():
            return None
        idxs = sel.selectedRows()
        if not idxs:
            return None
        return idxs[0].row()

    def _selected_row_id(self, table: QTableWidget) -> tuple[str | None, str | None]:
        vis_row = self._selected_visual_row(table)
        if vis_row is None:
            return None, None

        item0 = table.item(vis_row, 0)
        if not item0:
            return None, None

        data = item0.data(Qt.UserRole)
        if not isinstance(data, dict):
            return None, None

        pl_key = data.get("pl_key")
        row_id = data.get("row_id")
        if pl_key is None or row_id is None:
            return None, None

        return str(pl_key), str(row_id)

    def _current_candidate(self) -> str:
        it = self.lst_candidates.currentItem()
        if not it:
            return ""
        txt = (it.text() or "").strip()
        if txt.startswith("("):
            return ""
        return txt

    def _run_task(self, func, **kwargs):
        if self._busy:
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return

        self._last_progress_msg = ""
        self._set_busy(True, "Running...")
        self.progress.setValue(0)

        self.thread = QThread()
        self.worker = Worker(func, kwargs)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    @Slot(int, str)
    def _on_progress(self, pct: int, msg: str):
        self.progress.setValue(int(pct))
        if msg:
            self._last_progress_msg = msg
            self.status_label.setText(msg)
            m = re.search(r"(?:indexed so far|Indexed)\s*:\s*(\d+)", msg, re.IGNORECASE)
            if m:
                self.scan_count_label.setText(f"Indexed: {m.group(1)}")

    @Slot(object)
    def _on_finished(self, result):
        self._set_busy(False)
        self.progress.setValue(100)

        if isinstance(result, TaskResult):
            self.status_label.setText(result.message or "Done")
            outs = result.outputs or {}

            # Scan result: persist only roots that actually contributed tracks.
            if "root_results" in outs:
                results = outs.get("root_results", []) or []
                scanned_paths = {str(Path(r.get("root", ""))) for r in results if r.get("root")}
                successful = {
                    str(Path(r.get("root", "")))
                    for r in results
                    if r.get("root") and int(r.get("indexed", 0) or 0) > 0
                }

                kept: list[dict] = []
                for entry in self.music_roots:
                    key = str(Path(entry.get("path", "")))
                    if key in scanned_paths:
                        if key in successful:
                            entry["imported"] = True
                            kept.append(entry)
                        # Scanned but indexed zero: remove automatically.
                    else:
                        # Disabled roots were not part of this rebuild. Keep only
                        # roots that had already been confirmed by an earlier scan.
                        if entry.get("imported", False):
                            kept.append(entry)

                self.music_roots = kept
                self._save_music_roots()
                self._refresh_music_roots_ui()

                rejected = len(scanned_paths - successful)
                scan_indexed = int(outs.get("scan_indexed", 0) or 0)
                total_indexed = int(outs.get("total_indexed", scan_indexed) or 0)
                preserved_indexed = int(outs.get("preserved_indexed", 0) or 0)
                self.scan_count_label.setText(f"Indexed: {total_indexed}")
                msg = (
                    f"Scan complete. Added/updated roots: {len(successful)}; "
                    f"tracks scanned: {scan_indexed}; total library: {total_indexed}"
                )
                if preserved_indexed:
                    msg += f"; retained from other indexed roots: {preserved_indexed}"
                if rejected:
                    msg += f"; removed empty/unreadable selected roots: {rejected}"
                self.status_label.setText(msg)
                QMessageBox.information(self, "Scan Complete", msg)
                return

            # Repair result
            if "ambiguous" in outs or "failed" in outs:
                # After repair, reports on disk changed -> reload cache then refresh current view
                self._reload_reports_cache()
                self._refresh_tables_from_mode()

                summaries = outs.get("summaries", []) or []
                if summaries:
                    try:
                        total_amb = sum(int(s.get("ambiguous", 0)) for s in summaries)
                        total_fail = sum(int(s.get("failed", 0)) for s in summaries)
                        total_rep = sum(int(s.get("repaired", 0)) for s in summaries)
                        total_kept = sum(int(s.get("kept", 0)) for s in summaries)
                    except Exception:
                        total_amb = total_fail = total_rep = total_kept = 0

                    QMessageBox.information(
                        self,
                        "Repair Complete",
                        f"Kept: {total_kept}\n"
                        f"Repaired: {total_rep}\n"
                        f"Ambiguous: {total_amb}\n"
                        f"Failed: {total_fail}\n\n"
                        f"Reports: {self.reports_path}",
                    )
                return

            # Save result
            if "done" in outs:
                if getattr(self, "_last_action", None) == "SAVE":
                    for pl_key in getattr(self, "_pending_save_keys", []) or []:
                        source = getattr(self, "_pending_save_sources", {}).get(pl_key)
                        if source is not None:
                            session_report = self._session_report_for(source)
                            persistent_report = self.runner.report_path_for(self.reports_path, source)
                            if session_report.exists():
                                persistent_report.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(session_report, persistent_report)
                            saved_output = getattr(self, "_pending_save_outputs", {}).get(pl_key)
                            if saved_output is not None:
                                self._write_progress_marker(pl_key, saved_output, source)
                        sel = self._selections_by_key.get(pl_key, {}) or {}
                        self._save_selections_for_key(pl_key, sel)
                        self._saved_keys.add(pl_key)
                        self._persisted_progress_keys.add(pl_key)
                    self._pending_save_keys = []
                    self._pending_save_sources = {}
                    self._pending_save_outputs = {}
                    self._last_action = None

                done = outs.get("done", [])
                first = done[0].get("out_m3u", "") if done else ""
                QMessageBox.information(self, "Save Complete", f"{result.message}\n\nExample output:\n{first}")

                # After save, if user is in Unresolved view, they likely want remaining list updated.
                # Reload reports cache + refresh tables (respects current view mode).
                self._reload_reports_cache()
                self._refresh_tables_from_mode()
                return

        self.status_label.setText("Done")

    @Slot(str)
    def _on_failed(self, err: str):
        self._set_busy(False)
        self.progress.setValue(0)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Error", err)

    def _fill_table(self, table: QTableWidget, rows: list[dict]):
        table.setRowCount(0)

        for r in rows:
            vis_row = table.rowCount()
            table.insertRow(vis_row)

            playlist = str(r.get("playlist", ""))
            pl_key = str(r.get("pl_key", ""))
            row_id = str(r.get("row_index", "")).strip()

            extinf = str(r.get("extinf_display", ""))
            orig = str(r.get("original_path", ""))
            notes = str(r.get("notes", ""))

            it0 = QTableWidgetItem(playlist)
            it0.setData(Qt.UserRole, {"pl_key": pl_key, "row_id": row_id})
            table.setItem(vis_row, 0, it0)

            table.setItem(vis_row, 1, QTableWidgetItem(extinf))
            table.setItem(vis_row, 2, QTableWidgetItem(orig))
            table.setItem(vis_row, 3, QTableWidgetItem(notes))

    def _norm(self, s: str) -> str:
        s = (s or "").strip().lower()
        # 讓 "A - B" / "A_B" / 空白差異比較不影響
        s = s.replace("\u3000", " ")
        return " ".join(s.split())

    def _row_matches_query(self, r: dict, q: str) -> bool:
        """
        q: already normalized lower
        Match against:
        - EXTINF display (song title)
        - original path (full + basename)
        - notes (includes [SELECTED]/[RESCUED]/[AUTO]/[MANUAL] paths)
        - candidates list (full + basename)
        - playlist name (optional but handy)
        """
        if not q:
            return True

        def hit(text: str) -> bool:
            t = self._norm(text)
            return bool(t) and (q in t)

        # Playlist filename
        if hit(Path(str(r.get("playlist", ""))).name):
            return True

        # EXTINF
        if hit(str(r.get("extinf_display", ""))):
            return True

        # Original path
        orig = str(r.get("original_path", "") or "")
        if orig and (hit(orig) or hit(Path(orig).name)):
            return True

        # Notes
        notes = str(r.get("notes", "") or "")
        if notes and hit(notes):
            return True

        # Candidates
        cands = r.get("candidates", []) or []
        for p in cands:
            ps = str(p or "")
            if ps and (hit(ps) or hit(Path(ps).name)):
                return True

        return False

    def _apply_search_filter(self) -> None:
        """
        Apply UI-only filtering using self._ambiguous_rows_all / self._failed_rows_all as masters.
        IMPORTANT:
        - Do NOT mutate *_rows_all here (they must remain unfiltered masters).
        - Do NOT call itself (no recursion).
        """
        q = ""
        if hasattr(self, "edt_search") and self.edt_search is not None:
            q = self._norm(self.edt_search.text())

        self._ambiguous_rows = [r for r in (self._ambiguous_rows_all or []) if self._row_matches_query(r, q)]
        self._failed_rows = [r for r in (self._failed_rows_all or []) if self._row_matches_query(r, q)]

        self._rebuild_row_maps()
        self._fill_table(self.tbl_amb, self._ambiguous_rows)
        self._fill_table(self.tbl_fail, self._failed_rows)

        # optional: clear selection after filtering to avoid stale row_id
        self.tbl_amb.clearSelection()
        self.tbl_fail.clearSelection()
        self.lst_candidates.clear()
        self._active_target = None
        self._active_pl_key = None
        self._active_row_id = None
        self.lbl_target.setText("Target: (none)")

    def on_search_changed(self, _text: str) -> None:
        self._apply_search_filter()
