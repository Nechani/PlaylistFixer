# Playlist Fixer Full User Guide

Playlist Fixer is a local utility for repairing file-based playlists.

When your audio files still exist but playlists stop working because you changed computers, drive letters, folder locations, audio formats, devices, or Roon export paths, Playlist Fixer scans your music library, finds the correct files, and creates a new repaired playlist.

> Playlist Fixer does not modify your audio files and does not overwrite the original playlist.

---

## 1. What Playlist Fixer Can Do

Playlist Fixer is useful when:

- Old playlist paths no longer exist after moving to another computer
- A drive letter changed, such as `D:\Music` becoming `E:\Music`
- Music folders were moved or reorganized
- Audio formats were converted, such as FLAC to ALAC, WAV, MP3, or another format
- Playlists are moved between a computer, Mac, phone, or DAP
- A DAP loads only part of a playlist or cannot read it at all
- A Roon-exported M3U uses relative paths that do not work on another computer
- A Roon-exported XLSX came from another computer and all original absolute paths are different
- You want to review what was repaired automatically and manually correct any wrong match

Playlist Fixer is not intended for:

- Downloading missing audio files
- Editing audio tags or metadata
- Managing online playlists from streaming platforms such as Spotify or Apple Music
- Recovering files that no longer exist in any music folder
- Guaranteeing a fully automatic match when filenames, paths, or metadata are insufficient

---

## 2. Supported Formats

### 2.1 Supported Playlist Formats

- `.m3u`
- `.m3u8`
- Roon-exported `.m3u`
- Roon-exported `.xlsx`

For Roon XLSX files, Playlist Fixer can use title, artist, album, disc number, track number, and original path information.

A Roon M3U may use relative paths such as:

```text
../Artist/Album/1-02 Song.flac
```

Playlist Fixer parses the artist, album, disc number, track number, and filename instead of treating the path as a literal path on the current computer.

### 2.2 Supported Audio Formats

Common lossy formats:

- MP3
- AAC
- OGG Vorbis
- Opus
- MP4/M4A audio

Lossless and uncompressed formats:

- FLAC
- ALAC
- M4A
- WAV
- AIF
- AIFF
- AIFC
- APE
- WavPack (WV)

DSD:

- DSF
- DFF (best effort)

> Automatic matching quality depends on the metadata, filename, duration, and folder information available in each file.  
> Common formats such as FLAC, MP3, and M4A usually provide more complete metadata. WAV, some AIFF files, DSF, DFF, APE, and WV files may contain less consistent tag information.

---

## 3. Interface Overview

### Music Roots

Music Roots is the list of music folders already indexed by Playlist Fixer.

Each path has a checkbox.

The checkbox controls:

> Which Music Roots Repair is allowed to search and use.

This scope also applies to an original playlist path that still exists. If the original path is outside the checked Music Roots, Repair does not keep it automatically and searches only within the checked scope.

The checkbox does not control scanning and does not delete an existing index.

Music Roots are stored separately for each Windows user and computer. Restarting the program or temporarily disconnecting an external drive does not remove them. Only `Remove Selected` or `Clear All` removes them.

Moving the program folder to another computer does not import the previous computer's Music Roots. Old index data inside the program folder cannot add paths to the current computer's list.

The splitter between Music Roots and the track list can be dragged to change the height of the Music Roots area.

### Add Music Folders

Adds one or more folders containing audio files.

The normal Windows folder picker is used. After selecting one folder, you may continue adding more. Existing paths are not added twice.

A Music Root may show one of these states:

- `[Pending scan]`: newly added and not indexed yet
- `[Index missing]`: the path exists, but index data is missing or has not been created
- `[Unavailable]`: the folder or external drive is currently unavailable

A newly added folder that has not yet been scanned is marked:

```text
[Pending scan]
```

### Scan New Folders

Scans only newly added folders that are still marked `[Pending scan]`.

Existing indexed folders are skipped, so adding a small folder does not require rescanning a large library.

### Rescan Selected

Rescans the currently highlighted existing Music Root.

Use this when:

- Many tracks were added to the folder
- Tracks were deleted or moved
- Filenames or tags were changed
- You want to rebuild that folder's index

Other Music Roots are not affected.

### Remove Selected

Removes the selected path from Music Roots and from the index.

Clearing the checkbox does not remove a Music Root. Only Remove Selected does.

### Import Playlist(s)

Imports the playlist you want to repair.

For clarity, it is recommended to process one playlist at a time, save it, and then import the next playlist.

### Repair (Safe)

Analyzes the current playlist and tries to locate the correct file for each entry.

The first Repair runs immediately. If Repair has already been run for the same playlist, clicking `Repair (Safe)` again asks for confirmation.

