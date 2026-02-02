#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
playlist_scan_safe.py

Build a robust music_index.json that *does not drop files* just because tags are missing.
Priority for metadata:
  0) easy tags (mutagen File(..., easy=True))
  1) raw tags (mutagen File(..., easy=False)) for formats where easy tags are empty (common with AIFF/AIFC)
  2) filename-derived title
  3) path-derived artist guess (weak signal; only a fallback)

Each index item includes:
  - path: absolute path
  - duration: int seconds
  - title: string or None
  - artist: string or None
  - meta_source: "easy_tag" | "raw_tag" | "filename" | "path_guess" | "none"

This scanner is designed for messy folder structures — it does NOT assume Artist/Album layout.
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from mutagen import File

SUPPORTED_EXTS = {
    ".flac", ".alac", ".m4a", ".mp4", ".aac", ".mp3", ".ogg", ".opus", ".wav", ".aif", ".aiff", ".aifc", ".ape", ".wv", ".dsf", ".dff"
}

GENERIC_PATH_TOKENS = {
    "music", "itunes", "itunes media", "media", "hi-res", "hires", "lossless", "lossy",
    "downloads", "download", "album", "albums", "disc", "cd", "cd1", "cd2", "cd3",
    "deluxe", "edition", "remaster", "remastered", "single", "singles", "ep", "compilations",
    "various artists", "va", "unknown", "unknown artist"
}

TRACK_PREFIX_RE = re.compile(r"^\s*(\(?\d{1,3}\)?[\s._-]+)+", re.UNICODE)

def clean_filename_title(stem: str) -> str:
    s = stem.strip()
    s = TRACK_PREFIX_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_token(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())

def guess_artist_from_path(path: Path) -> Optional[str]:
    parts = list(path.parts)
    if parts:
        parts = parts[:-1]  # drop filename
    for p in reversed(parts):
        pt = p.strip()
        if not pt:
            continue
        nt = normalize_token(pt)
        if nt in GENERIC_PATH_TOKENS:
            continue
        if re.fullmatch(r"\d+", pt):
            continue
        if len(pt) <= 2:
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
            try:
                return v.decode("utf-8", "ignore")
            except Exception:
                return None
        return str(v)
    except Exception:
        return None

def read_easy_tags(audio) -> Tuple[Optional[str], Optional[str]]:
    title = _first(audio.get("title"))
    artist = _first(audio.get("artist"))
    if not artist:
        artist = _first(audio.get("albumartist"))
    return title, artist

def read_raw_tags(audio) -> Tuple[Optional[str], Optional[str]]:
    tags = getattr(audio, "tags", None)
    if not tags:
        return None, None

    def get_any(keys):
        for k in keys:
            if k in tags:
                v = tags.get(k)
                if isinstance(v, list):
                    return _first(v)
                try:
                    return str(v)
                except Exception:
                    continue
        return None

    title = get_any(["TIT2", "TITLE", "\xa9nam", "©nam"])
    artist = get_any(["TPE1", "ARTIST", "\xa9ART", "©ART"])
    if not artist:
        artist = get_any(["TPE2", "ALBUMARTIST", "aART", "\xa9aRT", "©aRT"])
    return title, artist

def get_duration_seconds(audio) -> Optional[int]:
    try:
        info = getattr(audio, "info", None)
        if info and getattr(info, "length", None):
            return int(round(float(info.length)))
    except Exception:
        pass
    return None

def scan_folder(root: Path):
    items = []
    scanned = 0
    skipped_no_duration = 0

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext not in SUPPORTED_EXTS:
                continue
            scanned += 1
            p = Path(dirpath) / fn

            dur = None
            title = None
            artist = None
            meta_source = "none"

            audio_easy = None
            try:
                audio_easy = File(str(p), easy=True)
            except Exception:
                audio_easy = None

            if audio_easy:
                dur = get_duration_seconds(audio_easy)
                t, a = read_easy_tags(audio_easy)
                if t or a:
                    title, artist = t, a
                    meta_source = "easy_tag"

            if dur is None or meta_source == "none":
                audio_raw = None
                try:
                    audio_raw = File(str(p), easy=False)
                except Exception:
                    audio_raw = None
                if audio_raw:
                    if dur is None:
                        dur = get_duration_seconds(audio_raw)
                    if meta_source == "none":
                        t, a = read_raw_tags(audio_raw)
                        if t or a:
                            title, artist = t, a
                            meta_source = "raw_tag"

            if dur is None:
                skipped_no_duration += 1
                continue

            if not title:
                title = clean_filename_title(p.stem)
                if meta_source == "none":
                    meta_source = "filename"

            if not artist:
                ag = guess_artist_from_path(p)
                if ag:
                    artist = ag
                    if meta_source in ("filename", "none"):
                        meta_source = "path_guess"

            items.append({
                "path": str(p),
                "duration": int(dur),
                "title": title,
                "artist": artist,
                "meta_source": meta_source,
            })

    return {
        "root": str(root),
        "scanned_supported": scanned,
        "skipped_no_duration": skipped_no_duration,
        "indexed": len(items),
        "items": items
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

    out.write_text(json.dumps(result["items"], ensure_ascii=False, indent=2), encoding="utf-8")

    stats_path = out.with_suffix(".stats.json")
    stats_path.write_text(
        json.dumps(
            {k: result[k] for k in ["root", "scanned_supported", "skipped_no_duration", "indexed"]},
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


def scan_multiple_roots(roots):
    """Scan multiple roots and return combined items + stats."""
    combined = []
    stats = {
        "roots": [],
        "scanned_supported": 0,
        "skipped_no_duration": 0,
        "indexed": 0,
    }
    for r in roots:
        res = scan_folder(Path(r).expanduser().resolve())
        stats["roots"].append(res["root"])
        stats["scanned_supported"] += int(res.get("scanned_supported", 0))
        stats["skipped_no_duration"] += int(res.get("skipped_no_duration", 0))
        combined.extend(res["items"])
    stats["indexed"] = len(combined)
    return {"items": combined, "stats": stats}

if __name__ == "__main__":
    main()
