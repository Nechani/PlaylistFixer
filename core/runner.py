from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any
import json
import csv

from core.paths import stats_path as stats_path_fn
from core.vendor.playlist_scan_safe import scan_folder
from core.vendor.repair_playlist_safe_v4 import repair_playlist

ProgressCb = Callable[[int, str], None]


@dataclass
class TaskResult:
    ok: bool
    message: str
    outputs: Dict[str, Any]


class TaskRunner:
    """UI runner wiring to verified scan/repair logic."""

    # -------------------------
    # Canonical key helpers
    # -------------------------
    def canonical_key(self, playlist_path: Path) -> str:
        """
        Normalize a playlist filename to a stable key so that:
        - 15.m3u                 -> 15
        - fixed_15.m3u           -> 15
        - fixed_15_selected.m3u  -> 15
        - __tmp_fixed_15.m3u     -> 15
        """
        stem = playlist_path.stem

        # strip known prefixes
        for prefix in ("__tmp_fixed_", "draft_fixed_", "fixed_"):
            if stem.startswith(prefix):
                stem = stem[len(prefix):]

        # strip known suffixes
        for suffix in ("_selected",):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]

        stem = stem.strip()
        return stem if stem else playlist_path.stem

    def report_path_for(self, out_dir: Path, playlist_path: Path) -> Path:
        key = self.canonical_key(playlist_path)
        return out_dir / f"repair_report_{key}.csv"

    def selections_path_for(self, out_dir: Path, playlist_path: Path) -> Path:
        key = self.canonical_key(playlist_path)
        return out_dir / f"selections_{key}.json"

    def export_path_for(self, out_dir: Path, playlist_path: Path) -> Path:
        key = self.canonical_key(playlist_path)
        return out_dir / f"fixed_{key}_selected.m3u"

    # -------------------------
    # Scan
    # -------------------------
    def scan_index(
        self,
        music_roots: List[Path],
        out_index: Path,
        progress: Optional[ProgressCb] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> TaskResult:
        roots = [Path(r) for r in music_roots]
        if progress:
            progress(0, "Scanning…")

        items: list[dict] = []
        stats = {"roots": [], "scanned_supported": 0, "skipped_no_duration": 0, "indexed": 0}

        total = max(1, len(roots))
        for idx, r in enumerate(roots):
            if cancel_flag and cancel_flag():
                return TaskResult(False, "Scan cancelled.", {"index": None})
            if progress:
                progress(int(idx * 100 / total), f"Scanning: {r} | indexed so far: {len(items)}")

            res = scan_folder(r)
            items.extend(res.get("items", []))
            stats["roots"].append(res.get("root", str(r)))
            stats["scanned_supported"] += int(res.get("scanned_supported", 0))
            stats["skipped_no_duration"] += int(res.get("skipped_no_duration", 0))

        stats["indexed"] = len(items)

        out_index.parent.mkdir(parents=True, exist_ok=True)
        out_index.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

        sp = stats_path_fn()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

        if progress:
            progress(100, f"Scan complete. Indexed: {stats['indexed']}")
        return TaskResult(True, f"Scan complete. Indexed: {stats['indexed']}", {"index": str(out_index), "stats": str(sp)})

    # -------------------------
    # Report helpers
    # -------------------------
    def _read_report_rows(self, report_csv: Path) -> list[dict]:
        rows: list[dict] = []
        if not report_csv.exists():
            return rows
        with report_csv.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for i, r in enumerate(reader):
                r["_i"] = i
                if "row_index" not in r or r["row_index"] in (None, ""):
                    r["row_index"] = str(i)
                else:
                    r["row_index"] = str(r["row_index"]).strip()
                rows.append(r)
        return rows

    def _parse_candidates_from_notes(self, notes: str) -> list[str]:
        """
        Parse candidate file paths from notes.

        - Prefer part after 'candidates:' if present.
        - Split by '|'
        - Keep only tokens that look like a file path (has separator + filename contains a dot)
        """
        notes = (notes or "").strip()
        if not notes:
            return []

        low = notes.lower()
        if "candidates:" in low:
            notes = notes[low.index("candidates:") + len("candidates:") :].strip()

        cands: list[str] = []
        for part in notes.split("|"):
            p = (part or "").strip().strip('"').strip("'")
            if not p:
                continue

            has_sep = (":\\" in p) or ("/" in p) or ("\\" in p)
            name = Path(p).name
            looks_like_file = ("." in name) and len(name) >= 3

            if has_sep and looks_like_file:
                cands.append(p)

        return cands

    def _picked_path_from_row(self, r: dict) -> str:
        """
        Detect "final chosen path" from report columns.
        Do NOT use notes.
        """
        if not isinstance(r, dict):
            return ""

        KEY_HINTS = (
            "written", "written_path",
            "chosen", "chosen_path",
            "selected", "selected_path",
            "best", "best_path", "best_match", "best_match_path",
            "final", "final_path",
            "resolved", "resolved_path",
            "output", "output_path",
            "matched", "matched_path",
            "picked", "picked_path",
            "target", "target_path",
            "result", "result_path",
        )

        for k, v in r.items():
            lk = str(k).lower()
            if any(h in lk for h in KEY_HINTS):
                s = (str(v) if v is not None else "").strip()
                if s:
                    return s

        return ""

    def _classify_for_ui(self, report_rows: list[dict], playlist_path: Path) -> tuple[list[dict], list[dict]]:
        """
        UNRESOLVED UI classification (robust):
        - Show only rows that still need human action.
        - Skip resolved rows.
        - Robust to different status naming conventions by using keyword matching.
        - Do NOT fallback unknown statuses into FAILED blindly; only classify if it matches patterns.
        """
        ambiguous: list[dict] = []
        failed: list[dict] = []

        pl_key = self.canonical_key(playlist_path)

        def norm(s: str) -> str:
            return (s or "").strip().upper()

        def classify_status(st: str) -> str:
            """
            Return: 'RESOLVED' | 'AMBIGUOUS' | 'FAILED' | ''(unknown)
            """
            st = norm(st)
            if not st:
                return ""

            # resolved keywords
            if any(k in st for k in ("KEPT", "REPAIRED", "FIXED", "OK", "DONE", "SUCCESS", "RESOLV")):
                return "RESOLVED"

            # ambiguous-ish keywords
            if any(k in st for k in ("AMBIG", "MULTI", "CONFLICT", "DUPLIC", "CANDIDATE", "MULTIPLE")):
                return "AMBIGUOUS"

            # failed-ish keywords
            if any(k in st for k in ("FAIL", "NOT_FOUND", "NOTFOUND", "MISSING", "MISS", "ERROR", "ERR")):
                return "FAILED"

            return ""

        for r in report_rows:
            status_raw = r.get("status") or ""
            kind = classify_status(status_raw)

            # resolved => never show in unresolved lists
            if kind == "RESOLVED":
                continue

            # only show known unresolved kinds
            if kind not in ("AMBIGUOUS", "FAILED"):
                continue

            row_index_raw = (r.get("row_index") or r.get("_i") or -1)
            try:
                row_index = int(str(row_index_raw).strip())
            except Exception:
                row_index = -1

            extinf_display = (r.get("extinf_display") or r.get("extinf") or "").strip()
            notes = (r.get("notes") or "").strip()
            orig = (r.get("original_path") or r.get("original") or "").strip()

            cands = self._parse_candidates_from_notes(notes)

            row = {
                "playlist": str(playlist_path),
                "pl_key": pl_key,
                "row_index": row_index,
                "extinf_display": extinf_display,
                "original_path": orig,
                "notes": notes,
                "candidates": cands,
            }

            if kind == "AMBIGUOUS":
                ambiguous.append(row)
            else:
                failed.append(row)

        return ambiguous, failed

    # -------------------------
    # Repair phase (NO playlist output kept)
    # -------------------------
    def repair_playlists(
        self,
        playlists: List[Path],
        index_path: Path,
        out_dir: Path,
        mode: str = "safe",
        dry_run: bool = False,
        progress: Optional[ProgressCb] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> TaskResult:
        """
        Repair(Safe):
        - Generates repair_report_{key}.csv
        - Does NOT keep auto-generated fixed playlist file (tmp file deleted).
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        summaries: list[dict] = []
        all_amb: list[dict] = []
        all_fail: list[dict] = []

        total_pl = max(1, len(playlists))
        for i, pl in enumerate(playlists):
            if cancel_flag and cancel_flag():
                return TaskResult(False, "Repair cancelled.", {})

            pct = int(i * 100 / total_pl)
            if progress:
                progress(pct, f"Repairing: {pl.name}")

            key = self.canonical_key(pl)
            tmp_fixed = out_dir / f"__tmp_fixed_{key}.m3u"
            report_path = self.report_path_for(out_dir, pl)

            s = repair_playlist(str(pl), str(index_path), str(tmp_fixed), str(report_path), verbose=False)
            summaries.append(s)

            # remove tmp output playlist
            try:
                if tmp_fixed.exists():
                    tmp_fixed.unlink()
            except Exception:
                pass

            report_rows = self._read_report_rows(report_path)
            if report_rows:
                amb, fail = self._classify_for_ui(report_rows, pl)
                all_amb.extend(amb)
                all_fail.extend(fail)

        if progress:
            progress(100, "Repair complete.")
        return TaskResult(
            True,
            "Repair complete.",
            {
                "summaries": summaries,
                "out_dir": str(out_dir),
                "ambiguous": all_amb,
                "failed": all_fail,
            },
        )

    # -------------------------
    # Save/Export phase (final playlist output)
    # -------------------------
    def export_fixed_multi(
        self,
        jobs: List[Dict[str, Any]],
        progress: Optional[ProgressCb] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> TaskResult:
        """
        Save/export final playlists.

        - Use STRICT final-path whitelist keys to avoid accidentally using candidates columns.
        - Manual selections override everything.
        - For resolved statuses, write final path (from whitelist) or orig if missing.
        - For unresolved statuses, keep original path.
        """

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

        RESOLVED_KEYWORDS = ("KEPT", "REPAIRED", "FIXED", "OK", "DONE", "SUCCESS", "RESOLV")

        def is_resolved_status(st: str) -> bool:
            st = (st or "").strip().upper()
            return any(k in st for k in RESOLVED_KEYWORDS)

        def pick_final(rr: dict) -> str:
            for k in FINAL_KEYS:
                v = rr.get(k)
                s = (str(v) if v is not None else "").strip()
                if s:
                    return s
            return ""

        done = []
        total = max(1, len(jobs))

        for i, job in enumerate(jobs):
            if cancel_flag and cancel_flag():
                return TaskResult(False, "Export cancelled.", {})

            if progress:
                progress(int(i * 100 / total), f"Saving: {Path(job['out_m3u']).name}")

            report_csv = Path(job["report_csv"])
            out_m3u = Path(job["out_m3u"])
            selections: Dict[str, str] = job.get("selections", {}) or {}

            rows = self._read_report_rows(report_csv)
            lines = ["#EXTM3U"]

            for r in rows:
                row_index = str(r.get("row_index", r.get("_i", ""))).strip()
                extinf_line = (r.get("extinf_line") or r.get("extinf") or "").strip()
                orig = (r.get("original_path") or r.get("original") or "").strip()
                status = (r.get("status") or "").strip()

                final_path = pick_final(r)
                chosen = selections.get(row_index) if row_index else None

                if extinf_line:
                    lines.append(extinf_line)

                if chosen:
                    lines.append(chosen)
                else:
                    if is_resolved_status(status):
                        lines.append(final_path or orig)
                    else:
                        lines.append(orig)

            out_m3u.parent.mkdir(parents=True, exist_ok=True)
            out_m3u.write_text("\n".join(lines) + "\n", encoding="utf-8")
            done.append({"out_m3u": str(out_m3u)})

        if progress:
            progress(100, "Save complete.")
        return TaskResult(True, "Save complete.", {"done": done})