After you confirm, Playlist Fixer clears the current unsaved Repair results and `✓` manual changes, then analyzes the playlist again using the currently checked Music Roots. Previously saved output files on disk are not deleted.

Repair does not overwrite the original playlist and does not create permanent repair progress until you save.

### View: Unresolved / Resolved

- **Unresolved**: entries that have not been repaired, have uncertain candidates, have no reliable match, or were manually changed but not yet saved
- **Resolved**: entries that were kept, repaired automatically, or have a saved manual selection

Unresolved shows Ambiguous and Failed entries in one table:

- `△`: Ambiguous — possible candidates were found, but manual confirmation is required
- `✕`: Failed — no reliable candidate was found; use Browse to select the file manually
- `✓`: manually fixed, but not yet saved

Ambiguous entries are shown before Failed entries by default. After Apply, the entry stays in the same position and changes to `✓`; it moves to Resolved only after Save.

Resolved is also an audit view. If an automatic match is wrong, you can still replace it manually. A manual change made in Resolved temporarily shows `✓` until it is saved.

### Candidates

Shows possible matching files for the currently selected entry.

### Browse

Lets you manually select the correct audio file when no reliable candidate is available.

### Apply

Applies the current selection.

In Unresolved, the entry stays in the same position and changes to `✓`. It does not move to Resolved until Save.

In Resolved, a manual change also shows `✓` temporarily.

Until Save is used, applied choices remain temporary for the current session.

### Save Fixed Playlist

Creates the repaired playlist and saves the current progress.

---

## 4. How Music Roots Work

### 4.1 Creating Your First Music Index

1. Click `Add Music Folders`
2. Select a folder containing audio files
3. The new path is shown as `[Pending scan]`
4. Click `Scan New Folders`
5. After a successful scan, the path becomes a regular Music Root

The path remains in the Music Roots list even if it is temporarily unavailable, cannot currently be read, or contains no indexed audio files. It is marked `[Unavailable]`, `[Index missing]`, or `[Pending scan]` as appropriate. Use `Remove Selected` or `Clear All` to remove it.

### 4.2 Adding Another Music Folder Later

For example, if you already have:

```text
C:\Music
D:\Lossless
```

and later add:

```text
E:\New Music
```

you only need to:

1. Click Add Music Folders
2. Select `E:\New Music`
3. Click `Scan New Folders`

Playlist Fixer scans only the new folder. It does not rescan `C:\Music` or `D:\Lossless`.

### 4.3 Updating an Existing Music Folder

If the contents of `C:\Music` change:

1. Highlight `C:\Music` in the Music Roots list
2. Click `Rescan Selected`
3. Confirm the rescan

Only that folder is updated.

### 4.4 Choosing the Repair Search Scope

For example:

```text
☑ C:\PC Music
☐ D:\DAP Music
```

Repair searches and uses files only from `C:\PC Music`.

`D:\DAP Music` remains indexed, but it is excluded from the current Repair search. Even if a `D:\DAP Music` path in the original playlist still exists, Repair does not keep it while that Music Root is unchecked.

If a checked Music Root is marked `[Index missing]` or `[Unavailable]`, Repair warns you before continuing.

This helps prevent:

- A PC playlist from being repaired to DAP copies
- A DAP playlist from being repaired to PC copies
- Confusion when the same track exists on multiple devices

---

## 5. Importing a Playlist

Click `Import Playlist(s)` and select one of the following:

- M3U
- M3U8
- Roon M3U
- Roon XLSX

After import, all playlist entries immediately appear in Unresolved.

Before Repair is run, each entry is marked:

```text
[NOT REPAIRED]
```

This means only that the entry has not been analyzed. It does not mean the track is broken.

### Standard M3U / M3U8

Playlist Fixer may use:

- Original path
- `#EXTINF`
- Title
- Artist
- Filename
- Duration
- Audio tags
- Folder structure

### Roon XLSX

A Roon XLSX may contain:

- Album Artist
- Track Artist
- Album
- Disc number
- Track number
- Title
- External ID
- Path

Even if the XLSX came from another computer with different drive letters and folder structures, Playlist Fixer attempts to match it using metadata and the current music index.

After a Roon XLSX is repaired, it is exported as a standard M3U. Playlist Fixer uses reliable Track Artist, Album Artist, and Title fields from the XLSX to create `#EXTINF` lines, so the repaired playlist does not lose normal M3U track information and become a path-only playlist. If duration is unavailable, `-1` is used; standard players can still read the playlist.

### Roon M3U

Common characteristics of Roon M3U files include:

- Relative paths
- `/` path separators
- No `#EXTINF`
- Filenames containing disc and track numbers
- Folder names reorganized by Roon

