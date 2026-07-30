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
import ntpath
import json
import re
import csv
import difflib
import io
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional, List, Dict, Tuple, Any, Set
from dataclasses import dataclass, field, replace

try:
    from mutagen import File as MutagenFile
except Exception:
    MutagenFile = None

DUR_TOL_DEFAULT = 2  # seconds tolerance, DAP-style
MATCH_ENGINE_BUILD = "2026-07-30-xlsx-artist-12"

# One prepared candidate context is shared by every playlist in the same repair
# session. The key includes the index fingerprint and enabled roots, so changing
# either automatically invalidates it without affecting matching behavior.
_REPAIR_CONTEXT_LOCK = threading.Lock()
_REPAIR_CONTEXT_CACHE: Dict[str, Any] = {"key": None, "value": None}


class RepairCancelled(Exception):
    """Raised when the caller cancels a repair before output is committed."""


def _atomic_write_text(
    path_value: str,
    text: str,
    encoding: str = "utf-8",
    newline: Optional[str] = None,
) -> None:
    """Replace a text file only after its complete contents are on disk."""
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with tmp.open("w", encoding=encoding, newline=newline) as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def read_playlist_text(path_value: str) -> str:
    """Decode text playlists conservatively, including Japanese Windows exports."""
    raw = Path(path_value).read_bytes()
    # Single-byte Western codecs are deliberately last because they can decode
    # almost any byte sequence and would otherwise hide CP932/Big5 mojibake.
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp932", "cp950", "big5", "cp1252"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")

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



def compact_identity(s: Optional[str]) -> Optional[str]:
    """Aggressive identity key for artist/album names only.

    Removes separator differences such as spaces, hyphens, underscores, wave dashes
    and quote variants while preserving Unicode letters and digits. This is deliberately
    not used for title matching.
    """
    value = norm(s)
    if not value:
        return None
    value = value.replace("〜", "").replace("～", "")
    value = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    return value or None


