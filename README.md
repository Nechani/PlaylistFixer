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
- Export a new repaired M3U playlist without changing the original

---

## Roon Support

Playlist Fixer includes dedicated handling for Roon exports.

### Roon XLSX

Roon XLSX exports can contain useful metadata such as:

- Title
- Track Artist
- Album Artist
- Album
- Disc number
- Track number
- Original path

Playlist Fixer uses this information to find matching local files even when the original absolute path belongs to another computer.

### Roon M3U

Roon may export relative paths such as:

```text
../Artist/Album/1-02 Song.flac
```

Playlist Fixer can interpret the artist, album, disc, track number, title, and path structure instead of treating the line as a normal local path only.

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

---

## Author and Contact

**Author:** Ne  
**GitHub:** https://github.com/Nechani  
**Issues and feedback:** plfixne@gmail.com  
**Support:** https://ko-fi.com/nechani

If Playlist Fixer saves you time or rescues a playlist you built over years, consider supporting development. ☕