Playlist Fixer parses the Roon path structure before matching.

---

## 6. Running Repair

After you click `Repair (Safe)`, Playlist Fixer attempts the following:

1. Check whether the original path is still valid
2. Compare path suffixes and folder structure
3. Compare filename and duration
4. Compare title, artist, and album
5. Compare disc and track numbers
6. Compare Roon XLSX metadata with local audio tags
7. Compare Roon M3U path structure with the current index
8. Calculate a combined confidence score from multiple signals

To avoid incorrect repairs, Playlist Fixer does not automatically choose a file based only on a matching title.

If two candidates are too close, the entry remains Ambiguous for manual review.

---

## 7. Repair Statuses

After Repair, an entry may have one of these statuses:

### Kept original

The original path is still valid and is inside the checked Music Roots, so it does not need to be changed.

### Auto repaired

Playlist Fixer found one clear, high-confidence candidate and re-linked the entry automatically.

### Manual selection

You manually selected the correct file.

### Ambiguous (`△`)

One or more reasonable candidates were found, but Playlist Fixer could not safely determine which one is correct. Manual confirmation is required.

### Failed (`✕`)

No sufficiently reliable candidate was found. Use Browse to locate the correct audio file manually.

### Manually fixed, not saved (`✓`)

A manual selection has been applied but has not yet been saved. This is a temporary state.

---

## 8. Unresolved and Resolved

### Unresolved

Contains:

- Entries not yet repaired
- `△` Ambiguous entries
- `✕` Failed entries
- Entries with a selection that has not yet been applied
- `✓` entries that were manually fixed but not yet saved

Ambiguous and Failed entries appear in the same table, with `△` shown before `✕` by default.

After Apply, the entry stays in its current position and changes to `✓`. It moves to Resolved only after Save.

### Resolved

Contains:

- Kept original
- Auto repaired
- Saved manual selections

Resolved entries can still be edited. A new manual change shows `✓` until Save, then the mark disappears.

For example, an automatic match may confuse:

- Live and studio versions
- Remastered and original versions
- Different songs with the same title
- The same song from different albums
- Different formats or sample-rate versions

Select the entry in Resolved, choose another candidate or browse to the correct file, and click Apply.

---

## 9. Handling Ambiguous Entries

1. Select an Ambiguous entry marked `△` in Unresolved
2. Review the Candidates list
3. Select the correct file
4. Click Apply
5. The entry stays in place and changes to `✓`
6. Click `Save Fixed Playlist` to move it to Resolved

Pay special attention to:

- Artist
- Album
- Title
- Track number
- Live, Remaster, Deluxe, and similar version differences
- Which Music Root contains the candidate

---

## 10. Handling Failed Entries

1. Select a Failed entry marked `✕` in Unresolved
2. Click Browse
3. Locate and select the correct audio file
4. Click Apply
5. The entry stays in place and changes to `✓`
6. Click `Save Fixed Playlist` to move it to Resolved

If the audio file no longer exists, it cannot be repaired.

---

## 11. Temporary State and Saved Progress

This is an important safety feature.

### Repair Results Are Temporary

After Repair:

- Automatic results are displayed
- Ambiguous entries are marked `△`
- Failed entries are marked `✕`
- Manual Apply choices are marked `✓`
- `✓` entries remain in their current positions
- But no permanent repair progress has been created yet

If you leave the playlist without saving and import the original playlist again, it is treated as not permanently repaired.

If you run Repair again and confirm the rescan, the current view switches to a new temporary Repair state. Old saved progress is not mixed into the new Unresolved or Resolved display. The new results become the current saved progress only after Save.

### Save Creates Permanent Progress

After you click `Save Fixed Playlist`:

- A new repaired playlist is created
- The Repair report is saved
- Manual selections are saved
- Incomplete progress is saved
- `✓` entries in Unresolved move to Resolved
- Unsaved `✓` marks in Resolved disappear
- You can continue later

### Original and Repaired Playlists Use Separate Progress

For example:

```text
1.m3u
fixed_1_selected.m3u
```

These do not share the same repair state just because their names are similar.

- Opening the original `1.m3u`: treated as the original unrepaired playlist
- Opening the saved `fixed_1_selected.m3u`: loads the saved repair progress

---

## 12. Saving the Repaired Playlist

Click `Save Fixed Playlist` to create:

```text
fixed_*_selected.m3u
```

The original playlist is not overwritten.

A repaired Roon XLSX is also exported as M3U.

You may save before every entry is resolved. The saved repaired playlist can be opened later to continue working on the remaining entries.

---

## 13. Reports and Progress Files

