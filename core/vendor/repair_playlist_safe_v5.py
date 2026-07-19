#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_playlist_safe_v5.py

v5 goals:
- Keep v4 behavior for #EXTINF playlists (duration-based DAP-style matching)
- Add support for playlists WITHOUT #EXTINF (e.g., Roon exports):
    * treat each non-comment line as a path entry
    * if path exists => KEPT
    * else attempt repair by filename/title + optional artist guess from path + (optional) format policy
    * if 1 match => REPAIRED_PATH
    * if >1 => AMBIGUOUS_PATH (do not auto pick)
    * else FAILED_PATH

Report CSV columns are made compatible with your runner/exporter:
  row_index, status, extinf_line, extinf_duration, extinf_display,
  original_path, written_path, notes
"""

import os
import json
import re
import csv
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

DUR_TOL_DEFAULT = 2  # seconds tolerance, DAP-style

# -------- normalization / parsing --------

_REMOVE_PARENS = re.compile(r"[\(\[\{].*?[\)\]\}]")
_FEAT = re.compile(r"\b(feat\.|ft\.)\b", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"\s+")
_DASHES = re.compile(r"[–—]")  # en/em dash
_BAD_PUNCT = re.compile(r"[·•|]")

def norm(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    s = _DASHES.sub("-", s)
    # normalize apostrophes/quotes (straight + curly) so "He’s" == "He's" == "Hes"
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    s = s.replace("'", "")
    s = _BAD_PUNCT.sub(" ", s)
    s = s.replace("_", " ")
    s = s.replace("\u3000", " ")  # full-width space
    s = s.lower()
    # keep feat content, but normalize token
    s = _FEAT.sub("feat", s)
    # remove bracketed qualifiers: (remastered), [explicit], etc.
    s = _REMOVE_PARENS.sub("", s)
    s = _MULTI_SPACE.sub(" ", s).strip()
    return s or None

def tokens(s: Optional[str]) -> set[str]:
    if not s:
        return set()
    parts = re.split(r"[ \t/\\\-:,;.!?]+", s)
    return {p for p in parts if p}

def jaccard(a: Optional[str], b: Optional[str]) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0

def parse_extinf(line: str) -> Tuple[Optional[int], Optional[str]]:
    """
    returns: (duration:int|None, display:str|None)
    """
    m = re.match(r"#EXTINF:(-?\d+)\s*,\s*(.*)$", line.strip())
    if not m:
        return None, None
    dur = int(m.group(1))
    disp = m.group(2).strip()
    return dur, disp

def candidate_pairs_from_display(disp: str) -> List[Tuple[str, Optional[str]]]:
    """
    Parse #EXTINF display into candidate (title, artist) pairs.
    Supports:
      - "Title - Artist"
      - "Artist - Title"
      - Multi-dash exports like:
          "6lack - Loaded Gun (AKE RMX) - AKE"
          "Arabic Flavor Music x Namu Serpentard - PSG - LiteFeet PSG"
    """
    if not disp:
        return []

    disp2 = disp.replace("–", "-").replace("—", "-").strip()
    raw_parts = [p.strip() for p in re.split(r"\s+-\s+", disp2) if p.strip()]
    parts = [norm(p) for p in raw_parts]
    parts = [p for p in parts if p]
    if not parts:
        return []

    pairs: List[Tuple[str, Optional[str]]] = []

    if len(parts) == 1:
        pairs.append((parts[0], None))
    elif len(parts) == 2:
        a, b = parts
        pairs.append((a, b))
        pairs.append((b, a))
    else:
        # Pattern A: artist - title - extra...
        pairs.append((parts[1], parts[0]))
        pairs.append((" - ".join(parts[1:]), parts[0]))

        # Pattern B: title - extra... - artist
        pairs.append((" - ".join(parts[:-1]), parts[-1]))

        # Title-only fallbacks
        pairs.append((" - ".join(parts), None))
        pairs.append((" - ".join(parts[:-1]), None))
        pairs.append((parts[1], None))

    # De-dup while preserving order
    seen = set()
    out: List[Tuple[str, Optional[str]]] = []
    for t, a in pairs:
        key = (t, a)
        if not t or key in seen:
            continue
        seen.add(key)
        out.append((t, a))
    return out

# -------- format policy --------

def apply_format_policy(
    matches: List[dict],
    mode: str = "none",
    prefer: Optional[List[str]] = None,
    strict_ext: Optional[str] = None,
) -> List[dict]:
    """
    Shrink the candidate set by format policy. Does NOT pick a single track if still ambiguous.

    mode:
      - "none": do nothing
      - "strict": keep only strict_ext (e.g. ".flac"); if none remain => []
      - "fallback": keep only the best-ranked ext group from prefer list
    """
    if not matches or not mode or mode == "none":
        return matches

    def ext_of(m: dict) -> str:
        return (m.get("ext") or os.path.splitext(m.get("path", ""))[1] or "").lower()

    if mode == "strict":
        if not strict_ext:
            return matches
        want = strict_ext.lower()
        return [m for m in matches if ext_of(m) == want]

    if mode == "fallback":
        if not prefer:
            return matches
        order = {e.lower(): i for i, e in enumerate(prefer)}

        def rank(m: dict) -> int:
            return order.get(ext_of(m), 10_000)

        matches2 = sorted(matches, key=rank)
        best = rank(matches2[0])
        return [m for m in matches2 if rank(m) == best]

    return matches

# -------- helpers for non-EXTINF playlists --------

def guess_artist_from_path_str(p: str) -> Optional[str]:
    """
    Heuristic: take the last non-trivial folder name as artist guess.
    (Works well when folder structure is .../Artist/Album/track.ext)
    """
    try:
        path = Path(p)
        parts = list(path.parts[:-1])  # drop filename
        for seg in reversed(parts):
            seg = str(seg).strip()
            if not seg:
                continue
            low = seg.lower()
            if low in ("music", "downloads", "download", "album", "albums", "disc", "cd", "cd1", "cd2", "cd3",
                       "various artists", "va", "unknown", "unknown artist"):
                continue
            if re.fullmatch(r"\d+", seg):
                continue
            if re.fullmatch(r"(19|20)\d{2}", seg):
                continue
            if len(seg) <= 2:
                continue
            return seg
    except Exception:
        return None
    return None

def title_from_filename(p: str) -> str:
    try:
        stem = Path(p).stem
    except Exception:
        stem = p
    stem = re.sub(r"^\s*(\(?\d{1,3}\)?[\s._-]+)+", "", stem).strip()  # leading track numbers
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem

def build_indexes(music_index: list) -> Tuple[Dict[int, List[dict]], Dict[str, List[dict]]]:
    """
    by_dur: duration -> items (for EXTINF mode)
    by_title: normalized title -> items (for non-EXTINF mode)
    Only keep items with path + duration for by_dur.
    For by_title, duration can be None; but we keep it if present.
    """
    by_dur: Dict[int, List[dict]] = {}
    by_title: Dict[str, List[dict]] = {}

    for it in music_index:
        path = it.get("path")
        if not path:
            continue
        ext = os.path.splitext(path)[1].lower()

        title_raw = it.get("title")
        artist_raw = it.get("artist")
        title_n = norm(title_raw) if title_raw is not None else None
        artist_n = norm(artist_raw) if artist_raw is not None else None

        dur = it.get("duration", None)
        dur_i: Optional[int] = None
        try:
            if dur is not None:
                dur_i = int(dur)
        except Exception:
            dur_i = None

        item = {
            "title": title_n,
            "artist": artist_n,
            "duration": dur_i,
            "path": path,
            "ext": ext,
            "album": norm(it.get("album")) if it.get("album") else None,
            "disc": it.get("disc"),
            "track": it.get("track"),
        }

        # by_dur needs duration + title (and ideally artist)
        if title_n and dur_i is not None:
            by_dur.setdefault(dur_i, []).append(item)

        # by_title for path-only mode
        if title_n:
            by_title.setdefault(title_n, []).append(item)

    return by_dur, by_title



def norm_path_parts(p: str) -> List[str]:
    p = (p or "").replace("\\", "/")
    parts = [norm(x) for x in p.split("/") if x not in ("", ".", "..")]
    return [x for x in parts if x]


def suffix_similarity(a: str, b: str) -> float:
    pa, pb = norm_path_parts(a), norm_path_parts(b)
    if not pa or not pb:
        return 0.0
    same = 0
    for x, y in zip(reversed(pa), reversed(pb)):
        if x == y:
            same += 1
        else:
            break
    return same / max(1, min(len(pa), len(pb)))


def parse_intish(value: Any) -> Optional[int]:
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def parse_roon_m3u_path(orig_path: str) -> Dict[str, Any]:
    parts = [x for x in (orig_path or "").replace("\\", "/").split("/") if x not in ("", ".", "..")]
    filename = parts[-1] if parts else orig_path
    artist = parts[-3] if len(parts) >= 3 else ""
    album = parts[-2] if len(parts) >= 2 else ""
    stem = Path(filename).stem
    m = re.match(r"^\s*(\d{1,2})[-_. ](\d{1,3})\s+(.+)$", stem)
    disc = track = None
    title = title_from_filename(filename)
    if m:
        disc, track, title = int(m.group(1)), int(m.group(2)), m.group(3).strip()
    return {
        "source": "roon_m3u",
        "artist": artist,
        "album_artist": artist,
        "album": album,
        "disc": disc,
        "track": track,
        "title": title,
    }


def score_roon_candidate(meta: Dict[str, Any], orig_path: str, item: dict) -> Tuple[float, List[str]]:
    title_q = norm(str(meta.get("title") or title_from_filename(orig_path)))
    artist_q = norm(str(meta.get("artist") or meta.get("album_artist") or ""))
    album_q = norm(str(meta.get("album") or ""))
    item_title = norm(str(item.get("title") or title_from_filename(str(item.get("path", "")))))
    item_artist = norm(str(item.get("artist") or guess_artist_from_path_str(str(item.get("path", ""))) or ""))
    item_path = str(item.get("path", ""))

    score = 0.0
    reasons: List[str] = []
    ts = jaccard(title_q, item_title) if title_q and item_title else 0.0
    if title_q and item_title and title_q == item_title:
        score += 58; reasons.append("title exact")
    elif ts >= 0.92:
        score += 51; reasons.append("title close")
    elif ts >= 0.78:
        score += 38; reasons.append("title fuzzy")
    else:
        return 0.0, []

    if artist_q and item_artist:
        artists = [norm(x) for x in re.split(r"\s*/\s*|\s*;\s*|\s*,\s*", str(meta.get("artist") or meta.get("album_artist") or ""))]
        artists = [x for x in artists if x]
        if artist_q == item_artist or item_artist in artists:
            score += 25; reasons.append("artist exact")
        elif max([jaccard(x, item_artist) for x in artists] or [0]) >= 0.8:
            score += 18; reasons.append("artist close")

    path_score = suffix_similarity(orig_path, item_path)
    if path_score >= 0.66:
        score += 22; reasons.append("path suffix")
    elif path_score >= 0.4:
        score += 12; reasons.append("path tail")

    if album_q:
        path_parts = norm_path_parts(item_path)
        if album_q in path_parts:
            score += 15; reasons.append("album folder")
        elif any(jaccard(album_q, x) >= 0.82 for x in path_parts[-4:]):
            score += 9; reasons.append("album close")

    track_q = parse_intish(meta.get("track"))
    disc_q = parse_intish(meta.get("disc"))
    filename = Path(item_path).stem
    nums = [int(x) for x in re.findall(r"\d+", filename[:12])]
    if track_q is not None and track_q in nums:
        score += 7; reasons.append("track number")
    if disc_q is not None and nums and nums[0] == disc_q:
        score += 3; reasons.append("disc number")
    return score, reasons

# -------- main repair --------

def repair_playlist(
    playlist_path: str,
    index_path: str,
    output_path: str,
    report_path: str = "repair_report.csv",
    dur_tol: int = DUR_TOL_DEFAULT,
    verbose: bool = False,
    format_mode: str = "none",                     # "none" | "strict" | "fallback"
    format_priority_list: Optional[List[str]] = None, # e.g. [".flac",".alac",".m4a",".mp3"]
    strict_ext: Optional[str] = None,                # e.g. ".flac"
    allowed_roots: Optional[List[str]] = None,       # existing paths are kept only inside these roots
):
    """Repair a playlist using a pre-built music index (import-safe)."""
    with open(index_path, "r", encoding="utf-8") as f:
        music_index = json.load(f)

    by_dur, by_title = build_indexes(music_index)

    def path_is_in_allowed_roots(path_value: str) -> bool:
        """Return True when path_value belongs to the active repair scope.

        When no explicit roots are supplied, retain the legacy behavior and
        allow any existing path. Windows paths are compared case-insensitively.
        """
        if not allowed_roots:
            return True

        import ntpath

        try:
            candidate = ntpath.normcase(ntpath.abspath(ntpath.normpath(path_value)))
        except Exception:
            return False

        for root_value in allowed_roots:
            try:
                root = ntpath.normcase(ntpath.abspath(ntpath.normpath(str(root_value))))
                if ntpath.commonpath([candidate, root]) == root:
                    return True
            except (ValueError, OSError, TypeError):
                continue
        return False

    def should_keep_existing_path(path_value: str) -> bool:
        return os.path.exists(path_value) and path_is_in_allowed_roots(path_value)

    def find_matches_extinf(title_n: Optional[str], artist_n: Optional[str], dur: int) -> List[dict]:
        """
        DAP-style matching:
        Stage 1: exact title+artist within duration tolerance
        Stage 2: token-similarity title+artist within duration tolerance
        Stage 3: title-only within duration tolerance (only if artist unknown)
        """
        cand: List[dict] = []
        for d in range(dur - dur_tol, dur + dur_tol + 1):
            cand.extend(by_dur.get(d, []))

        if not cand or not title_n:
            return []

        # Stage 1: exact (normalized) match
        exact: List[dict] = []
        for s in cand:
            if s["title"] == title_n and (artist_n is None or s["artist"] == artist_n):
                exact.append(s)
        if exact:
            return exact

        # Stage 2: fuzzy title + artist (Jaccard on tokens)
        fuzzy: List[dict] = []
        for s in cand:
            if artist_n is not None:
                if s["artist"] != artist_n:
                    continue
                if jaccard(s["title"], title_n) >= 0.85:
                    fuzzy.append(s)
            else:
                if jaccard(s["title"], title_n) >= 0.90:
                    fuzzy.append(s)

        return fuzzy

    def find_matches_path_only(orig_path: str) -> List[dict]:
        """
        Non-EXTINF mode: we don't have duration, so we use:
        - title guess from filename stem
        - optional artist guess from folder
        Strategy:
          1) exact normalized title match
          2) if artist guess exists: prefer same-artist subset
          3) if still many: try higher jaccard threshold on title (against candidates' title tokens)
        """
        title_guess = title_from_filename(orig_path)
        title_n = norm(title_guess)
        if not title_n:
            return []

        cands = list(by_title.get(title_n, []))

        # If no exact title bucket, try fuzzy across all titles (bounded by jaccard)
        if not cands:
            # WARNING: could be heavy on huge indexes; we keep it conservative
            # Only do fuzzy if the guessed title has enough tokens
            tg_tokens = tokens(title_n)
            if len(tg_tokens) < 2:
                return []
            fuzzy: List[dict] = []
            for tkey, items in by_title.items():
                if jaccard(tkey, title_n) >= 0.92:
                    fuzzy.extend(items)
            cands = fuzzy

        if not cands:
            return []

        artist_guess = guess_artist_from_path_str(orig_path)
        artist_n = norm(artist_guess) if artist_guess else None

        if artist_n:
            same_artist = [m for m in cands if (m.get("artist") == artist_n)]
            if same_artist:
                cands = same_artist

        # Apply format policy to shrink ambiguity
        cands = apply_format_policy(
            cands,
            mode=format_mode,
            prefer=format_priority_list,
            strict_ext=strict_ext,
        )

        # De-dup by path
        seen = set()
        out: List[dict] = []
        for m in cands:
            p = m.get("path")
            if not p or p in seen:
                continue
            seen.add(p)
            out.append(m)
        return out

    def find_matches_roon(orig_path: str, meta: Optional[Dict[str, Any]] = None) -> Tuple[List[dict], str]:
        query = dict(meta or parse_roon_m3u_path(orig_path))
        scored: List[Tuple[float, dict, List[str]]] = []
        for item in music_index:
            if not item.get("path"):
                continue
            score, reasons = score_roon_candidate(query, orig_path, item)
            if score > 0:
                scored.append((score, item, reasons))
        if not scored:
            return [], "no Roon metadata match"
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][0]
        # Auto only with strong confidence and a clear lead. Otherwise surface candidates.
        threshold = 78.0
        close = [x for x in scored if x[0] >= max(threshold - 8, best - 7)]
        if best >= threshold and (len(scored) == 1 or best - scored[1][0] >= 8):
            item = dict(scored[0][1])
            item["_match_reason"] = f"Roon match {best:.0f}: " + ", ".join(scored[0][2])
            return [item], item["_match_reason"]
        out = []
        for score, item, reasons in close[:10]:
            obj = dict(item)
            obj["_match_reason"] = f"{score:.0f}: " + ", ".join(reasons)
            out.append(obj)
        return out, f"Roon candidates; best score {best:.0f}"

    with open(playlist_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        lines = f.readlines()

    # Detect if playlist has any EXTINF lines
    has_extinf = any(l.lstrip().startswith("#EXTINF") for l in lines)

    out_lines: List[str] = []
    report_rows: List[List[str]] = []

    total = kept = repaired = ambiguous = failed = 0

    def add_report(
        row_index: int,
        status: str,
        extinf_line: str,
        extinf_duration: str,
        extinf_display: str,
        original_path: str,
        written_path: str,
        notes: str,
    ):
        report_rows.append([
            str(row_index),
            status,
            extinf_line or "",
            extinf_duration or "",
            extinf_display or "",
            original_path or "",
            written_path or "",
            notes or "",
        ])

    if has_extinf:
        i = 0
        row_index = 0
        while i < len(lines):
            line = lines[i].rstrip("\n")
            out_lines.append(line)

            if line.startswith("#EXTINF") and i + 1 < len(lines):
                total += 1
                dur, disp = parse_extinf(line)
                original_path = lines[i + 1].rstrip("\n")

                if should_keep_existing_path(original_path):
                    out_lines.append(original_path)
                    kept += 1
                    add_report(row_index, "KEPT", line, str(dur) if dur is not None else "", disp or "",
                               original_path, original_path, "")
                    row_index += 1
                    i += 2
                    continue

                if dur is None or dur < 0 or not disp:
                    out_lines.append(original_path)
                    failed += 1
                    add_report(row_index, "FAILED_NO_EXTINF", line, str(dur) if dur is not None else "", disp or "",
                               original_path, original_path, "no duration or display")
                    row_index += 1
                    i += 2
                    continue

                pairs = candidate_pairs_from_display(disp)
                all_matches: List[dict] = []

                for (t, a) in pairs:
                    ms = find_matches_extinf(t, a, dur)
                    if ms:
                        seen = {m["path"] for m in all_matches}
                        for m in ms:
                            if m["path"] not in seen:
                                all_matches.append(m)

                if not all_matches and pairs:
                    for (t, _a) in pairs:
                        ms = find_matches_extinf(t, None, dur)
                        if ms:
                            seen = {m["path"] for m in all_matches}
                            for m in ms:
                                if m["path"] not in seen:
                                    all_matches.append(m)

                all_matches = apply_format_policy(
                    all_matches,
                    mode=format_mode,
                    prefer=format_priority_list,
                    strict_ext=strict_ext,
                )

                if len(all_matches) == 1:
                    new_path = all_matches[0]["path"]
                    out_lines.append(new_path)
                    repaired += 1
                    add_report(row_index, "REPAIRED", line, str(dur), disp or "",
                               original_path, new_path, "")
                elif len(all_matches) > 1:
                    out_lines.append(original_path)
                    ambiguous += 1
                    cand_note = "candidates: " + " | ".join(m["path"] for m in all_matches[:10])
                    add_report(row_index, "AMBIGUOUS", line, str(dur), disp or "",
                               original_path, original_path, cand_note)
                else:
                    out_lines.append(original_path)
                    failed += 1
                    note = "no match"
                    if format_mode in ("strict", "fallback"):
                        note = f"no match after format_policy({format_mode})"
                    add_report(row_index, "FAILED", line, str(dur), disp or "",
                               original_path, original_path, note)

                row_index += 1
                i += 2
            else:
                i += 1

    else:
        # No EXTINF: path-per-line mode
        row_index = 0
        pending_roon_meta: Optional[Dict[str, Any]] = None
        is_roon_source = any(l.startswith("#PLAYLISTFIXER_SOURCE:ROON_XLSX") for l in lines)
        for raw in lines:
            line = raw.rstrip("\n")

            if line.startswith("#ROONMETA:"):
                try:
                    pending_roon_meta = json.loads(line.split(":", 1)[1])
                except Exception:
                    pending_roon_meta = None
                continue

            # Keep ordinary header/comments as-is, but omit internal annotations.
            if not line.strip() or line.lstrip().startswith("#"):
                if not line.startswith("#PLAYLISTFIXER_SOURCE:"):
                    out_lines.append(line)
                continue

            total += 1
            original_path = line

            if should_keep_existing_path(original_path):
                out_lines.append(original_path)
                kept += 1
                add_report(row_index, "KEPT_PATH", "", "", "",
                           original_path, original_path, "")
                row_index += 1
                continue

            roon_like = pending_roon_meta is not None or is_roon_source or original_path.replace("\\", "/").startswith("../")
            if roon_like:
                matches, match_note = find_matches_roon(original_path, pending_roon_meta)
            else:
                matches = find_matches_path_only(original_path)
                match_note = "filename/title match"
            pending_roon_meta = None

            if len(matches) == 1:
                new_path = matches[0]["path"]
                out_lines.append(new_path)
                repaired += 1
                reason = matches[0].get("_match_reason") or match_note
                add_report(row_index, "REPAIRED_PATH", "", "", "",
                           original_path, new_path, reason)
            elif len(matches) > 1:
                out_lines.append(original_path)
                ambiguous += 1
                cand_note = "candidates: " + " | ".join(m["path"] for m in matches[:10])
                details = " || ".join(m.get("_match_reason", "") for m in matches[:10] if m.get("_match_reason"))
                if details:
                    cand_note += " || match details: " + details
                add_report(row_index, "AMBIGUOUS_PATH", "", "", "",
                           original_path, original_path, cand_note)
            else:
                out_lines.append(original_path)
                failed += 1
                note = "no match (no EXTINF)"
                if format_mode in ("strict", "fallback"):
                    note = f"no match after format_policy({format_mode}) (no EXTINF)"
                add_report(row_index, "FAILED_PATH", "", "", "",
                           original_path, original_path, note)

            row_index += 1

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    with open(report_path, "w", encoding="utf-8", newline="") as rf:
        w = csv.writer(rf)
        w.writerow([
            "row_index",
            "status",
            "extinf_line",
            "extinf_duration",
            "extinf_display",
            "original_path",
            "written_path",
            "notes",
        ])
        w.writerows(report_rows)

    if verbose:
        print("====== 修復完成 (SAFE v5) ======")
        print(f"playlist: {playlist_path}")
        print(f"模式: {'EXTINF' if has_extinf else 'PATH_ONLY'}")
        print(f"歌單歌曲總數: {total}")
        print(f"原路徑可用: {kept}")
        print(f"自動修復成功: {repaired}")
        print(f"多筆命中未修: {ambiguous}")
        print(f"修復失敗: {failed}")
        print(f"輸出歌單: {output_path}")
        print(f"報告檔: {report_path}")

    return {
        "total": int(total),
        "kept": int(kept),
        "repaired": int(repaired),
        "ambiguous": int(ambiguous),
        "failed": int(failed),
        "mode": "extinf" if has_extinf else "path_only",
        "playlist_path": str(playlist_path),
        "output_path": str(output_path),
        "report_path": str(report_path),
    }
