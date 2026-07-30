#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a robust music index without dropping files with incomplete tags."""

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Tuple, Dict, List

from mutagen import File

SUPPORTED_EXTS = {
    ".flac", ".alac", ".m4a", ".mp4", ".aac", ".mp3", ".ogg", ".opus",
    ".wav", ".aif", ".aiff", ".aifc", ".ape", ".wv", ".dsf", ".dff"
}

GENERIC_PATH_TOKENS = {
    "music", "itunes", "itunes media", "media", "hi-res", "hires", "lossless", "lossy",
    "downloads", "download", "album", "albums", "disc", "cd", "cd1", "cd2", "cd3",
    "deluxe", "edition", "remaster", "remastered", "single", "singles", "ep", "compilations",
    "various artists", "va", "unknown", "unknown artist"
}

TRACK_PREFIX_RE = re.compile(r"^\s*(\(?\d{1,3}\)?[\s._-]+)+", re.UNICODE)

# These extensions use the same generic raw-tag reader below. They are enabled
# only after a full-library field comparison against the legacy Easy→Raw path:
# 14,141 files, zero differences in every field consumed by Repair.
# All other supported formats retain the legacy parser automatically.
RAW_ONCE_VALIDATED_EXTS = {".aif", ".aiff", ".flac", ".m4a", ".mp3", ".wav"}
REPAIR_METADATA_FIELDS = (
    "duration", "title", "artist", "album_artist", "album", "track", "disc",
)


class ScanCancelled(Exception):
    """Raised when a caller asks an in-progress folder scan to stop."""


def clean_filename_title(stem: str) -> str:
    s = TRACK_PREFIX_RE.sub("", stem.strip()).strip()
    return re.sub(r"\s+", " ", s).strip()