Playlist Fixer creates repair reports and progress files such as:

### repair_report_*.csv

Contains analysis and matching results for each entry.

It may include:

- Original track information
- Status
- Selected path
- Candidate information
- Match reason
- Roon metadata match score

### selections_*.json

Stores manual selections.

### Repair Progress Data

Stores officially saved progress so long playlists can be resumed later.

### fixed_*_selected.m3u

The repaired playlist output.

> Do not delete reports or progress files unless you are willing to lose the saved repair progress.

---

## 14. Frequently Asked Questions

### Why does a newly added folder show Pending scan?

Because it has not been indexed yet. Click `Scan New Folders`. It becomes a regular Music Root only after a successful scan.

### Why does a Music Root show Index missing?

The path still exists, but the related index data is missing or has not been created. Scan or rescan that Music Root.

### Why does a Music Root show Unavailable?

The folder or external drive is not currently accessible. Reconnect the drive or restore the folder.

### Does Scan New Folders rescan my entire library?

No. It scans only newly added folders that are still Pending.

### When should I use Rescan Selected?

Use it when the contents, filenames, tags, or track count of an existing folder have changed.

### Does clearing a Music Root checkbox delete it?

No. It only excludes that Music Root from the current Repair scope, including whether original paths inside that root may be kept.

### Why does an existing original path get replaced?

The original path is outside the currently checked Music Roots. Repair uses only files inside the checked scope.

### Why do Music Roots remain when an external drive is disconnected?

Music Roots are stored separately for the current Windows user and computer. Temporarily disconnecting a drive does not delete the setting. Use `Remove Selected` or `Clear All` to remove it.

### Why are Music Roots different on another computer?

Each computer stores its own Music Roots. Index files carried inside the program folder do not add paths to another computer's Music Roots list.

### Why are all entries shown in Unresolved immediately after import?

Because Repair has not been run yet. Their status is Not repaired, not Failed.

### Why were some entries not repaired automatically?

Possible reasons include:

- Multiple similar candidates
- Missing metadata
- Too many songs with the same title
- Live, Remaster, or other version differences
- Too little information in the original playlist
- The audio file is not inside any indexed Music Root
- The correct Music Root is not checked for Repair

### Can Playlist Fixer repair a Roon XLSX exported from another computer?

Yes. Playlist Fixer uses Roon metadata and does not rely only on the original absolute path.

However, manual review may still be needed when tags are missing, many versions exist, or the local files differ significantly.

### Why does Apply not move an entry to Resolved immediately?

Apply creates a temporary manual change. The entry remains in place with `✓` and moves to Resolved only after Save.

### Why does clicking Repair (Safe) again show a confirmation?

Running Repair again clears the current unsaved automatic results and `✓` manual changes, then analyzes the playlist again with the currently checked Music Roots. Previously saved output files are not deleted.

### Why does a playlist appear unrepaired after I already ran Repair?

Because it was not saved. Repair results are temporary until Save is used.

### Can I save a partially repaired playlist?

Yes. After saving, you can reopen the repaired playlist and continue later.

### Does Playlist Fixer modify my original audio files?

No.

### Does Playlist Fixer overwrite the original playlist?

No. It creates a new `fixed_*_selected.m3u`.

### Is an internet connection required?

No. All scanning and repairing are performed locally.

---

## 15. Reporting a Problem

When reporting an issue, please include:

- Playlist Fixer version
- Operating system version
- Original playlist
- Roon XLSX or Roon M3U if the issue involves Roon
- Related Repair report
- selections file, if available
- Screenshot of the issue
- Whether the problem occurred during Import, Repair, Apply, or Save
- Expected result
- Actual result
- Which Music Roots were checked

You do not need to send:

- Your entire music library
- Large audio collections
- Private music content

When necessary, a small public test sample and its playlist are enough.

---

## 16. Safety and Privacy

Playlist Fixer:

- Does not modify audio files
- Does not overwrite original playlists
- Does not download or upload music
- Does not require internet access
- Processes everything locally
- Has no ads
- Has no paywall

---

## 17. Recommended Workflow

When using Playlist Fixer for the first time or repairing an important playlist:

1. Keep a backup of the original playlist
2. Test with a small playlist first
3. Verify the checked Music Roots
4. Review Resolved after Repair
5. Do not rely only on filenames for Ambiguous entries
6. Test the saved playlist in your player before processing a large collection

---

Playlist Fixer is designed around four principles:

- Safety: no destructive operations
- Transparency: repair results can be reviewed
- Recoverability: manual choices and progress can be saved
- Portability: designed for computer changes, path changes, format changes, and multiple devices

It exists for one purpose:

> To protect the playlists you built over years of listening.
