# Playlist Fixer

**Playlist Fixer repairs broken file-based playlists by reconnecting them to audio files that still exist in your music library.**

It is designed for playlists that stop working after files are moved, renamed, converted, reorganized, or transferred between computers and audio devices.

Playlist Fixer works locally, does not modify your music files, and does not overwrite the original playlist.

> If the file still exists somewhere, Playlist Fixer tries to find it.

---

## What It Can Repair

Playlist Fixer can help when:

- You move to a new computer or drive
- Music folders are reorganized
- Drive letters or root folders change
- Audio files are renamed
- Audio formats are converted
- Playlists are moved between PC, Mac, and DAP devices
- A DAP loads only part of a playlist
- Roon exports point to paths from another computer
- Roon forces you to export audio files together with an M3U, but you only want the playlist
- A playlist contains broken, outdated, relative, or device-specific paths

---

## Core Features

- Repair broken `.m3u` and `.m3u8` playlists
- Import and repair Roon `.xlsx` playlist exports
- Parse Roon-style relative-path `.m3u` exports
- Reconnect tracks after folder, filename, drive, device, or format changes
- Build a searchable local index of your music library
- Add new music folders without rescanning the entire library
- Rescan only the folder you choose
- Use Music Root checkboxes to control which libraries Repair may search
- Automatically classify tracks as:
  - Kept
  - Automatically repaired
  - Ambiguous
  - Failed
- Review all automatically repaired tracks in the Resolved view
- Manually replace an incorrect automatic match
- Choose between multiple candidates
- Browse for missing tracks manually
- Save unfinished repair progress and continue later
- Keep unsaved Repair results temporary
- Generate CSV reports for review and troubleshooting
- Save repaired playlists as `.m3u8` (UTF-8, recommended) or `.m3u` (legacy compatibility) without changing the original

---

## Roon Support

Playlist Fixer includes dedicated handling for Roon exports.

- Import Roon XLSX exports and rebuild them as M3U playlists
- Parse Roon M3U relative paths
- Match Roon exports against your existing local music library

### 🌟 Roon XLSX Support

Roon normally exports M3U playlists together with the referenced audio files.

If you only need the playlist, Playlist Fixer can use a Roon XLSX export to rebuild and export an M3U from your existing music library, without copying the audio files again.

It can also use metadata such as title, artist, album, disc number, track number, and original path to find matching files even when the XLSX came from another computer.

### Roon M3U Support

Roon M3U files may contain relative paths such as:

```text
../Artist/Album/1-02 Song.flac
```
---

## Supported Playlist Formats

- `.m3u`
- `.m3u8`
- Roon `.m3u` exports
- Roon `.xlsx` exports

---

## Supported Audio Formats

Playlist Fixer can scan and match the following audio formats:

### Lossy

- MP3
- AAC
- OGG Vorbis
- Opus
- MP4 / M4A audio

### Lossless and Uncompressed

- FLAC
- ALAC
- M4A
- WAV
- AIFF / AIF / AIFC
- APE
- WavPack (`.wv`)

### DSD

- DSF
- DFF

DSF and DFF support is best effort.

Matching quality depends on the metadata, filename, duration, path, and folder information available in each file.

---

## Safe by Design

Playlist Fixer is designed to avoid destructive changes:

- Music files are never modified
- Original playlists are not overwritten
- Repair results remain temporary until saved
- Low-confidence matches are not forced automatically
- Ambiguous results remain available for manual review
- Resolved tracks remain visible so automatic choices can be audited
- Reports are generated for transparency

---

## Typical Workflow

1. Add one or more music folders
2. Scan new folders to build the index
3. Select which Music Roots Repair may use
4. Import a playlist
5. Run **Repair (Safe)**
6. Review Unresolved and Resolved tracks
7. Correct any ambiguous, failed, or incorrect matches
8. Save the repaired playlist

When an indexed parent folder already contains a child folder, the child becomes ready immediately and can be selected independently for Repair. The existing index is reused in the background, so the same files are not scanned twice.

For detailed instructions, see the full manuals below.

---

## Documentation

- [English Manual](README_EN.md)
- [繁體中文說明書](README_ZH-TW.md)
- [日本語マニュアル](README_JP.md)

---

## What Playlist Fixer Does Not Do

Playlist Fixer does not:

- Download missing music files
- Edit audio tags or metadata
- Manage streaming-service playlists
- Repair Spotify, Apple Music, or other online playlists
- Guarantee automatic recovery when there is not enough reliable information

---

## Privacy

- No ads
- No paywall
- No network access required
- Local file processing only

---

## Status

Playlist Fixer is actively developed.

Bug reports, unusual playlist samples, and feedback are welcome.

---

## License

MIT License — free to use, modify, and distribute.
