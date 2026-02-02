import os, sys, json, re, csv


DUR_TOL_DEFAULT = 2  # seconds tolerance, DAP-style


# -------- normalization / parsing --------

_REMOVE_PARENS = re.compile(r"[\(\[\{].*?[\)\]\}]")
_FEAT = re.compile(r"\b(feat\.|ft\.)\b", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"\s+")
_DASHES = re.compile(r"[–—]")  # en/em dash
_BAD_PUNCT = re.compile(r"[·•|]")

def norm(s: str | None) -> str | None:
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

def tokens(s: str | None) -> set[str]:
    if not s:
        return set()
    # split on spaces and some punctuation
    parts = re.split(r"[ \t/\\\-:,;.!?]+", s)
    return {p for p in parts if p}

def jaccard(a: str | None, b: str | None) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0

def parse_extinf(line: str):
    """
    returns: (duration:int|None, display:str|None)
    """
    m = re.match(r"#EXTINF:(-?\d+)\s*,\s*(.*)$", line.strip())
    if not m:
        return None, None
    dur = int(m.group(1))
    disp = m.group(2).strip()
    return dur, disp

def candidate_pairs_from_display(disp: str):
    """
    Parse #EXTINF display into candidate (title, artist) pairs.

    Supports:
      - "Title - Artist"
      - "Artist - Title"
      - Multi-dash exports like:
          "6lack - Loaded Gun (AKE RMX) - AKE"
          "Arabic Flavor Music x Namu Serpentard - PSG - LiteFeet PSG"

    Safe approach:
      - Normalize dashes (–/— -> -)
      - Split on hyphen with optional surrounding spaces
      - For 2-part: return both orientations
      - For >=3 parts: generate a small, conservative set:
          A) artist - title - extra...   => (title=parts[1:], artist=parts[0]) and (title=parts[1], artist=parts[0])
          B) title - extra... - artist  => (title=parts[:-1], artist=parts[-1])
      - Add title-only fallback (artist=None) for later low-confidence tiers (still gated by duration/similarity).
    """
    if not disp:
        return []

    disp2 = disp.replace("–", "-").replace("—", "-").strip()
    raw_parts = [p.strip() for p in re.split(r"\s+-\s+", disp2) if p.strip()]
    parts = [norm(p) for p in raw_parts]
    parts = [p for p in parts if p]
    if not parts:
        return []

    pairs = []

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
    out = []
    for t, a in pairs:
        key = (t, a)
        if not t or key in seen:
            continue
        seen.add(key)
        out.append((t, a))
    return out

# -------- build index (fast lookup by duration bucket) --------