def artist_compatible(query: Optional[str], candidate: Optional[str]) -> bool:
    """Conservative artist compatibility for Roon path names versus file tags.

    Accept exact identity and a main-artist tag followed by an explicit collaboration
    marker (feat/ft/featuring/with). It does not accept arbitrary substring matches.
    """
    q = compact_identity(query)
    c = compact_identity(candidate)
    if not q or not c:
        return False
    if q == c:
        return True

    raw = norm(candidate) or ""
    main = re.split(r"\b(?:feat|featuring|ft|with)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    if compact_identity(main) == q:
        return True

    # Multi-artist tags commonly repeat the album artist after a comma. Only accept
    # an exact component, never a loose substring.
    components = [compact_identity(x) for x in re.split(r"\s*[,;/]\s*", raw)]
    return q in {x for x in components if x}


_GENERIC_ARTIST_IDENTITIES = frozenset(
    compact_identity(value)
    for value in (
        "Various",
        "Various Artist",
        "Various Artists",
        "VA",
        "Unknown",
        "Unknown Artist",
        "様々なアーティスト",
        "各种艺术家",
        "各種藝人",
    )
)


def meaningful_artist_identities(*values: Optional[str]) -> List[str]:
    """Return distinct, non-generic artist fields supplied by an exporter.

    Roon XLSX rows can use ``Artist`` for a composite performer/guest credit
    while ``Album Artist`` contains the stable primary identity.  Both fields
    are evidence and neither should hide the other.  Generic compilation labels
    are excluded because they cannot establish track identity.
    """
    result: List[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        key = compact_identity(value)
        if not value or not key or key in _GENERIC_ARTIST_IDENTITIES or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def album_keys_from_item(item: dict) -> set[str]:
    """Return conservative album identity keys from metadata and nearby folders."""
    keys: set[str] = set()
    album = compact_identity(str(item.get("album") or ""))
    if album:
        keys.add(album)

    path = str(item.get("path") or "").replace("\\", "/")
    parts = [x for x in path.split("/") if x]
    for folder in parts[-4:-1]:
        key = compact_identity(folder)
        if key:
            keys.add(key)
        # Common library layout: "Artist - Album". Add the album suffix too.
        split = re.split(r"\s+-\s+", folder, maxsplit=1)
        if len(split) == 2:
            suffix = compact_identity(split[1])
            if suffix:
                keys.add(suffix)
    return keys

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


def preserved_candidate_pairs_from_display(disp: str) -> List[Tuple[str, Optional[str]]]:
    """Parse EXTINF display text without deleting version qualifiers.

    The first-stage matcher intentionally retains its historical normalization.
    This parser is used only after that stage is unresolved, so terms such as
    "live", "remix" and "acoustic" can safely distinguish otherwise identical
    candidates.
    """
    if not disp:
        return []

    display = disp.replace("–", "-").replace("—", "-").strip()
    raw_parts = [part.strip() for part in re.split(r"\s+-\s+", display) if part.strip()]
    parts = [norm_preserve_qualifiers(part) for part in raw_parts]
    parts = [part for part in parts if part]
    if not parts:
        return []

    pairs: List[Tuple[str, Optional[str]]] = []
    if len(parts) == 1:
        pairs.append((parts[0], None))
    elif len(parts) == 2:
        first, second = parts
        pairs.extend([(first, second), (second, first)])
    else:
        pairs.append((parts[1], parts[0]))
        pairs.append((" - ".join(parts[1:]), parts[0]))
        pairs.append((" - ".join(parts[:-1]), parts[-1]))
        pairs.append((" - ".join(parts), None))
        pairs.append((" - ".join(parts[:-1]), None))
        pairs.append((parts[1], None))

    seen: set[Tuple[str, Optional[str]]] = set()
    out: List[Tuple[str, Optional[str]]] = []
    for title, artist in pairs:
        key = (title, artist)
        if not title or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def raw_candidate_pairs_from_display(disp: str) -> List[Tuple[str, Optional[str]]]:
    """Parse EXTINF text while retaining brackets needed by the safety gate."""
    if not disp:
        return []

    display = disp.replace("–", "-").replace("—", "-").strip()
    parts = [part.strip() for part in re.split(r"\s+-\s+", display) if part.strip()]
    if not parts:
        return []

    pairs: List[Tuple[str, Optional[str]]] = []
    if len(parts) == 1:
        pairs.append((parts[0], None))
    elif len(parts) == 2:
        first, second = parts
        pairs.extend([(first, second), (second, first)])
    else:
        pairs.append((parts[1], parts[0]))
        pairs.append((" - ".join(parts[1:]), parts[0]))
        pairs.append((" - ".join(parts[:-1]), parts[-1]))
        pairs.append((" - ".join(parts), None))
        pairs.append((" - ".join(parts[:-1]), None))
        pairs.append((parts[1], None))

    seen: set[Tuple[str, Optional[str]]] = set()
    out: List[Tuple[str, Optional[str]]] = []
    for title, artist in pairs:
        key = (title.casefold(), artist.casefold() if artist else None)
        if not title or key in seen:
            continue
        seen.add(key)
        out.append((title, artist))
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


def build_roon_indexes(music_index: list) -> Tuple[Dict[str, List[dict]], Dict[str, List[dict]]]:
    """Precompute expensive Roon matching features and inverted indexes.

    The old implementation recalculated filename/path metadata for every
    playlist-row × library-item pair. With a 1,579-track playlist and an
    18,870-item library that meant possibly millions of full candidate scores.
    This cache narrows each query to title-related candidates and computes each
    library item's normalized metadata only once per repair run.
    """
    by_full_title: Dict[str, List[dict]] = {}
    by_title_token: Dict[str, List[dict]] = {}

    for item in music_index:
        path_value = str(item.get("path") or "")
        if not path_value:
            continue
        title_variants = candidate_title_variants(item)
        item["_pf_title_variants"] = title_variants
        item["_pf_artist_variants"] = item_artist_variants(item)
        item["_pf_album_keys"] = item_album_keys(item)
        item["_pf_track"] = item_track_number(item)
        item["_pf_norm_path_parts"] = norm_path_parts(path_value)

        seen_tokens: Set[str] = set()
        for title in title_variants:
            by_full_title.setdefault(title, []).append(item)
            seen_tokens.update(tokens(title))
        for token in seen_tokens:
            by_title_token.setdefault(token, []).append(item)

    return by_full_title, by_title_token


def roon_candidate_pool(
    query_title: Optional[str],
    by_full_title: Dict[str, List[dict]],
    by_title_token: Dict[str, List[dict]],
) -> List[dict]:
    """Return a bounded candidate set without scanning the entire library."""
    title_q = norm_preserve_qualifiers(query_title)
    if not title_q:
        return []

    pool: List[dict] = []
    seen: Set[str] = set()

    def add(items: List[dict]) -> None:
        for item in items:
            path_value = str(item.get("path") or "")
            if path_value and path_value not in seen:
                seen.add(path_value)
                pool.append(item)

    # Exact preserved-title matches are always included.
    add(by_full_title.get(title_q, []))

    # Also include items sharing title tokens so close spellings and punctuation
    # variants retain the same fuzzy behavior without a full-library scan.
    for token in tokens(title_q):
        add(by_title_token.get(token, []))

    return pool


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



_VERSION_WORDS = {
    "live", "acoustic", "remix", "rmx", "remastered", "remaster",
    "instrumental", "karaoke", "demo", "cover", "edit", "mix",
    "version", "ver", "radio", "mono", "stereo", "unplugged",
    "stripped", "alternate", "orchestral", "orchestra", "piano",
    "extended", "reprise", "sped", "slowed", "nightcore",
}

def norm_preserve_qualifiers(s: Optional[str]) -> Optional[str]:
    """Normalize a title without deleting bracketed/version text."""
    if not s:
        return None
    value = str(s).strip()
    value = _DASHES.sub("-", value)
    value = value.replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
    value = value.replace("'", "")
    value = _BAD_PUNCT.sub(" ", value)
    value = value.replace("_", " ").replace("\u3000", " ")
    value = value.lower()
    value = _FEAT.sub("feat", value)
    value = re.sub(r"[\(\)\[\]\{\}]", " ", value)
    value = _MULTI_SPACE.sub(" ", value).strip()
    return value or None


def title_identity_key(value: Optional[str]) -> Optional[str]:
    """Return a punctuation/Unicode-insensitive title key for rescue matching.

    This deliberately is not used by the first-stage matcher.  It may equate
    strings that are visually different, so callers must also require
    independent artist/album/track/path evidence before auto-resolving.
    """
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = norm_preserve_qualifiers(normalized)
    if not normalized:
        return None
    # Compatibility-normalize equivalent accents (for example Greek oxia versus
    # tonos) and remove punctuation/separators commonly replaced by exporters.
    decomposed = unicodedata.normalize("NFKD", normalized)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    compact = "".join(char for char in without_marks if char.isalnum())
    return compact or None


def title_identity_grams(key: Optional[str], width: int = 3) -> set[str]:
    """Character grams used to find conservative near-title rescue candidates."""
    if not key:
        return set()
    if len(key) <= width:
        return {key}
    return {key[index:index + width] for index in range(len(key) - width + 1)}


def version_signature(title: Optional[str]) -> Tuple[str, ...]:
    """Return conservative version markers that must agree for auto-resolve.

    Besides generic words such as live/remix/remastered, keep words immediately
    before remix/rmx/mix so named remixes (e.g. Zatox Remix) stay distinct.
    """
    value = norm_preserve_qualifiers(title) or ""
    words = re.findall(r"[\w]+", value, flags=re.UNICODE)
    markers: List[str] = []
    for i, word in enumerate(words):
        if word in _VERSION_WORDS:
            markers.append(word)
            if word in {"remix", "rmx", "mix"} and i > 0:
                prev = words[i - 1]
                if prev not in {"the", "a", "an"}:
                    markers.append(prev)
    return tuple(sorted(set(markers)))


def version_compatible(query_title: Optional[str], candidate_title: Optional[str]) -> bool:
    """Different explicit versions may be candidates, but never auto-resolved."""
    return version_signature(query_title) == version_signature(candidate_title)


_FEAT_CREDIT = re.compile(
    r"(?:^|[\s\(\[\{,;/])\s*(?:feat(?:uring)?|ft)\.?\s+"
    r"(.+?)(?=$|[\)\]\},;/])",
    re.IGNORECASE,
)
_WITH_CREDIT = re.compile(
    r"[\(\[\{]\s*with\s+(.+?)(?=$|[\)\]\}])",
    re.IGNORECASE,
)


def artist_credit_parts(value: Optional[str]) -> set[str]:
    """Return accent/punctuation-insensitive credited artist components."""
    if not value:
        return set()
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    normalized = re.sub(
        r"\b(?:feat(?:uring)?|ft|with|and|x)\b",
        ",",
        normalized,
        flags=re.IGNORECASE,
    )
    parts = re.split(r"\s*(?:,|&|/|;|\+)\s*", normalized)
    out: set[str] = set()
    for part in parts:
        compact = compact_identity(part)
        if compact:
            out.add(compact)
    return out


def collaboration_credits(value: Optional[str]) -> set[str]:
    """Extract explicit feat/with credits from a title."""
    out: set[str] = set()
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    normalized = _DASHES.sub("-", normalized)
    for pattern in (_FEAT_CREDIT, _WITH_CREDIT):
        for match in pattern.finditer(normalized):
            out.update(artist_credit_parts(match.group(1)))
    return out


def title_without_collaboration(value: Optional[str]) -> Optional[str]:
    """Remove only explicit feat/with clauses while preserving version words."""
    raw = unicodedata.normalize("NFKC", str(value or ""))
    if not raw.strip():
        return None
    stripped = _FEAT_CREDIT.sub(" ", raw)
    stripped = _WITH_CREDIT.sub(" ", stripped)
    stripped = re.sub(
        r"\s+(?:feat(?:uring)?|ft)\.?\s+.+$",
        " ",
        stripped,
        flags=re.IGNORECASE,
    )
    return norm_preserve_qualifiers(stripped)


def title_auto_resolve_compatible(
    query_title: Optional[str],
    candidate_title: Optional[str],
    source_artist: Optional[str],
    candidate_artists: List[str],
) -> bool:
    """High-precision title/version gate used before any Resolved result."""
    if not version_compatible(query_title, candidate_title):
        return False

    query_base = title_identity_key(title_without_collaboration(query_title))
    candidate_base = title_identity_key(title_without_collaboration(candidate_title))
    if not query_base or query_base != candidate_base:
        return False

    return collaboration_auto_resolve_compatible(
        query_title,
        candidate_title,
        source_artist,
        candidate_artists,
    )


def collaboration_auto_resolve_compatible(
    query_title: Optional[str],
    candidate_title: Optional[str],
    source_artist: Optional[str],
    candidate_artists: List[str],
) -> bool:
    """Accept collaboration differences only when the artist credits explain them."""
    source_credits = artist_credit_parts(source_artist)
    candidate_credits = set()
    for value in candidate_artists:
        candidate_credits.update(artist_credit_parts(value))

    query_collabs = collaboration_credits(query_title)
    candidate_collabs = collaboration_credits(candidate_title)
    if query_collabs != candidate_collabs:
        candidate_only = candidate_collabs - query_collabs
        query_only = query_collabs - candidate_collabs
        if candidate_only and not candidate_only.issubset(source_credits):
            return False
        if query_only and not query_only.issubset(candidate_credits):
            return False
    return True


def path_candidate_safe(query: Dict[str, Any], item: dict) -> Tuple[bool, str]:
    """Reject a path-only match when explicit version/collaboration evidence conflicts."""
    source_path = str(query.get("path") or "")
    target_path = str(item.get("path") or "")
    source_file_title = norm_preserve_qualifiers(title_from_filename(source_path))
    target_file_title = norm_preserve_qualifiers(title_from_filename(target_path))
    query_title = str(query.get("title") or "")
    raw_candidate_title = str(item.get("title") or "")
    source_artist = str(query.get("artist") or query.get("album_artist") or "")

    # An identical filename is useful evidence, but it must never erase an
    # explicit Live/Remix/collaboration conflict from the target's own tags.
    if query_title and raw_candidate_title:
        if not version_compatible(query_title, raw_candidate_title):
            return False, "version conflict"
        if not collaboration_auto_resolve_compatible(
            query_title,
            raw_candidate_title,
            source_artist,
            item_artist_variants(item),
        ):
            return False, "collaboration conflict"

    # Artist names supplied by the old path/XLSX are identity evidence. A title,
    # album name or track number cannot silently outvote an explicit mismatch.
    candidate_artists = [
        str(value).strip()
        for value in (item.get("artist"), item.get("album_artist"))
        if str(value or "").strip()
    ]
    if source_artist and candidate_artists:
        compatible = any(
            artist_compatible(source_artist, value)
            or jaccard(norm(source_artist), norm(value)) >= 0.8
            for value in candidate_artists
        )
        if not compatible:
            return False, "artist conflict"

    # MusicBee/iTunes often truncates both the old and new filename at the same
    # point even though the target's embedded title tag is complete. Once the
    # explicit safety checks above pass, identical filenames remain valid evidence.
    if source_file_title and source_file_title == target_file_title:
        return True, ""
    return True, ""


def duplicate_duration_consistency(
    item: dict,
    same_title_items: List[dict],
) -> Tuple[bool, str]:
    """Veto a duration outlier when three independent indexed copies agree."""
    selected_duration = parse_intish(item.get("duration"))
    if selected_duration is None:
        return True, ""

    selected_path = ntpath.normcase(ntpath.normpath(str(item.get("path") or "")))
    selected_title = str(item.get("title") or "")
    selected_signature = version_signature(selected_title)
    selected_collabs = collaboration_credits(selected_title)
    selected_albums = item_album_keys(item)
    selected_artists = item_artist_variants(item)
    selected_album_artist = artist_credit_parts(item.get("album_artist"))
    selected_track = item_track_number(item)
    selected_disc = item_disc_number(item)
    peer_durations: List[int] = []

    various_artist_aliases = {
        "variousartist",
        "variousartists",
        "様々なアーティスト",
        "各种艺术家",
        "各種藝人",
    }

    def comparable_album_artist(parts: set[str]) -> set[str]:
        if any(part in various_artist_aliases for part in parts):
            return {"__various_artists__"}
        return parts

    selected_album_artist = comparable_album_artist(selected_album_artist)

    for candidate in same_title_items:
        candidate_path = ntpath.normcase(
            ntpath.normpath(str(candidate.get("path") or ""))
        )
        if not candidate_path or candidate_path == selected_path:
            continue
        candidate_title = str(candidate.get("title") or "")
        if version_signature(candidate_title) != selected_signature:
            continue
        if collaboration_credits(candidate_title) != selected_collabs:
            continue
        candidate_album_artist = comparable_album_artist(
            artist_credit_parts(candidate.get("album_artist"))
        )
        if (
            selected_album_artist
            and candidate_album_artist
            and selected_album_artist != candidate_album_artist
        ):
            continue

        candidate_track = item_track_number(candidate)
        candidate_disc = item_disc_number(candidate)
        if (
            selected_track is not None
            and candidate_track is not None
            and selected_track != candidate_track
        ):
            continue
        if (
            selected_disc is not None
            and candidate_disc is not None
            and selected_disc != candidate_disc
        ):
            continue

        candidate_albums = item_album_keys(candidate)
        album_ok = bool(selected_albums and candidate_albums and selected_albums & candidate_albums)
        artist_ok = any(
            artist_compatible(left, right)
            for left in selected_artists
            for right in item_artist_variants(candidate)
        )
        if not album_ok or not artist_ok:
            continue

        candidate_duration = parse_intish(candidate.get("duration"))
        if candidate_duration is not None:
            peer_durations.append(candidate_duration)

    if len(peer_durations) < 3:
        return True, ""

    consensus: List[int] = []
    for duration in peer_durations:
        cluster = [value for value in peer_durations if abs(value - duration) <= 5]
        if len(cluster) > len(consensus):
            consensus = cluster
    if len(consensus) < 3:
        return True, ""

    ordered = sorted(consensus)
    consensus_duration = ordered[len(ordered) // 2]
    delta = abs(selected_duration - consensus_duration)
    if delta > 10:
        return (
            False,
            f"indexed-copy duration conflict {selected_duration}s vs "
            f"{consensus_duration}s consensus ({len(consensus)} copies)",
        )
    return True, ""


def extinf_candidate_safe(
    display: str,
    original_path: str,
    duration: Optional[int],
    item: dict,
) -> Tuple[bool, str]:
    """Reject single-candidate EXTINF matches with contradictory evidence."""
    candidate_duration = parse_intish(item.get("duration"))
    if duration is not None and candidate_duration is not None:
        delta = abs(candidate_duration - duration)
        if delta > 10:
            return False, f"duration conflict {delta}s"

    base = parse_generic_absolute_path(original_path)
    base_artist = str(base.get("artist") or "")
    pairs = raw_candidate_pairs_from_display(display)
    if not pairs:
        pairs = [(str(base.get("title") or ""), base_artist or None)]

    candidate_titles = candidate_title_variants(item)
    raw_primary_title = str(item.get("title") or "")
    primary_title = norm_preserve_qualifiers(raw_primary_title)
    # A simplified filename must not erase an explicit version/collaboration
    # qualifier that is present in the file's own title tag.
    if primary_title and (
        version_signature(primary_title) or collaboration_credits(raw_primary_title)
    ):
        candidate_titles = [raw_primary_title]
    candidate_artists = item_artist_variants(item)
    for query_title, display_artist in pairs:
        source_artist = str(display_artist or base_artist or "")
        for candidate_title in candidate_titles:
            if title_auto_resolve_compatible(
                query_title,
                candidate_title,
                source_artist,
                candidate_artists,
            ):
                return True, ""
    return False, "title/version/collaboration conflict"


def filename_metadata(path_value: str) -> Dict[str, Any]:
    """Extract conservative artist/album/track/title clues from common filenames.

    Supports examples such as:
      Artist - Album - 03_10.Title.mp3
      Artist - Album - 03 - Title.flac
      1-03 Title.flac
    """
    filename = re.split(r"[\\/]", str(path_value or ""))[-1]
    stem = os.path.splitext(filename)[0].strip()
    result: Dict[str, Any] = {"artist": None, "album": None, "track": None, "title": None}

    m = re.match(r"^\s*(.+?)\s+-\s+(.+?)\s+-\s+(\d{1,3})(?:[_-]\d{1,3})?[. _-]+(.+?)\s*$", stem)
    if m:
        result.update(artist=m.group(1), album=m.group(2), track=int(m.group(3)), title=m.group(4))
        return result

    m = re.match(r"^\s*(\d{1,2})[-_. ](\d{1,3})(?:[_-]\d{1,3})?[. _-]+(.+?)\s*$", stem)
    if m:
        result.update(track=int(m.group(2)), title=m.group(3))
        return result

    m = re.match(r"^\s*(\d{1,3})(?:[_-]\d{1,3})?[. _-]+(.+?)\s*$", stem)
    if m:
        result.update(track=int(m.group(1)), title=m.group(2))
        return result

    result["title"] = title_from_filename(filename)
    return result


def candidate_title_variants(item: dict) -> List[str]:
    cached = item.get("_pf_title_variants")
    if isinstance(cached, list):
        return cached
    raw: List[Optional[str]] = [str(item.get("title") or "")]
    fm = filename_metadata(str(item.get("path") or ""))
    raw.append(str(fm.get("title") or ""))
    out: List[str] = []
    for value in raw:
        normalized = norm_preserve_qualifiers(value)
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def build_identity_rescue_indexes(
    music_index: list,
) -> Tuple[Dict[str, List[dict]], Dict[str, List[dict]]]:
    """Build format-neutral title indexes used only by the rescue stage."""
    by_identity: Dict[str, List[dict]] = {}
    by_gram: Dict[str, List[dict]] = {}
    for item in music_index:
        path_value = str(item.get("path") or "")
        if not path_value:
            continue
        identity_keys: set[str] = set()
        for variant in candidate_title_variants(item):
            key = title_identity_key(variant)
            if key:
                identity_keys.add(key)
                by_identity.setdefault(key, []).append(item)
        seen_grams: set[str] = set()
        for key in identity_keys:
            seen_grams.update(title_identity_grams(key))
        for gram in seen_grams:
            by_gram.setdefault(gram, []).append(item)
    return by_identity, by_gram


def identity_rescue_candidate_pool(
    query_title: Optional[str],
    by_identity: Dict[str, List[dict]],
    by_gram: Dict[str, List[dict]],
) -> List[dict]:
    """Return exact or very-close title candidates without a full-library scan."""
    query_key = title_identity_key(query_title)
    if not query_key:
        return []

    exact = by_identity.get(query_key, [])
    if exact:
        return list(exact)
    # Fuzzy rescue is intentionally disabled for very short titles; a one-word
    # near-match such as "Stay" versus "Star" is not enough identity evidence.
    if len(query_key) < 6:
        return []

    overlap: Dict[str, Tuple[int, dict]] = {}
    for gram in title_identity_grams(query_key):
        for item in by_gram.get(gram, []):
            path_value = str(item.get("path") or "")
            if not path_value:
                continue
            count, _ = overlap.get(path_value, (0, item))
            overlap[path_value] = (count + 1, item)

    # Score only the strongest character-gram candidates. This keeps rescue
    # bounded even for a very large library with common title fragments.
    strongest = sorted(overlap.values(), key=lambda entry: entry[0], reverse=True)[:250]
    out: List[dict] = []
    for _count, item in strongest:
        best_ratio = max(
            (
                difflib.SequenceMatcher(None, query_key, title_identity_key(variant) or "").ratio()
                for variant in candidate_title_variants(item)
            ),
            default=0.0,
        )
        if best_ratio >= 0.90:
            out.append(item)
    return out


def item_track_number(item: dict) -> Optional[int]:
    if "_pf_track" in item:
        return item.get("_pf_track")
    tagged = parse_intish(item.get("track"))
    if tagged is not None:
        return tagged
    return parse_intish(filename_metadata(str(item.get("path") or "")).get("track"))


def item_disc_number(item: dict) -> Optional[int]:
    tagged = parse_intish(item.get("disc"))
    if tagged is not None:
        return tagged
    filename = Path(str(item.get("path") or "")).stem
    match = re.match(r"^\s*(\d{1,2})[-_. ](\d{1,3})", filename)
    return int(match.group(1)) if match else None


def item_tag_track_number(item: dict) -> Optional[int]:
    """Return only an embedded/indexed Track tag, never a filename guess."""
    return parse_intish(item.get("track"))


def item_tag_disc_number(item: dict) -> Optional[int]:
    """Return only an embedded/indexed Disc tag, never a filename guess."""
    return parse_intish(item.get("disc"))


def item_album_keys(item: dict) -> set[str]:
    cached = item.get("_pf_album_keys")
    if isinstance(cached, set):
        return cached
    keys = album_keys_from_item(item)
    fm_album = compact_identity(str(filename_metadata(str(item.get("path") or "")).get("album") or ""))
    if fm_album:
        keys.add(fm_album)
    return keys


def item_artist_variants(item: dict) -> List[str]:
    cached = item.get("_pf_artist_variants")
    if isinstance(cached, list):
        return cached
    values = [str(item.get("artist") or ""), str(item.get("album_artist") or "")]
    fm = filename_metadata(str(item.get("path") or ""))
    values.append(str(fm.get("artist") or ""))
    guessed = guess_artist_from_path_str(str(item.get("path") or ""))
    values.append(str(guessed or ""))
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def parse_generic_absolute_path(orig_path: str) -> Dict[str, Any]:
    """Parse MusicBee/foobar absolute paths using folder names as stable anchors.

    Folder structure is treated as .../Artist/Album/file. Filename separators are
    only stripped when they agree with those folder anchors, so hyphenated names
    such as Ne-Yo, CRYst-Alise and Exist/Exit are not split incorrectly.
    """
    clean = str(orig_path or "").rstrip("\r\n")
    normalized = clean.replace("\\", "/")
    parts = [x for x in normalized.split("/") if x]
    filename = parts[-1] if parts else clean
    stem = Path(filename).stem.strip()
    album = parts[-2] if len(parts) >= 2 else ""
    folder_artist = parts[-3] if len(parts) >= 3 else ""

    disc: Optional[int] = None
    track: Optional[int] = None
    remainder = stem

    # Explicit disc-track forms: 3-08 Title, 01_02_Title, 1-03 Title.
    m = re.match(r"^\s*(\d{1,2})[-_.](\d{1,3})(?:[._ -]+)(.+?)\s*$", remainder)
    if m:
        disc, track, remainder = int(m.group(1)), int(m.group(2)), m.group(3).strip()
    else:
        # Single track prefix, including glued forms such as 010-Title.
        m = re.match(r"^\s*(\d{1,3})(?:[._ -]+)(.+?)\s*$", remainder)
        if m:
            track, remainder = int(m.group(1)), m.group(2).strip()

    def strip_anchor(text: str, anchor: str) -> str:
        if not text or not anchor:
            return text
        # Require a real separator after the complete folder anchor. This avoids
        # splitting inside names such as Ne-Yo or CRYst-Alise.
        pattern = r"^\s*" + re.escape(anchor) + r"\s+-\s+"
        return re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)

    # MusicBee often emits "03 - Artist - Title" or
    # "Artist - Album - 02 Title". For entries with an explicit leading track,
    # strip only components confirmed by folders. For unnumbered iTunes-style
    # files, preserve the complete stem because the index filename variant may
    # intentionally include the artist prefix.
    if track is not None:
        remainder = strip_anchor(remainder, folder_artist)
        remainder = strip_anchor(remainder, album)
    else:
        anchored = strip_anchor(remainder, folder_artist)
        anchored = strip_anchor(anchored, album)
        # Complex export: "Artist - Album - 02 Title". Use the final numbered
        # segment only when such a segment actually exists.
        m = re.search(r"\s+-\s+(\d{1,3})\s+(.+?)\s*$", anchored)
        if m:
            track, remainder = int(m.group(1)), m.group(2).strip()

    title = remainder.strip() or title_from_filename(filename)
    return {
        "source": "generic_absolute_path",
        "artist": folder_artist,
        "album_artist": folder_artist,
        "album": album,
        "disc": disc,
        "track": track,
        "title": title,
    }



@dataclass(frozen=True)
class TrackIdentity:
    """Source-neutral song identity used by every playlist parser.

    A parser may leave fields empty. Missing fields are neutral; they are not
    treated as disagreement. ``source`` records where the query came from, not
    which matching algorithm should be used.
    """
    title_raw: str
    title: Optional[str]
    artist_raw: str = ""
    album_raw: str = ""
    artist_key: Optional[str] = None
    album_key: Optional[str] = None
    disc: Optional[int] = None
    track: Optional[int] = None
    duration: Optional[int] = None
    path: str = ""
    source: str = "unknown"
    path_parts: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateIdentity:
    """Normalized identity for one indexed audio file."""
    title_variants: Tuple[str, ...]
    artist_variants: Tuple[str, ...]
    album_keys: frozenset[str]
    disc: Optional[int]
    track: Optional[int]
    duration: Optional[int]
    path: str
    path_parts: Tuple[str, ...]


def query_track_identity(meta: Dict[str, Any], orig_path: str) -> TrackIdentity:
    title_raw = str(meta.get("title") or title_from_filename(orig_path))
    artist_raw = str(meta.get("artist") or meta.get("album_artist") or "")
    album_raw = str(meta.get("album") or "")
    cached_parts = meta.get("_pf_norm_path_parts")
    if not isinstance(cached_parts, list):
        cached_parts = norm_path_parts(orig_path)
        meta["_pf_norm_path_parts"] = cached_parts
    return TrackIdentity(
        title_raw=title_raw,
        title=norm_preserve_qualifiers(title_raw),
        artist_raw=artist_raw,
        album_raw=album_raw,
        artist_key=compact_identity(artist_raw),
        album_key=compact_identity(album_raw),
        disc=parse_intish(meta.get("disc")),
        track=parse_intish(meta.get("track")),
        duration=parse_intish(meta.get("duration")),
        path=str(orig_path or ""),
        source=str(meta.get("source") or "unknown"),
        path_parts=tuple(cached_parts),
    )


def indexed_track_identity(item: dict) -> CandidateIdentity:
    cached = item.get("_pf_track_identity")
    if isinstance(cached, CandidateIdentity):
        return cached
    parts = item.get("_pf_norm_path_parts")
    if not isinstance(parts, list):
        parts = norm_path_parts(str(item.get("path") or ""))
    ident = CandidateIdentity(
        title_variants=tuple(candidate_title_variants(item)),
        artist_variants=tuple(item_artist_variants(item)),
        album_keys=frozenset(item_album_keys(item)),
        disc=item_disc_number(item),
        track=item_track_number(item),
        duration=parse_intish(item.get("duration")),
        path=str(item.get("path") or ""),
        path_parts=tuple(parts),
    )
    item["_pf_track_identity"] = ident
    return ident


def indexed_tag_order_identity(item: dict) -> CandidateIdentity:
    """Use real target tags for Track/Disc while retaining all other evidence.

    Filename-derived order remains useful to rank path-only candidates, but it
    must not contradict trusted source-audio tags or masquerade as corroboration.
    """
    return replace(
        indexed_track_identity(item),
        track=item_tag_track_number(item),
        disc=item_tag_disc_number(item),
    )


def score_track_identity(query: TrackIdentity, candidate: CandidateIdentity) -> Tuple[float, List[str]]:
    """Shared evidence scorer for XLSX, Roon M3U and generic path inputs.

    This intentionally preserves the previous weights and thresholds. The
    refactor changes representation, not matching decisions.
    """
    score = 0.0
    reasons: List[str] = []
    if not query.title or not candidate.title_variants:
        return 0.0, []

    exact_title = query.title in candidate.title_variants
    best_similarity = max((jaccard(query.title, value) for value in candidate.title_variants), default=0.0)
    if exact_title:
        score += 58; reasons.append("title exact")
    elif best_similarity >= 0.92:
        score += 51; reasons.append("title close")
    elif best_similarity >= 0.78:
        score += 38; reasons.append("title fuzzy")
    else:
        return 0.0, []

    if any(version_compatible(query.title_raw, value) for value in candidate.title_variants):
        reasons.append("version compatible")
    else:
        reasons.append("VERSION MISMATCH")
        score -= 35

    if query.artist_raw:
        if any(artist_compatible(query.artist_raw, value) for value in candidate.artist_variants):
            score += 25; reasons.append("artist compatible")
        elif candidate.artist_variants:
            qn = norm(query.artist_raw)
            closeness = max((jaccard(qn, norm(value)) for value in candidate.artist_variants if norm(value)), default=0.0)
            if closeness >= 0.8:
                score += 18; reasons.append("artist close")
            else:
                reasons.append("artist differs")

    if candidate.path_parts and query.path_parts:
        same = 0
        for x, y in zip(reversed(query.path_parts), reversed(candidate.path_parts)):
            if x == y:
                same += 1
            else:
                break
        path_score = same / max(1, min(len(query.path_parts), len(candidate.path_parts)))
    else:
        path_score = suffix_similarity(query.path, candidate.path)
    if path_score >= 0.66:
        score += 22; reasons.append("path suffix")
    elif path_score >= 0.4:
        score += 12; reasons.append("path tail")

    if query.album_key:
        if query.album_key in candidate.album_keys:
            score += 15; reasons.append("album identity")
        elif any(jaccard(norm(query.album_raw), norm(key)) >= 0.82 for key in candidate.album_keys if norm(key)):
            score += 9; reasons.append("album close")
        elif candidate.album_keys:
            reasons.append("album differs")

    if query.track is not None and candidate.track is not None:
        if candidate.track == query.track:
            score += 7; reasons.append("track number")
        else:
            score -= 14; reasons.append("track differs")
    if query.disc is not None and candidate.disc is not None:
        if candidate.disc == query.disc:
            score += 3; reasons.append("disc number")
        else:
            score -= 8; reasons.append("disc differs")

    # Duration is format-neutral evidence, but it is used only when the playlist
    # source itself explicitly supplied duration (for example EXTINF or source
    # metadata). Historical index entries are never used to fill this field.
    if query.duration is not None and candidate.duration is not None:
        duration_delta = abs(candidate.duration - query.duration)
        if duration_delta <= 2:
            score += 20; reasons.append("duration close")
        elif duration_delta <= 5:
            score += 10; reasons.append("duration near")
        elif duration_delta > 10:
            score -= 20; reasons.append("duration differs")
    return score, reasons


def extinf_query_metadata(
    display: str,
    original_path: str,
    duration: Optional[int],
) -> List[Dict[str, Any]]:
    """Build source-neutral structured queries for a previously unresolved EXTINF row."""
    base = parse_generic_absolute_path(original_path)
    pairs = preserved_candidate_pairs_from_display(display)
    if not pairs:
        pairs = [(str(base.get("title") or ""), str(base.get("artist") or "") or None)]

    out: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for title, artist in pairs:
        query = dict(base)
        query["source"] = "extinf_rescue"
        query["title"] = title or str(base.get("title") or "")
        query["artist"] = artist or str(base.get("artist") or "")
        query["album_artist"] = query["artist"]
        query["duration"] = duration
        key = (str(query["title"]), str(query["artist"]))
        if query["title"] and key not in seen:
            seen.add(key)
            out.append(query)
    return out


def rank_ambiguous_extinf_candidates(
    display: str,
    original_path: str,
    duration: Optional[int],
    candidates: List[dict],
) -> Tuple[List[dict], str]:
    """Auto-resolve an existing ambiguity only when structured evidence separates it.

    Every candidate already passed the legacy title/artist/duration matcher.  The
    rescue stage may use album, track, disc and preserved version text, but a tie
    or any hard conflict remains Ambiguous.
    """
    queries = extinf_query_metadata(display, original_path, duration)
    scored: List[Tuple[float, dict, List[str]]] = []
    for item in candidates:
        best_score = 0.0
        best_reasons: List[str] = []
        for meta in queries:
            score, reasons = score_track_identity(
                query_track_identity(meta, original_path),
                indexed_track_identity(item),
            )
            if score > best_score:
                best_score, best_reasons = score, reasons
        scored.append((best_score, item, best_reasons))

    scored.sort(key=lambda entry: entry[0], reverse=True)
    if not scored:
        return candidates, "no structured EXTINF candidates"
    best_score, best_item, best_reasons = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    reason_set = set(best_reasons)
    hard_conflicts = {
        "VERSION MISMATCH", "track differs", "disc differs", "duration differs",
    }
    title_safe = "title exact" in reason_set or "title close" in reason_set
    artist_safe = "artist compatible" in reason_set
    album_safe = "album identity" in reason_set
    track_present = any(parse_intish(meta.get("track")) is not None for meta in queries)
    track_safe = "track number" in reason_set
    disc_present = any(parse_intish(meta.get("disc")) is not None for meta in queries)
    disc_safe = "disc number" in reason_set
    locator_safe = (not track_present or track_safe) and (not disc_present or disc_safe)

    if (
        best_score >= 100.0
        and best_score - runner_up >= 10.0
        and not (reason_set & hard_conflicts)
        and title_safe
        and "version compatible" in reason_set
        and artist_safe
        and album_safe
        and locator_safe
    ):
        chosen = dict(best_item)
        chosen["_match_reason"] = (
            f"EXTINF structured rescue [{MATCH_ENGINE_BUILD}] {best_score:.0f}: "
            + ", ".join(best_reasons)
        )
        return [chosen], chosen["_match_reason"]
    return candidates, "structured EXTINF evidence remained ambiguous"


def score_identity_rescue(
    meta: Dict[str, Any],
    original_path: str,
    item: dict,
) -> Tuple[float, List[str]]:
    """Score candidates whose titles differ only by export damage or a small typo."""
    query = query_track_identity(meta, original_path)
    candidate = indexed_track_identity(item)
    query_key = title_identity_key(query.title_raw)
    if not query_key:
        return 0.0, []

    ratios: List[Tuple[float, str]] = []
    for variant in candidate.title_variants:
        candidate_key = title_identity_key(variant)
        if candidate_key:
            ratios.append((difflib.SequenceMatcher(None, query_key, candidate_key).ratio(), variant))
    if not ratios:
        return 0.0, []
    best_ratio, _best_variant = max(ratios, key=lambda entry: entry[0])
    reasons: List[str] = []
    if best_ratio == 1.0:
        score = 60.0
        reasons.append("title identity")
    elif best_ratio >= 0.90:
        score = 50.0
        reasons.append(f"title character close {best_ratio:.2f}")
    else:
        return 0.0, []

    if any(version_compatible(query.title_raw, variant) for variant in candidate.title_variants):
        reasons.append("version compatible")
    else:
        reasons.append("VERSION MISMATCH")
        score -= 50.0

    artist_ok = False
    if query.artist_raw:
        artist_ok = any(
            artist_compatible(query.artist_raw, value)
            for value in candidate.artist_variants
        )
        if artist_ok:
            score += 25.0
            reasons.append("artist compatible")
        elif candidate.artist_variants:
            reasons.append("artist differs")

    album_ok = False
    if query.album_key:
        album_ok = query.album_key in candidate.album_keys
        if album_ok:
            score += 15.0
            reasons.append("album identity")
        elif candidate.album_keys:
            reasons.append("album differs")

    if query.track is not None and candidate.track is not None:
        if query.track == candidate.track:
            score += 7.0
            reasons.append("track number")
        else:
            score -= 20.0
            reasons.append("track differs")
    if query.disc is not None and candidate.disc is not None:
        if query.disc == candidate.disc:
            score += 3.0
            reasons.append("disc number")
        else:
            score -= 12.0
            reasons.append("disc differs")

    path_score = suffix_similarity(original_path, candidate.path)
    if path_score == 1.0:
        score += 30.0
        reasons.append("exact path suffix")
    elif path_score >= 0.66:
        score += 15.0
        reasons.append("path suffix")

    if query.duration is not None and candidate.duration is not None:
        delta = abs(query.duration - candidate.duration)
        if delta <= 2:
            score += 20.0
            reasons.append("duration close")
        elif delta <= 5:
            score += 10.0
            reasons.append("duration near")
        else:
            # A stale EXTINF duration is negative evidence, not an absolute gate.
            reasons.append(f"duration differs {delta}s")
    return score, reasons


def _source_audio_first(value: Any) -> Optional[str]:
    """Return one text value from Mutagen's Easy/raw tag representations."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore") or None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _source_audio_raw_tags(audio: Any) -> Dict[str, Optional[str]]:
    """Read common identity fields from format-neutral raw Mutagen tags."""
    tags = getattr(audio, "tags", None)
    empty = {
        "title": None,
        "artist": None,
        "album_artist": None,
        "album": None,
        "track": None,
        "disc": None,
    }
    if not tags:
        return empty

    def get_any(keys: List[str]) -> Optional[str]:
        for key in keys:
            try:
                if key not in tags:
                    continue
                value = _source_audio_first(tags.get(key))
            except Exception:
                continue
            if value:
                return value
        return None

    artist = get_any(["TPE1", "ARTIST", "\xa9ART", "©ART"])
    album_artist = get_any(
        ["TPE2", "ALBUMARTIST", "ALBUM ARTIST", "aART", "\xa9aRT", "©aRT"]
    )
    return {
        "title": get_any(["TIT2", "TITLE", "\xa9nam", "©nam"]),
        "artist": artist or album_artist,
        "album_artist": album_artist,
        "album": get_any(["TALB", "ALBUM", "\xa9alb", "©alb"]),
        "track": get_any(["TRCK", "TRACKNUMBER", "TRACK", "trkn"]),
        "disc": get_any(["TPOS", "DISCNUMBER", "DISC", "disk"]),
    }


def _source_audio_duration(audio: Any) -> Optional[int]:
    try:
        info = getattr(audio, "info", None)
        length = getattr(info, "length", None) if info is not None else None
        if length is not None:
            return int(round(float(length)))
    except Exception:
        pass
    return None


def read_source_audio_identity(original_path: str) -> Optional[Dict[str, Any]]:
    """Read real source-file tags for a PATH_ONLY row without path guessing.

    This rescue is intentionally unavailable when the old source file is gone.
    Filename and folder guesses are already handled by the normal matcher; only
    embedded tags and duration may add enough independent evidence here.
    """
    if MutagenFile is None or not os.path.isfile(original_path):
        return None

    metadata: Dict[str, Optional[str]] = {
        "title": None,
        "artist": None,
        "album_artist": None,
        "album": None,
        "track": None,
        "disc": None,
    }
    duration: Optional[int] = None

    try:
        easy = MutagenFile(original_path, easy=True)
    except Exception:
        easy = None
    if easy is not None:
        duration = _source_audio_duration(easy)
        for field_name, tag_name in (
            ("title", "title"),
            ("artist", "artist"),
            ("album_artist", "albumartist"),
            ("album", "album"),
            ("track", "tracknumber"),
            ("disc", "discnumber"),
        ):
            try:
                value = _source_audio_first(easy.get(tag_name))
            except Exception:
                value = None
            if value:
                metadata[field_name] = value

    if duration is None or any(
        metadata[field_name] is None
        for field_name in ("title", "artist", "album", "track", "disc")
    ):
        try:
            raw = MutagenFile(original_path, easy=False)
        except Exception:
            raw = None
        if raw is not None:
            if duration is None:
                duration = _source_audio_duration(raw)
            raw_metadata = _source_audio_raw_tags(raw)
            for field_name, value in raw_metadata.items():
                if metadata.get(field_name) is None and value:
                    metadata[field_name] = value

    # A title and duration are mandatory. Empty-tag AIFF/WAV files and formats
    # Mutagen cannot identify remain Failed rather than receiving a path guess.
    if not metadata["title"] or duration is None:
        return None

    return {
        "source": "source_audio_tags",
        "path": original_path,
        "title": metadata["title"],
        "artist": metadata["artist"],
        "album_artist": metadata["album_artist"],
        "album": metadata["album"],
        "track": parse_intish(metadata["track"]),
        "disc": parse_intish(metadata["disc"]),
        "duration": duration,
    }


def select_source_audio_rescue(
    source_meta: Dict[str, Any],
    original_path: str,
    candidates: List[dict],
) -> Tuple[List[dict], str]:
    """Resolve only a unique candidate corroborated by real source-file tags."""
    query = query_track_identity(source_meta, original_path)
    scored: List[Tuple[float, dict, List[str]]] = []
    safe_by_path: Dict[str, Tuple[float, dict, List[str]]] = {}

    for item in candidates:
        # Source Track/Disc values came from real audio tags. Compare them only
        # with real target tags; a number guessed from the target filename is
        # useful path text, but neither confirming nor contradictory metadata.
        candidate_identity = indexed_tag_order_identity(item)
        score, reasons = score_track_identity(query, candidate_identity)
        if score <= 0:
            continue
        scored.append((score, item, reasons))
        reason_set = set(reasons)

        hard_conflict = bool(
            reason_set
            & {
                "VERSION MISMATCH",
                "artist differs",
                "album differs",
                "duration differs",
            }
        )
        title_safe = "title exact" in reason_set or "title close" in reason_set
        artist_present = bool(query.artist_raw)
        artist_safe = (
            not artist_present
            or "artist compatible" in reason_set
            or "artist close" in reason_set
        )
        album_present = bool(query.album_raw)
        album_safe = (
            not album_present
            or "album identity" in reason_set
            or "album close" in reason_set
        )
        # Missing target tags are unknown, not contradictory. When both real
        # source and target tags exist, a disagreement is a hard veto.
        track_safe = (
            query.track is None
            or candidate_identity.track is None
            or "track number" in reason_set
        )
        disc_safe = (
            query.disc is None
            or candidate_identity.disc is None
            or "disc number" in reason_set
        )
        duration_safe = (
            query.duration is not None
            and ("duration close" in reason_set or "duration near" in reason_set)
        )

        artist_channel = (
            "artist compatible" in reason_set or "artist close" in reason_set
        )
        album_channel = (
            "album identity" in reason_set or "album close" in reason_set
        )
        identity_channels = sum(
            (
                artist_channel,
                album_channel,
                candidate_identity.track is not None
                and "track number" in reason_set,
                candidate_identity.disc is not None
                and "disc number" in reason_set,
            )
        )
        raw_candidate_title = str(item.get("title") or "")
        collaboration_safe = collaboration_auto_resolve_compatible(
            query.title_raw,
            raw_candidate_title,
            query.artist_raw,
            item_artist_variants(item),
        )

        if (
            score >= 100.0
            and not hard_conflict
            and title_safe
            and "version compatible" in reason_set
            and collaboration_safe
            and artist_safe
            and album_safe
            and track_safe
            and disc_safe
            and duration_safe
            and identity_channels >= 2
            and (artist_channel or album_channel)
        ):
            path_value = str(item.get("path") or "")
            previous = safe_by_path.get(path_value)
            if path_value and (previous is None or score > previous[0]):
                safe_by_path[path_value] = (score, item, reasons)

    scored.sort(key=lambda entry: entry[0], reverse=True)
    safe = sorted(safe_by_path.values(), key=lambda entry: entry[0], reverse=True)
    if not safe:
        return [], "source audio metadata did not identify a safe candidate"

    best_score, best_item, best_reasons = safe[0]
    # The margin uses every scored candidate, including candidates rejected by a
    # hard conflict. A near-tie is never hidden merely because one row failed a gate.
    runner_up = max(
        (
            score
            for score, item, _reasons in scored
            if str(item.get("path") or "") != str(best_item.get("path") or "")
        ),
        default=0.0,
    )
    if best_score - runner_up >= 10.0:
        chosen = dict(best_item)
        chosen["_match_reason"] = (
            f"Source audio metadata rescue [{MATCH_ENGINE_BUILD}] "
            f"{best_score:.0f}: " + ", ".join(best_reasons)
        )
        return [chosen], chosen["_match_reason"]

    surfaced: List[dict] = []
    for score, item, reasons in safe[:10]:
        candidate = dict(item)
        candidate["_match_reason"] = (
            f"Source audio metadata candidate [{MATCH_ENGINE_BUILD}] "
            f"{score:.0f}: " + ", ".join(reasons)
        )
        surfaced.append(candidate)
    return surfaced, "source audio metadata candidates remained tied"


def select_identity_rescue(
    query_metas: List[Dict[str, Any]],
    original_path: str,
    candidates: List[dict],
) -> Tuple[List[dict], str]:
    """Select only candidates supported by independent structured evidence."""
    safe: List[Tuple[float, dict, List[str]]] = []
    for item in candidates:
        best_score = 0.0
        best_reasons: List[str] = []
        for meta in query_metas:
            score, reasons = score_identity_rescue(meta, original_path, item)
            if score > best_score:
                best_score, best_reasons = score, reasons
        reason_set = set(best_reasons)
        query_has_artist = any(
            str(meta.get("artist") or meta.get("album_artist") or "").strip()
            for meta in query_metas
        )
        hard_conflict = (
            "VERSION MISMATCH" in reason_set
            or (query_has_artist and "artist differs" in reason_set)
            or "track differs" in reason_set
            or "disc differs" in reason_set
        )
        title_safe = (
            "title identity" in reason_set
            or any(reason.startswith("title character close ") for reason in best_reasons)
        )
        # The aggressive title key is allowed only with independent identity.
        # Exact path suffix can stand in for a translated/missing artist tag,
        # but album identity remains mandatory.
        identity_safe = (
            "album identity" in reason_set
            and (
                "artist compatible" in reason_set
                or "exact path suffix" in reason_set
            )
        )
        query_has_track = any(parse_intish(meta.get("track")) is not None for meta in query_metas)
        locator_safe = (
            not query_has_track
            or "track number" in reason_set
            or "exact path suffix" in reason_set
        )
        if (
            best_score >= 82.0
            and not hard_conflict
            and title_safe
            and "version compatible" in reason_set
            and identity_safe
            and locator_safe
        ):
            safe.append((best_score, item, best_reasons))

    # De-duplicate physical paths before deciding whether evidence is unique.
    unique: Dict[str, Tuple[float, dict, List[str]]] = {}
    for entry in safe:
        path_value = str(entry[1].get("path") or "")
        if path_value and (path_value not in unique or entry[0] > unique[path_value][0]):
            unique[path_value] = entry
    safe = sorted(unique.values(), key=lambda entry: entry[0], reverse=True)
    if not safe:
        return [], "no generic evidence rescue"

    if len(safe) == 1:
        score, item, reasons = safe[0]
        chosen = dict(item)
        chosen["_match_reason"] = (
            f"Generic evidence rescue [{MATCH_ENGINE_BUILD}] {score:.0f}: "
            + ", ".join(reasons)
        )
        return [chosen], chosen["_match_reason"]

    # When several copies have identical metadata, an exact relative-path suffix
    # identifies the intended physical file without imposing a root/format bias.
    exact_tail = [
        entry for entry in safe
        if "exact path suffix" in set(entry[2])
    ]
    if len(exact_tail) == 1:
        score, item, reasons = exact_tail[0]
        chosen = dict(item)
        chosen["_match_reason"] = (
            f"Generic path-identity rescue [{MATCH_ENGINE_BUILD}] {score:.0f}: "
            + ", ".join(reasons)
        )
        return [chosen], chosen["_match_reason"]

    surfaced: List[dict] = []
    for score, item, reasons in safe[:10]:
        candidate = dict(item)
        candidate["_match_reason"] = (
            f"Generic evidence candidate [{MATCH_ENGINE_BUILD}] {score:.0f}: "
            + ", ".join(reasons)
        )
        surfaced.append(candidate)
    return surfaced, "multiple generic evidence candidates"


def score_roon_candidate(meta: Dict[str, Any], orig_path: str, item: dict) -> Tuple[float, List[str]]:
    """Compatibility wrapper around the source-neutral identity scorer."""
    return score_track_identity(
        query_track_identity(meta, orig_path),
        indexed_track_identity(item),
    )

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
    cancel_flag: Optional[Callable[[], bool]] = None,
    source_base_dir: Optional[str] = None,           # original playlist folder for relative source paths
):
    """Repair a playlist using a pre-built music index (import-safe)."""

    def check_cancelled() -> None:
        if cancel_flag and cancel_flag():
            raise RepairCancelled("Repair cancelled.")

    def _path_is_in_roots(path_value: str, roots: Optional[List[str]]) -> bool:
        if not roots:
            return True
        import ntpath
        try:
            candidate = ntpath.normcase(ntpath.abspath(ntpath.normpath(str(path_value))))
        except Exception:
            return False
        for root_value in roots:
            try:
                root = ntpath.normcase(ntpath.abspath(ntpath.normpath(str(root_value))))
                if ntpath.commonpath([candidate, root]) == root:
                    return True
            except (ValueError, OSError, TypeError):
                continue
        return False

    try:
        index_stat = os.stat(index_path)
        index_fingerprint = (os.path.abspath(index_path), int(index_stat.st_size), int(index_stat.st_mtime_ns))
    except OSError:
        index_fingerprint = (os.path.abspath(index_path), None, None)
    roots_key = tuple(sorted(str(root).rstrip("\\/").casefold() for root in (allowed_roots or [])))
    context_key = (index_fingerprint, roots_key)

    with _REPAIR_CONTEXT_LOCK:
        cached = _REPAIR_CONTEXT_CACHE.get("value") if _REPAIR_CONTEXT_CACHE.get("key") == context_key else None
        if cached is None:
            with open(index_path, "r", encoding="utf-8") as f:
                music_index = json.load(f)

            # Older indexes may contain the same physical file once through a
            # parent Music Root and again through a child Root. Matching works on
            # physical files, so collapse those historical duplicates before any
            # candidate indexes or safety margins are calculated.
            unique_music_index: list[dict] = []
            position_by_path: Dict[str, int] = {}
            for item in music_index if isinstance(music_index, list) else []:
                if not isinstance(item, dict):
                    continue
                path_value = str(item.get("path") or "")
                path_key = (
                    ntpath.normcase(ntpath.normpath(path_value))
                    if path_value
                    else ""
                )
                if not path_key:
                    unique_music_index.append(item)
                    continue
                previous_position = position_by_path.get(path_key)
                if previous_position is None:
                    position_by_path[path_key] = len(unique_music_index)
                    unique_music_index.append(item)
                else:
                    unique_music_index[previous_position] = item
            music_index = unique_music_index

            # Matching must use only the roots enabled for this repair run. The
            # persistent index may contain backup/test copies of the same track.
            scoped_music_index = [
                item for item in music_index
                if _path_is_in_roots(str(item.get("path") or ""), allowed_roots)
            ]
            by_dur, by_title = build_indexes(scoped_music_index)
            roon_by_title, roon_by_token = build_roon_indexes(scoped_music_index)
            identity_by_title, identity_by_gram = build_identity_rescue_indexes(scoped_music_index)
            global_items_by_title: Dict[str, List[dict]] = defaultdict(list)
            for item in music_index:
                title_key = title_identity_key(str(item.get("title") or ""))
                if title_key:
                    global_items_by_title[title_key].append(item)
            cached = (
                scoped_music_index,
                by_dur,
                by_title,
                roon_by_title,
                roon_by_token,
                identity_by_title,
                identity_by_gram,
                global_items_by_title,
            )
            _REPAIR_CONTEXT_CACHE["key"] = context_key
            _REPAIR_CONTEXT_CACHE["value"] = cached

    (
        scoped_music_index,
        by_dur,
        by_title,
        roon_by_title,
        roon_by_token,
        identity_by_title,
        identity_by_gram,
        global_items_by_title,
    ) = cached

    # Matching remains self-contained: the cache only removes repeated loading and
    # index construction; it does not alter candidates, scores, or thresholds.
    indexed_item_by_path = {
        ntpath.normcase(ntpath.normpath(str(item.get("path") or ""))): item
        for item in scoped_music_index
        if item.get("path")
    }
    source_audio_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def cached_source_audio_identity(path_value: str) -> Optional[Dict[str, Any]]:
        """Read each old source file at most once during one playlist repair."""
        source_path = str(path_value or "")
        if source_path and not ntpath.isabs(source_path):
            base_dir = source_base_dir or ntpath.dirname(ntpath.abspath(playlist_path))
            source_path = ntpath.normpath(
                ntpath.join(base_dir, source_path)
            )
        key = ntpath.normcase(ntpath.normpath(source_path))
        if key not in source_audio_cache:
            source_audio_cache[key] = read_source_audio_identity(source_path)
        cached_meta = source_audio_cache[key]
        return dict(cached_meta) if cached_meta is not None else None

    def verify_with_source_audio(
        original_path: str,
    ) -> Tuple[List[dict], str, Optional[Dict[str, Any]]]:
        """Use real source tags only as a final verifier for unresolved rows."""
        source_meta = cached_source_audio_identity(original_path)
        if source_meta is None:
            return [], "source audio metadata unavailable", None
        rescue_pool = identity_rescue_candidate_pool(
            str(source_meta.get("title") or ""),
            identity_by_title,
            identity_by_gram,
        )
        rescue_pool = apply_format_policy(
            rescue_pool,
            mode=format_mode,
            prefer=format_priority_list,
            strict_ext=strict_ext,
        )
        rescued, rescue_note = select_source_audio_rescue(
            source_meta,
            original_path,
            rescue_pool,
        )
        return rescued, rescue_note, source_meta

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

    def find_exact_filename_identity(orig_path: str, meta: Dict[str, Any]) -> List[dict]:
        """Conservative fallback for exported paths whose tags differ from filenames.

        It requires the normalized full filename stem to be identical and, when
        available, the album folder to agree. This recovers cases such as
        DelusionAll/Delusion:All and ExistExit/Exist/Exit without using another
        resolved row or loose fuzzy matching.
        """
        query_name = re.split(r"[\\/]", str(orig_path or ""))[-1]
        query_stem = norm_preserve_qualifiers(os.path.splitext(query_name)[0])
        if not query_stem:
            return []
        album_q = compact_identity(str(meta.get("album") or ""))
        found: List[dict] = []
        seen: set[str] = set()
        for item in scoped_music_index:
            path_value = str(item.get("path") or "")
            if not path_value or path_value in seen:
                continue
            candidate_name = re.split(r"[\\/]", path_value)[-1]
            candidate_stem = norm_preserve_qualifiers(os.path.splitext(candidate_name)[0])
            if candidate_stem != query_stem:
                continue
            if album_q and album_q not in item_album_keys(item):
                continue
            seen.add(path_value)
            found.append(item)
        return apply_format_policy(
            found,
            mode=format_mode,
            prefer=format_priority_list,
            strict_ext=strict_ext,
        )

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
        title_raw_query = str(query.get("title") or title_from_filename(orig_path))
        candidate_pool = roon_candidate_pool(title_raw_query, roon_by_title, roon_by_token)
        for item in candidate_pool:
            score, reasons = score_roon_candidate(query, orig_path, item)
            if score > 0:
                scored.append((score, item, reasons))
        if not scored:
            rescue_pool = identity_rescue_candidate_pool(
                title_raw_query,
                identity_by_title,
                identity_by_gram,
            )
            rescue_pool = apply_format_policy(
                rescue_pool,
                mode=format_mode,
                prefer=format_priority_list,
                strict_ext=strict_ext,
            )
            rescued, rescue_note = select_identity_rescue(
                [query],
                orig_path,
                rescue_pool,
            )
            if rescued:
                return rescued, rescue_note
            return [], "no Roon metadata match"
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][0]
        # Keep the established score threshold and margin, then apply hard safety
        # vetoes before any later provenance-aware rescue stage.
        threshold = 78.0
        close = [x for x in scored if x[0] >= max(threshold - 8, best - 7)]
        best_reasons = scored[0][2]
        # Track/Disc disagreement must never be silently outvoted by title,
        # artist, album or path score. Path-derived inputs may still be rescued
        # later by real source-audio tags and duration.
        hard_conflicts = {
            "VERSION MISMATCH", "artist differs", "track differs", "disc differs",
        }
        best_conflict_free = not any(reason in hard_conflicts for reason in best_reasons)
        best_order_mismatch = bool(
            {"track differs", "disc differs"} & set(best_reasons)
        )
        identity_evidence = sum(reason in {
            "title exact", "title close", "artist compatible", "artist close",
            "album identity", "album close", "track number", "disc number", "path suffix"
        } for reason in best_reasons)
        # Require multiple independent clues. A title plus one supporting identity
        # clue is enough for sparse M3U data; richer XLSX rows naturally provide more.
        evidence_safe = identity_evidence >= 2
        if best_conflict_free and evidence_safe and best >= threshold and (len(scored) == 1 or best - scored[1][0] >= 8):
            item = dict(scored[0][1])
            item["_match_reason"] = f"Roon match {best:.0f}: " + ", ".join(scored[0][2])
            return [item], item["_match_reason"]

        # Path-neutral rescue for metadata-rich sources such as Roon XLSX.
        # Folder layout and filename structure may be completely different on another
        # device, so path evidence may raise confidence but is never required here.
        # Auto-resolve only when trusted row metadata identifies one physical file.
        source_name = str(query.get("source") or "").lower()
        if source_name == "roon_xlsx":
            title_q_exact = norm_preserve_qualifiers(str(query.get("title") or ""))
            track_q_exact = parse_intish(query.get("track"))
            disc_q_exact = parse_intish(query.get("disc"))
            rich_safe: List[dict] = []
            for candidate in candidate_pool:
                title_variants = candidate_title_variants(candidate)
                if not title_q_exact or title_q_exact not in title_variants:
                    continue
                if not any(version_compatible(str(query.get("title") or ""), value) for value in title_variants):
                    continue
                candidate_track = item_tag_track_number(candidate)
                candidate_disc = item_tag_disc_number(candidate)
                # Track is the strongest structured locator in XLSX. When both sides
                # provide it, disagreement is disqualifying. Missing candidate data is
                # neutral only when artist or album gives independent support.
                if track_q_exact is not None and candidate_track is not None and candidate_track != track_q_exact:
                    continue
                if disc_q_exact is not None and candidate_disc is not None and candidate_disc != disc_q_exact:
                    continue
                source_artist_values = meaningful_artist_identities(
                    query.get("artist"),
                    query.get("album_artist"),
                )
                artist_ok = any(
                    artist_compatible(source_value, candidate_value)
                    for source_value in source_artist_values
                    for candidate_value in item_artist_variants(candidate)
                )
                album_key = compact_identity(str(query.get("album") or ""))
                album_ok = bool(album_key and album_key in item_album_keys(candidate))
                track_ok = track_q_exact is not None and candidate_track == track_q_exact
                disc_ok = disc_q_exact is not None and candidate_disc == disc_q_exact
                # Track/disc numbers are locators, not identities: many unrelated
                # albums contain "01 Intro", "09 Time", and similar names. They
                # can support artist/album evidence but can never replace it.
                # This keeps a sole same-named file by another artist out of
                # Resolved even when its track/disc numbers happen to match.
                source_artist_present = bool(source_artist_values)
                # If XLSX supplied an artist, that identity must agree. Album and
                # track numbers may support an artist match but cannot replace it.
                identity_ok = artist_ok or (not source_artist_present and album_ok)
                if not identity_ok:
                    continue
                obj = dict(candidate)
                obj["_xlsx_identity_ok"] = identity_ok
                rich_safe.append(obj)

            unique_rich: List[dict] = []
            seen_rich: set[str] = set()
            for candidate in rich_safe:
                candidate_path = str(candidate.get("path") or "")
                if candidate_path and candidate_path not in seen_rich:
                    seen_rich.add(candidate_path)
                    unique_rich.append(candidate)
            if len(unique_rich) == 1:
                item = dict(unique_rich[0])
                evidence = ["exact title"]
                if track_q_exact is not None and item_tag_track_number(unique_rich[0]) == track_q_exact:
                    evidence.append("track")
                if disc_q_exact is not None and item_tag_disc_number(unique_rich[0]) == disc_q_exact:
                    evidence.append("disc")
                if item.get("_xlsx_identity_ok"):
                    evidence.append("artist/album identity")
                item["_match_reason"] = (
                    f"Path-neutral XLSX identity [{MATCH_ENGINE_BUILD}]: " + ", ".join(evidence)
                )
                return [item], item["_match_reason"]
            if len(unique_rich) > 1:
                out_rich: List[dict] = []
                for candidate in unique_rich[:10]:
                    obj = dict(candidate)
                    obj["_match_reason"] = f"Path-neutral XLSX candidate [{MATCH_ENGINE_BUILD}]"
                    out_rich.append(obj)
                return out_rich, "multiple path-neutral XLSX candidates"

        # Conservative rescue for Roon paths rejected only because the folder artist
        # uses separators such as _, -, spaces or wave dashes, or the file tag adds
        # an explicit feat/with credit. No fuzzy title is allowed here.
        title_raw_q = str(query.get("title") or title_from_filename(orig_path))
        title_q = norm_preserve_qualifiers(title_raw_q)
        artist_q = str(query.get("artist") or query.get("album_artist") or "")
        album_key_q = compact_identity(str(query.get("album") or ""))
        track_q = parse_intish(query.get("track"))
        safe: List[dict] = []
        if (
            title_q
            and artist_q
            and album_key_q
            and track_q is not None
            and not best_order_mismatch
        ):
            for item in candidate_pool:
                item_path = str(item.get("path") or "")
                if not item_path:
                    continue
                title_variants = candidate_title_variants(item)
                if title_q not in title_variants:
                    continue
                if not any(version_compatible(title_raw_q, value) for value in title_variants):
                    continue
                if not any(artist_compatible(artist_q, value) for value in item_artist_variants(item)):
                    continue
                if album_key_q not in item_album_keys(item):
                    continue
                if item_track_number(item) != track_q:
                    continue
                safe.append(item)

        # De-duplicate paths. Auto-resolve only when the safe combination identifies
        # one physical file; otherwise keep it in Ambiguous for human review.
        unique_safe: List[dict] = []
        seen_paths: set[str] = set()
        for item in safe:
            path_value = str(item.get("path") or "")
            if not path_value or path_value in seen_paths:
                continue
            seen_paths.add(path_value)
            unique_safe.append(item)
        if len(unique_safe) == 1:
            item = dict(unique_safe[0])
            item["_match_reason"] = (
                "Roon safe identity: exact title, compatible artist, "
                "album identity, track number"
            )
            return [item], item["_match_reason"]

        # A low score does not always mean that no useful candidate exists.
        # Cross-library exports commonly retain the exact filename/title while
        # artist and album tags change language, aliases or release suffixes.
        # Surface those candidates for human review, but mark them so that a
        # single candidate can never be mistaken for an automatic resolution.
        query_name = re.split(r"[\\/]", str(orig_path or ""))[-1]
        query_stem = norm_preserve_qualifiers(os.path.splitext(query_name)[0])
        query_title = norm_preserve_qualifiers(title_raw_query)
        close_paths = {
            str(candidate.get("path") or "")
            for _score, candidate, _reasons in close
        }
        safe_paths = {
            str(candidate.get("path") or "")
            for candidate in unique_safe
        }
        review_only: List[dict] = []
        for score, candidate, reasons in scored:
            path_value = str(candidate.get("path") or "")
            if not path_value or path_value in close_paths or path_value in safe_paths:
                continue
            candidate_name = re.split(r"[\\/]", path_value)[-1]
            candidate_stem = norm_preserve_qualifiers(
                os.path.splitext(candidate_name)[0]
            )
            exact_filename = bool(query_stem and candidate_stem == query_stem)
            exact_title = bool(
                query_title and query_title in candidate_title_variants(candidate)
            )
            if not (exact_filename or exact_title):
                continue
            obj = dict(candidate)
            obj["_requires_manual_review"] = True
            evidence = []
            if exact_filename:
                evidence.append("exact filename")
            if exact_title:
                evidence.append("exact title")
            obj["_manual_review_reason"] = ", ".join(evidence)
            review_only.append(obj)

        out = []
        # Include safe candidates first so the user sees the most relevant choices,
        # but do not silently choose among multiple versions.
        surfaced = unique_safe + [x[1] for x in close] + review_only
        seen_paths = set()
        for candidate in surfaced:
            path_value = str(candidate.get("path") or "")
            if not path_value or path_value in seen_paths:
                continue
            seen_paths.add(path_value)
            obj = dict(candidate)
            score_entry = next((x for x in scored if x[1].get("path") == path_value), None)
            if score_entry:
                obj["_match_reason"] = f"{score_entry[0]:.0f}: " + ", ".join(score_entry[2])
                if obj.get("_requires_manual_review"):
                    obj["_match_reason"] += (
                        " [manual review only: "
                        + str(obj.get("_manual_review_reason") or "low confidence")
                        + "]"
                    )
            elif candidate in unique_safe:
                obj["_match_reason"] = "safe identity candidate"
            out.append(obj)
            if len(out) >= 10:
                break

        # The first-stage candidates remain authoritative. The generic stage may
        # turn this row into Resolved only when independent evidence identifies a
        # single file; otherwise preserve the original Ambiguous candidate list.
        rescue_pool = identity_rescue_candidate_pool(
            title_raw_query,
            identity_by_title,
            identity_by_gram,
        )
        rescue_pool = apply_format_policy(
            rescue_pool,
            mode=format_mode,
            prefer=format_priority_list,
            strict_ext=strict_ext,
        )
        rescued, rescue_note = select_identity_rescue(
            [query],
            orig_path,
            rescue_pool,
        )
        if len(rescued) == 1:
            return rescued, rescue_note
        if not out and rescued:
            return rescued, rescue_note
        if best_order_mismatch:
            for candidate in out:
                candidate["_requires_order_verification"] = True
        return out, f"Roon candidates; best score {best:.0f}"

    lines = read_playlist_text(playlist_path).splitlines(keepends=True)

    # Detect if playlist has any EXTINF lines
    has_extinf = any(l.lstrip().startswith("#EXTINF") for l in lines)

    out_lines: List[str] = []
    report_rows: List[List[str]] = []

    total = kept = repaired = ambiguous = failed = 0
    duplicate_target_conflicts = 0
    reused_target_rows = 0
    resolved_targets: Dict[str, Dict[str, Any]] = {}
    conflicted_targets: set[str] = set()

    def reuse_identity_compatible(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        """Reuse is safe only when the playlist literally repeats one source path."""
        first_path = str(first.get("path") or "").replace("/", "\\")
        second_path = str(second.get("path") or "").replace("/", "\\")
        if not first_path or not second_path:
            return False
        return ntpath.normcase(ntpath.normpath(first_path)) == ntpath.normcase(
            ntpath.normpath(second_path)
        )

    def add_report(
        row_index: int,
        status: str,
        extinf_line: str,
        extinf_duration: str,
        extinf_display: str,
        original_path: str,
        written_path: str,
        notes: str,
    ) -> int:
        report_index = len(report_rows)
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
        return report_index

    def register_resolved_target(
        *,
        target_path: str,
        source_meta: Dict[str, Any],
        original_path: str,
        row_index: int,
        out_line_index: int,
        report_index: int,
    ) -> bool:
        """Keep target assignment one-to-one and downgrade both sides on conflict."""
        nonlocal repaired, ambiguous, duplicate_target_conflicts, reused_target_rows

        target_key = os.path.normcase(os.path.normpath(str(target_path)))

        def downgrade(entry: Dict[str, Any], other_row: int) -> None:
            nonlocal repaired, ambiguous, duplicate_target_conflicts
            out_lines[entry["out_line_index"]] = entry["original_path"]
            report = report_rows[entry["report_index"]]
            report[1] = "AMBIGUOUS_TARGET_CONFLICT"
            report[6] = entry["original_path"]
            report[7] = (
                f"candidates: {target_path} || target also claimed by distinct "
                f"source row {other_row}; kept unresolved for safety"
            )
            repaired -= 1
            ambiguous += 1
            duplicate_target_conflicts += 1

        current = {
            "meta": source_meta,
            "original_path": original_path,
            "row_index": row_index,
            "out_line_index": out_line_index,
            "report_index": report_index,
        }

        if target_key in conflicted_targets:
            downgrade(current, -1)
            return False

        previous = resolved_targets.get(target_key)
        if previous is None:
            resolved_targets[target_key] = current
            return True

        if reuse_identity_compatible(previous["meta"], source_meta):
            reused_target_rows += 1
            note = report_rows[report_index][7]
            report_rows[report_index][7] = (
                note + " || exact duplicate source row"
            ).strip(" |")
            return True

        downgrade(previous, row_index)
        downgrade(current, int(previous["row_index"]))
        conflicted_targets.add(target_key)
        resolved_targets.pop(target_key, None)
        return False

    if has_extinf:
        i = 0
        row_index = 0
        while i < len(lines):
            check_cancelled()
            line = lines[i].rstrip("\r\n")
            out_lines.append(line)

            if line.startswith("#EXTINF") and i + 1 < len(lines):
                total += 1
                dur, disp = parse_extinf(line)
                original_path = lines[i + 1].rstrip("\r\n")

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

                # Preserve every legacy one-candidate result.  Only rows that
                # would otherwise be Ambiguous receive structured ranking.
                if len(all_matches) > 1:
                    ranked, _rank_note = rank_ambiguous_extinf_candidates(
                        disp,
                        original_path,
                        dur,
                        all_matches,
                    )
                    all_matches = ranked

                # A stale duration or exporter-damaged title can leave the
                # legacy duration bucket empty. Search a bounded title-identity
                # pool, then require album/artist/track evidence before surfacing
                # or selecting anything.
                if not all_matches:
                    query_metas = extinf_query_metadata(disp, original_path, dur)
                    rescue_pool: List[dict] = []
                    rescue_seen: set[str] = set()
                    for query_meta in query_metas:
                        for item in identity_rescue_candidate_pool(
                            str(query_meta.get("title") or ""),
                            identity_by_title,
                            identity_by_gram,
                        ):
                            path_value = str(item.get("path") or "")
                            if path_value and path_value not in rescue_seen:
                                rescue_seen.add(path_value)
                                rescue_pool.append(item)
                    rescue_pool = apply_format_policy(
                        rescue_pool,
                        mode=format_mode,
                        prefer=format_priority_list,
                        strict_ext=strict_ext,
                    )
                    rescued, _rescue_note = select_identity_rescue(
                        query_metas,
                        original_path,
                        rescue_pool,
                    )
                    if rescued:
                        all_matches = rescued

                source_audio_meta: Optional[Dict[str, Any]] = None
                source_audio_verified = False

                # The source file itself is stronger evidence than stale EXTINF
                # text. Use it only when the normal result is unresolved.
                if len(all_matches) != 1:
                    rescued, _source_note, verified_meta = verify_with_source_audio(
                        original_path
                    )
                    if len(rescued) == 1:
                        all_matches = rescued
                        source_audio_meta = verified_meta
                        source_audio_verified = True
                    elif rescued and not all_matches:
                        all_matches = rescued

                candidate_safe = False
                safety_note = ""
                if len(all_matches) == 1:
                    selected = all_matches[0]
                    new_path = selected["path"]
                    raw_selected = indexed_item_by_path.get(
                        ntpath.normcase(ntpath.normpath(str(new_path))),
                        selected,
                    )
                    if source_audio_verified and source_audio_meta is not None:
                        target_title_key = title_identity_key(
                            str(raw_selected.get("title") or "")
                        )
                        candidate_safe, safety_note = duplicate_duration_consistency(
                            raw_selected,
                            global_items_by_title.get(target_title_key, []),
                        )
                        if candidate_safe:
                            candidate_safe, safety_note = path_candidate_safe(
                                source_audio_meta,
                                raw_selected,
                            )
                    else:
                        candidate_safe, safety_note = extinf_candidate_safe(
                            disp or "",
                            original_path,
                            dur,
                            raw_selected,
                        )

                    # A unique normal candidate can still be rejected because
                    # the export text is truncated or stale. Retry against the
                    # real source tags without weakening the original gate.
                    if not candidate_safe and not source_audio_verified:
                        rescued, _source_note, verified_meta = verify_with_source_audio(
                            original_path
                        )
                        if len(rescued) == 1:
                            all_matches = rescued
                            source_audio_meta = verified_meta
                            source_audio_verified = True
                        if source_audio_verified and source_audio_meta is not None:
                            selected = all_matches[0]
                            new_path = selected["path"]
                            raw_selected = indexed_item_by_path.get(
                                ntpath.normcase(ntpath.normpath(str(new_path))),
                                selected,
                            )
                            target_title_key = title_identity_key(
                                str(raw_selected.get("title") or "")
                            )
                            candidate_safe, safety_note = duplicate_duration_consistency(
                                raw_selected,
                                global_items_by_title.get(target_title_key, []),
                            )
                            if candidate_safe:
                                candidate_safe, safety_note = path_candidate_safe(
                                    source_audio_meta,
                                    raw_selected,
                                )

                if len(all_matches) == 1:
                    selected = all_matches[0]
                    new_path = selected["path"]
                    if not candidate_safe:
                        out_lines.append(original_path)
                        ambiguous += 1
                        reason = str(selected.get("_match_reason") or "")
                        note = (
                            f"candidates: {new_path} || Resolved safety gate: "
                            f"{safety_note}"
                        )
                        if reason:
                            note += f" || match details: {reason}"
                        add_report(
                            row_index,
                            "AMBIGUOUS_SAFETY_CONFLICT",
                            line,
                            str(dur),
                            disp or "",
                            original_path,
                            original_path,
                            note,
                        )
                    else:
                        out_line_index = len(out_lines)
                        out_lines.append(new_path)
                        repaired += 1
                        report_index = add_report(
                            row_index,
                            "REPAIRED",
                            line,
                            str(dur),
                            disp or "",
                            original_path,
                            new_path,
                            str(selected.get("_match_reason") or ""),
                        )
                        register_resolved_target(
                            target_path=new_path,
                            source_meta=(
                                source_audio_meta
                                if source_audio_verified and source_audio_meta is not None
                                else {"path": original_path}
                            ),
                            original_path=original_path,
                            row_index=row_index,
                            out_line_index=out_line_index,
                            report_index=report_index,
                        )
                elif len(all_matches) > 1:
                    out_lines.append(original_path)
                    ambiguous += 1
                    cand_note = "candidates: " + " | ".join(m["path"] for m in all_matches[:10])
                    details = " || ".join(
                        str(match.get("_match_reason") or "")
                        for match in all_matches[:10]
                        if match.get("_match_reason")
                    )
                    if details:
                        cand_note += " || match details: " + details
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
            check_cancelled()
            line = raw.rstrip("\r\n")

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
            source_audio_meta: Optional[Dict[str, Any]] = None
            source_audio_verified = False
            if roon_like:
                matches, match_note = find_matches_roon(original_path, pending_roon_meta)
            else:
                generic_meta = parse_generic_absolute_path(original_path)
                matches, match_note = find_matches_roon(original_path, generic_meta)
                if not matches:
                    matches = find_exact_filename_identity(original_path, generic_meta)
                    if matches:
                        match_note = "MusicBee exact filename identity"
                        for item in matches:
                            item["_match_reason"] = (
                                f"MusicBee exact filename identity [{MATCH_ENGINE_BUILD}]"
                            )
                if len(matches) == 1 and "_match_reason" not in matches[0]:
                    matches[0]["_match_reason"] = (
                        matches[0].get("_match_reason", "")
                        + f" [MusicBee {MATCH_ENGINE_BUILD}]"
                    ).strip()

            requires_manual_review = (
                len(matches) == 1
                and bool(
                    matches[0].get("_requires_order_verification")
                    or matches[0].get("_requires_manual_review")
                )
            )

            # Apply the same source-file verifier to every PATH_ONLY exporter.
            # Missing files, unsafe candidates and ties leave the old result
            # untouched.
            if len(matches) != 1 or requires_manual_review:
                rescued, rescue_note, verified_meta = verify_with_source_audio(
                    original_path
                )
                if len(rescued) == 1:
                    matches = rescued
                    match_note = rescue_note
                    source_audio_meta = verified_meta
                    source_audio_verified = True
                    requires_manual_review = False
                elif rescued and not matches:
                    matches = rescued
                    match_note = rescue_note

            if pending_roon_meta is not None:
                current_meta = dict(pending_roon_meta)
            elif roon_like:
                current_meta = dict(parse_roon_m3u_path(original_path))
            else:
                current_meta = dict(generic_meta)
            if source_audio_verified and source_audio_meta is not None:
                current_meta = dict(source_audio_meta)
            current_meta.setdefault("path", original_path)
            pending_roon_meta = None

            candidate_safe = False
            safety_note = ""
            if len(matches) == 1 and not requires_manual_review:
                selected = matches[0]
                xlsx_identity_verified = bool(selected.get("_xlsx_identity_ok"))
                new_path = selected["path"]
                raw_selected = indexed_item_by_path.get(
                    ntpath.normcase(ntpath.normpath(str(new_path))),
                    selected,
                )
                target_title_key = title_identity_key(
                    str(raw_selected.get("title") or "")
                )
                candidate_safe, safety_note = duplicate_duration_consistency(
                    raw_selected,
                    global_items_by_title.get(target_title_key, []),
                )
                if candidate_safe:
                    candidate_safe, safety_note = path_candidate_safe(
                        current_meta,
                        raw_selected,
                    )
                    # The normal path gate compares the composite XLSX Artist
                    # field and can report an artist conflict even though the
                    # path-neutral XLSX verifier already matched the separate,
                    # meaningful Album Artist field.  Override only that one
                    # redundant veto; every title/version/order/duplicate gate
                    # remains authoritative.
                    if (
                        not candidate_safe
                        and xlsx_identity_verified
                        and safety_note == "artist conflict"
                    ):
                        candidate_safe = True
                        safety_note = ""

                # A weak exported path may point to the right unique candidate
                # and still fail the normal path gate. The real source tags may
                # replace that guess only when they independently identify one
                # safe candidate.
                if not candidate_safe and not source_audio_verified:
                    rescued, rescue_note, verified_meta = verify_with_source_audio(
                        original_path
                    )
                    if len(rescued) == 1:
                        matches = rescued
                        match_note = rescue_note
                        source_audio_meta = verified_meta
                        source_audio_verified = True
                    if source_audio_verified and source_audio_meta is not None:
                        selected = matches[0]
                        new_path = selected["path"]
                        raw_selected = indexed_item_by_path.get(
                            ntpath.normcase(ntpath.normpath(str(new_path))),
                            selected,
                        )
                        current_meta = dict(source_audio_meta)
                        current_meta.setdefault("path", original_path)
                        target_title_key = title_identity_key(
                            str(raw_selected.get("title") or "")
                        )
                        candidate_safe, safety_note = duplicate_duration_consistency(
                            raw_selected,
                            global_items_by_title.get(target_title_key, []),
                        )
                        if candidate_safe:
                            candidate_safe, safety_note = path_candidate_safe(
                                current_meta,
                                raw_selected,
                            )

            if len(matches) == 1 and not requires_manual_review:
                selected = matches[0]
                new_path = selected["path"]
                reason = selected.get("_match_reason") or match_note
                if not candidate_safe:
                    out_lines.append(original_path)
                    ambiguous += 1
                    note = (
                        f"candidates: {new_path} || Resolved safety gate: "
                        f"{safety_note}"
                    )
                    if reason:
                        note += f" || match details: {reason}"
                    add_report(
                        row_index,
                        "AMBIGUOUS_PATH_SAFETY_CONFLICT",
                        "",
                        "",
                        "",
                        original_path,
                        original_path,
                        note,
                    )
                else:
                    out_line_index = len(out_lines)
                    out_lines.append(new_path)
                    repaired += 1
                    report_index = add_report(
                        row_index,
                        "REPAIRED_PATH",
                        "",
                        "",
                        "",
                        original_path,
                        new_path,
                        reason,
                    )
                    register_resolved_target(
                        target_path=new_path,
                        source_meta=current_meta,
                        original_path=original_path,
                        row_index=row_index,
                        out_line_index=out_line_index,
                        report_index=report_index,
                    )
            elif matches:
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
                note = match_note if roon_like else "no match (no EXTINF)"
                if format_mode in ("strict", "fallback"):
                    note = f"no match after format_policy({format_mode}) (no EXTINF)"
                add_report(row_index, "FAILED_PATH", "", "", "",
                           original_path, original_path, note)

            row_index += 1

    check_cancelled()
    _atomic_write_text(output_path, "\n".join(out_lines) + "\n")

    report_buffer = io.StringIO(newline="")
    w = csv.writer(report_buffer)
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
    check_cancelled()
    _atomic_write_text(report_path, report_buffer.getvalue(), newline="")

    if verbose:
        print("====== 修復完成 (SAFE v5) ======")
        print(f"playlist: {playlist_path}")
        print(f"模式: {'EXTINF' if has_extinf else 'PATH_ONLY'}")
        print(f"歌單歌曲總數: {total}")
        print(f"原路徑可用: {kept}")
        print(f"自動修復成功: {repaired}")
        print(f"多筆命中未修: {ambiguous}")
        print(f"修復失敗: {failed}")
        print(f"唯一已解析檔案: {len(resolved_targets)}")
        print(f"合理重複使用: {reused_target_rows}")
        print(f"目標身份衝突: {duplicate_target_conflicts}")
        print(f"輸出歌單: {output_path}")
        print(f"報告檔: {report_path}")

    return {
        "total": int(total),
        "kept": int(kept),
        "repaired": int(repaired),
        "ambiguous": int(ambiguous),
        "failed": int(failed),
        "unique_resolved_files": int(len(resolved_targets)),
        "reused_target_rows": int(reused_target_rows),
        "duplicate_target_conflicts": int(duplicate_target_conflicts),
        "mode": "extinf" if has_extinf else "path_only",
        "playlist_path": str(playlist_path),
        "output_path": str(output_path),
        "report_path": str(report_path),
    }