def normalize_token(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def guess_artist_from_path(path: Path) -> Optional[str]:
    parts = list(path.parts[:-1])
    for p in reversed(parts):
        pt = p.strip()
        if not pt:
            continue
        nt = normalize_token(pt)
        if nt in GENERIC_PATH_TOKENS or re.fullmatch(r"\d+", pt) or len(pt) <= 2:
            continue
        if re.fullmatch(r"(19|20)\d{2}", pt):
            continue
        return pt
    return None


def _first(seq):
    if not seq:
        return None
    try:
        v = seq[0]
        if isinstance(v, bytes):
            return v.decode("utf-8", "ignore")
        return str(v)
    except Exception:
        return None


def read_easy_tags(audio) -> Dict[str, Optional[str]]:
    """Read the common identity fields exposed by Mutagen's easy interface."""
    return {
        "title": _first(audio.get("title")),
        "artist": _first(audio.get("artist")),
        "album_artist": _first(audio.get("albumartist")),
        "album": _first(audio.get("album")),
        "track": _first(audio.get("tracknumber")),
        "disc": _first(audio.get("discnumber")),
    }


def read_raw_tags(audio) -> Dict[str, Optional[str]]:
    tags = getattr(audio, "tags", None)
    if not tags:
        return {"title": None, "artist": None, "album_artist": None, "album": None, "track": None, "disc": None}

    def get_any(keys):
        for key in keys:
            if key not in tags:
                continue
            value = tags.get(key)
            if isinstance(value, list):
                return _first(value)
            try:
                return str(value)
            except Exception:
                pass
        return None

    artist = get_any(["TPE1", "ARTIST", "\xa9ART", "©ART"])
    album_artist = get_any(["TPE2", "ALBUMARTIST", "ALBUM ARTIST", "aART", "\xa9aRT", "©aRT"])
    return {
        "title": get_any(["TIT2", "TITLE", "\xa9nam", "©nam"]),
        "artist": artist or album_artist,
        "album_artist": album_artist,
        "album": get_any(["TALB", "ALBUM", "\xa9alb", "©alb"]),
        "track": get_any(["TRCK", "TRACKNUMBER", "TRACK", "trkn"]),
        "disc": get_any(["TPOS", "DISCNUMBER", "DISC", "disk"]),
    }


def parse_number_tag(value: Optional[str]) -> Optional[int]:
    """Parse values such as 3, 3/12, or Mutagen MP4 tuple strings."""
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def get_duration_seconds(audio) -> Optional[int]:
    try:
        info = getattr(audio, "info", None)
        length = getattr(info, "length", None) if info else None
        if length:
            return int(round(float(length)))
    except Exception:
        pass
    return None


def _scan_one_file(p: Path, root: Path) -> Tuple[Optional[dict], bool]:
    """Read one file. Returns (index item, skipped_for_missing_duration)."""
    dur = None
    metadata: Dict[str, Optional[str]] = {
        "title": None, "artist": None, "album_artist": None,
        "album": None, "track": None, "disc": None,
    }
    meta_source = "none"

    try:
        audio_easy = File(str(p), easy=True)
    except Exception:
        audio_easy = None

    if audio_easy:
        dur = get_duration_seconds(audio_easy)
        easy_metadata = read_easy_tags(audio_easy)
        for key, value in easy_metadata.items():
            if value:
                metadata[key] = value
        if any(metadata.values()):
            meta_source = "easy_tag"

    # Open raw tags only when duration or any important identity field is absent.
    # This keeps the normal fast path while filling album/disc/track for formats
    # whose easy mapping is incomplete.
    if dur is None or any(metadata[key] is None for key in ("title", "artist", "album", "track", "disc")):
        try:
            audio_raw = File(str(p), easy=False)
        except Exception:
            audio_raw = None
        if audio_raw:
            if dur is None:
                dur = get_duration_seconds(audio_raw)
            raw_metadata = read_raw_tags(audio_raw)
            filled_raw = False
            for key, value in raw_metadata.items():
                if metadata.get(key) is None and value:
                    metadata[key] = value
                    filled_raw = True
            if meta_source == "none" and filled_raw:
                meta_source = "raw_tag"

    if dur is None:
        return None, True

    if not metadata["title"]:
        metadata["title"] = clean_filename_title(p.stem)
        if meta_source == "none":
            meta_source = "filename"

    if not metadata["artist"]:
        metadata["artist"] = metadata["album_artist"] or guess_artist_from_path(p)
        if metadata["artist"] and meta_source in ("filename", "none"):
            meta_source = "path_guess"

    return ({
        "path": str(p),
        "root": str(root),
        "duration": int(dur),
        "title": metadata["title"],
        "artist": metadata["artist"],
        "album_artist": metadata["album_artist"],
        "album": metadata["album"],
        "track": parse_number_tag(metadata["track"]),
        "disc": parse_number_tag(metadata["disc"]),
        "meta_source": meta_source,
    }, False)


def _scan_one_file_raw_once(p: Path, root: Path) -> Tuple[Optional[dict], bool]:
    """Read duration and identity tags from one Mutagen object.

    This is a format-neutral fast path. It uses the same normalization helpers as
    the legacy scanner and falls back to that scanner if the raw object cannot
    provide a usable duration or any identity metadata.
    """
    try:
        audio = File(str(p), easy=False)
    except Exception:
        audio = None
    if not audio:
        return _scan_one_file(p, root)

    duration = get_duration_seconds(audio)
    metadata = read_raw_tags(audio)
    if duration is None or not any(metadata.values()):
        return _scan_one_file(p, root)

    if not metadata["title"]:
        metadata["title"] = clean_filename_title(p.stem)
    if not metadata["artist"]:
        metadata["artist"] = metadata["album_artist"] or guess_artist_from_path(p)

    return ({
        "path": str(p),
        "root": str(root),
        "duration": int(duration),
        "title": metadata["title"],
        "artist": metadata["artist"],
        "album_artist": metadata["album_artist"],
        "album": metadata["album"],
        "track": parse_number_tag(metadata["track"]),
        "disc": parse_number_tag(metadata["disc"]),
        "meta_source": "raw_tag",
    }, False)


def _same_repair_metadata(left: Optional[dict], right: Optional[dict]) -> bool:
    if left is None or right is None:
        return left is right
    return all(left.get(field) == right.get(field) for field in REPAIR_METADATA_FIELDS)


def scan_folder(
    root: Path,
    existing_items: Optional[List[dict]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
):
    """Scan one root with file-level incremental reuse.

    Existing entries are reused only when path, file size, and nanosecond mtime
    are unchanged. New or modified files are parsed with Mutagen; entries for
    files that disappeared are naturally omitted from the returned item list.
    Older index rows without fingerprints are reparsed once and upgraded.
    """
    root = Path(root)

    def check_cancelled() -> None:
        if cancel_flag and cancel_flag():
            raise ScanCancelled("Scan cancelled.")

    total_started = time.perf_counter()
    enumeration_started = total_started
    existing_by_path: Dict[str, dict] = {}
    for item in existing_items or []:
        try:
            key = os.path.normcase(os.path.abspath(str(item.get("path") or "")))
        except Exception:
            continue
        if key:
            existing_by_path[key] = item

    paths_to_scan: List[Tuple[Path, int, int]] = []
    reused_items: List[dict] = []
    ext_counts: Dict[str, int] = {}
    scanned_supported = 0

    # Enumerating/stat-ing every current file is necessary to discover additions,
    # modifications and deletions, but unchanged files avoid all Mutagen I/O.
    for dirpath, _, filenames in os.walk(root):
        check_cancelled()
        for filename in filenames:
            check_cancelled()
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue
            scanned_supported += 1
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            path = Path(dirpath) / filename
            try:
                st = path.stat()
                size = int(st.st_size)
                mtime_ns = int(st.st_mtime_ns)
            except OSError:
                # Let the normal parser attempt it so transient/stat failures keep
                # the same behavior as a fresh scan.
                size = -1
                mtime_ns = -1

            key = os.path.normcase(os.path.abspath(str(path)))
            old = existing_by_path.get(key)
            if (
                old is not None
                and old.get("size") == size
                and old.get("mtime_ns") == mtime_ns
            ):
                kept = dict(old)
                kept["path"] = str(path)
                kept["root"] = str(root)
                reused_items.append(kept)
            else:
                paths_to_scan.append((path, size, mtime_ns))

    enumeration_seconds = time.perf_counter() - enumeration_started
    parsing_started = time.perf_counter()

    # Guard the fast path with a small per-scan compatibility probe. Probe rows
    # themselves always use the legacy result, so even a mismatch cannot alter
    # the index. If any field consumed by Repair differs, the entire extension
    # stays on the legacy parser for this scan.
    try:
        probe_count = max(1, min(10, int(os.environ.get("PLAYLIST_FIXER_SCAN_PROBES", "3"))))
    except ValueError:
        probe_count = 3

    probe_entries: Dict[str, List[Tuple[Path, int, int]]] = {}
    for entry in paths_to_scan:
        ext = entry[0].suffix.lower()
        if ext in RAW_ONCE_VALIDATED_EXTS and len(probe_entries.setdefault(ext, [])) < probe_count:
            probe_entries[ext].append(entry)

    fast_extensions: set[str] = set()
    probe_results: Dict[str, Tuple[Optional[dict], bool]] = {}
    fallback_extensions: set[str] = set()
    for ext, entries in probe_entries.items():
        check_cancelled()
        compatible = True
        for path, _, _ in entries:
            check_cancelled()
            legacy_result = _scan_one_file(path, root)
            fast_result = _scan_one_file_raw_once(path, root)
            key = os.path.normcase(os.path.abspath(str(path)))
            probe_results[key] = legacy_result
            if legacy_result[1] != fast_result[1] or not _same_repair_metadata(
                legacy_result[0], fast_result[0]
            ):
                compatible = False
        if compatible:
            fast_extensions.add(ext)
        else:
            fallback_extensions.add(ext)

    try:
        requested = int(os.environ.get("PLAYLIST_FIXER_SCAN_WORKERS", "4"))
    except ValueError:
        requested = 4
    workers = max(1, min(8, requested, len(paths_to_scan) or 1))

    def scan_changed(entry: Tuple[Path, int, int]):
        check_cancelled()
        path, size, mtime_ns = entry
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in probe_results:
            item, skipped = probe_results[key]
        elif path.suffix.lower() in fast_extensions:
            item, skipped = _scan_one_file_raw_once(path, root)
        else:
            item, skipped = _scan_one_file(path, root)
        if item is not None:
            item["size"] = size
            item["mtime_ns"] = mtime_ns
        return item, skipped

    if workers == 1:
        results = (scan_changed(entry) for entry in paths_to_scan)
        executor = None
    else:
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pf-scan")
        results = executor.map(scan_changed, paths_to_scan, chunksize=16)

    parsed_items: List[dict] = []
    skipped_no_duration = 0
    try:
        for item, skipped in results:
            check_cancelled()
            if skipped:
                skipped_no_duration += 1
            elif item is not None:
                parsed_items.append(item)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    items = reused_items + parsed_items
    parsing_seconds = time.perf_counter() - parsing_started
    total_seconds = time.perf_counter() - total_started
    return {
        "root": str(root),
        "scanned_supported": scanned_supported,
        "skipped_no_duration": skipped_no_duration,
        "indexed": len(items),
        "ext_counts": ext_counts,
        "items": items,
        "reused_unchanged": len(reused_items),
        "parsed_new_or_changed": len(parsed_items),
        "removed_missing": max(0, len(existing_by_path) - len(reused_items) - sum(
            1 for path, _, _ in paths_to_scan if os.path.normcase(os.path.abspath(str(path))) in existing_by_path
        )),
        "fast_extensions": sorted(fast_extensions),
        "fallback_extensions": sorted(fallback_extensions),
        "enumeration_seconds": round(enumeration_seconds, 3),
        "parsing_seconds": round(parsing_seconds, 3),
        "total_seconds": round(total_seconds, 3),
    }


def main():
    ap = argparse.ArgumentParser(description="Build music_index.json (safe) from a music folder.")
    ap.add_argument("root", help="Root music folder to scan (recursive).")
    ap.add_argument("out_json", help="Output json path, e.g. music_index.json")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    out = Path(args.out_json).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Root does not exist: {root}")

    result = scan_folder(root)
    # Compact JSON substantially reduces serialization and disk-write time for
    # large libraries while remaining fully compatible with the existing reader.
    out.write_text(json.dumps(result["items"], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    stats_path = out.with_suffix(".stats.json")
    stats_path.write_text(
        json.dumps(
            {k: result[k] for k in ["root", "scanned_supported", "skipped_no_duration", "indexed", "ext_counts"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("====== 掃描完成 (SAFE) ======")
    print(f"Root: {result['root']}")
    print(f"掃描到支援格式檔案: {result['scanned_supported']}")
    print(f"缺 duration 而跳過: {result['skipped_no_duration']}")
    print(f"寫入 index 筆數: {result['indexed']}")
    print(f"輸出 index: {out}")
    print(f"統計檔: {stats_path}")


if __name__ == "__main__":
    main()