def repair_playlist(
    playlist_path: str,
    index_path: str,
    output_path: str,
    report_path: str = "repair_report.csv",
    dur_tol: int = DUR_TOL_DEFAULT,
    verbose: bool = False,
):
    """Repair a playlist using a pre-built music index (import-safe)."""
    with open(index_path, "r", encoding="utf-8") as f:
        music_index = json.load(f)

    # bucket by duration for quick narrowing
    by_dur = {}  # int -> list[dict]
    for it in music_index:
        title = norm(it.get("title"))
        artist = norm(it.get("artist"))
        dur = it.get("duration")
        path = it.get("path")
        if not title or not artist or dur is None or not path:
            continue
        by_dur.setdefault(int(dur), []).append({
            "title": title,
            "artist": artist,
            "duration": int(dur),
            "path": path
        })

    def find_matches(title_n: str | None, artist_n: str | None, dur: int):
        """
        DAP-style matching:
        Stage 1: exact title+artist within duration tolerance
        Stage 2: token-similarity title+artist within duration tolerance
        Stage 3: title-only within duration tolerance (only if artist unknown)
        """
        cand = []
        for d in range(dur - dur_tol, dur + dur_tol + 1):
            cand.extend(by_dur.get(d, []))

        if not cand or not title_n:
            return []

        # Stage 1: exact (normalized) match
        exact = []
        for s in cand:
            if s["title"] == title_n and (artist_n is None or s["artist"] == artist_n):
                exact.append(s)
        if len(exact) == 1:
            return exact
        if len(exact) > 1:
            return exact  # ambiguous, let caller decide

        # Stage 2: fuzzy title + artist (Jaccard on tokens)
        fuzzy = []
        for s in cand:
            if artist_n is not None:
                if s["artist"] != artist_n:
                    continue
                if jaccard(s["title"], title_n) >= 0.85:
                    fuzzy.append(s)
            else:
                # no artist: require stronger title similarity
                if jaccard(s["title"], title_n) >= 0.90:
                    fuzzy.append(s)

        return fuzzy

    # -------- repair playlist --------

    total = kept = repaired = ambiguous = failed = 0
    out_lines = []
    report_rows = []

    with open(playlist_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        out_lines.append(line)

        if line.startswith("#EXTINF") and i + 1 < len(lines):
            total += 1

            dur, disp = parse_extinf(line)
            original_path = lines[i + 1].rstrip("\n")

            # always write the path line once (either original or repaired)
            # but first decide what it should be
            if os.path.exists(original_path):
                out_lines.append(original_path)
                kept += 1
                report_rows.append(["KEPT", dur, disp, original_path, original_path, ""])
                i += 2
                continue

            # if EXTINF duration missing or -1, we can't do duration matching safely
            if dur is None or dur < 0 or not disp:
                out_lines.append(original_path)
                failed += 1
                report_rows.append(["FAILED_NO_EXTINF", dur, disp, original_path, original_path, "no duration or display"])
                i += 2
                continue

            pairs = candidate_pairs_from_display(disp)
            all_matches = []

            # Try each possible (title,artist) orientation, collect matches
            for (t, a) in pairs:
                ms = find_matches(t, a, dur)
                if ms:
                    # keep distinct by path
                    seen = {m["path"] for m in all_matches}
                    for m in ms:
                        if m["path"] not in seen:
                            all_matches.append(m)

            # If still nothing, fallback: try title-only (take whichever side looks more "song-like")
            if not all_matches and pairs:
                # choose the shorter side as title heuristic (often title shorter than artist+title)
                for (t, a) in pairs:
                    ms = find_matches(t, None, dur)
                    if ms:
                        seen = {m["path"] for m in all_matches}
                        for m in ms:
                            if m["path"] not in seen:
                                all_matches.append(m)

            if len(all_matches) == 1:
                new_path = all_matches[0]["path"]
                out_lines.append(new_path)
                repaired += 1
                report_rows.append(["REPAIRED", dur, disp, original_path, new_path, ""])
            elif len(all_matches) > 1:
                out_lines.append(original_path)
                ambiguous += 1
                # include top few candidates in notes
                cand_note = " | ".join(m["path"] for m in all_matches[:5])
                report_rows.append(["AMBIGUOUS", dur, disp, original_path, original_path, cand_note])
            else:
                out_lines.append(original_path)
                failed += 1
                report_rows.append(["FAILED", dur, disp, original_path, original_path, "no match"])

            i += 2
        else:
            i += 1

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    with open(report_path, "w", encoding="utf-8", newline="") as rf:
        w = csv.writer(rf)
        w.writerow(["status", "extinf_duration", "extinf_display", "original_path", "written_path", "notes"])
        w.writerows(report_rows)

    if verbose:
        print("====== 修復完成 (DAP-style) ======")
    if verbose:
        print(f"歌單歌曲總數: {total}")
    if verbose:
        print(f"原路徑可用: {kept}")
    if verbose:
        print(f"自動修復成功: {repaired}")
    if verbose:
        print(f"多筆命中未修: {ambiguous}")
    if verbose:
        print(f"修復失敗: {failed}")
    if verbose:
        print(f"輸出歌單: {output_path}")
    if verbose:
        print(f"報告檔: {report_path}")

    return {
        "total": int(total),
        "kept": int(kept),
        "repaired": int(repaired),
        "ambiguous": int(ambiguous),
        "failed": int(failed),
        "playlist_path": str(playlist_path),
        "output_path": str(output_path),
        "report_path": str(report_path),
    }


def main():
    import sys
    if len(sys.argv) < 4:
        raise SystemExit("Usage: python repair_playlist_safe_v4.py <playlist.m3u> <music_index.json> <fixed.m3u> <repair_report.csv>")
    playlist_path = sys.argv[1]
    index_path = sys.argv[2]
    output_path = sys.argv[3]
    report_path = sys.argv[4] if len(sys.argv) >= 5 else "repair_report.csv"
    repair_playlist(playlist_path, index_path, output_path, report_path, dur_tol=DUR_TOL_DEFAULT, verbose=True)

if __name__ == "__main__":
    main()
