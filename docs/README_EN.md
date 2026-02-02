1. What is Playlist Fixer?
Playlist Fixer is a tool designed to repair broken playlist files
(.m3u / .m3u8) when music files still exist but paths, formats, or devices have changed.
This tool does not modify audio files.
It only fixes playlist references by re-linking them to existing music files.
Playlist Fixer is useful if you:
•	Changed computers (Windows ↔ macOS)
•	Moved or reorganized your music folders
•	Converted audio formats (FLAC → ALAC / WAV, etc.)
•	Migrated playlists between devices
•	Use DAPs (Digital Audio Players) that fail to load or miss tracks
•	Want to recover playlists that players like Roon, Foobar, or DAPs cannot read correctly
Playlist Fixer is NOT for:
•	Downloading missing music
•	Editing metadata or tags
•	Managing streaming playlists (Spotify / Apple Music online playlists)
________________________________________
2. Typical Use Cases
Playlist Fixer can help in many real-world scenarios:
💻 Computer Migration
•	Old playlist paths no longer exist after moving to a new PC or Mac
•	Music folder structure changed
🔄 Format Conversion
•	Original playlist points to .flac
•	Files are now .alac, .wav, or another format
🎧 DAP Playlist Repair
•	DAP cannot read playlists correctly
•	Songs are missing or partially loaded
•	Fix DAP playlists using your computer library
•	Or fix computer playlists using DAP-exported playlists
🔁 Cross-Device Playlist Recovery
•	Repair playlists created on a DAP and reuse them on a computer
•	Repair computer playlists so they work on a DAP
________________________________________
3. Before You Start
Supported Playlist Formats
•	.m3u
•	.m3u8
Supported Audio Files
Playlist Fixer works with existing audio files, including:
•	Common lossy formats (.mp3, .aac, .ogg, .opus)
•	Lossless formats (.flac, .wav, .aif, .aiff, .ape, .wv)
•	Apple containers (.m4a, .alac)
•	DSD formats (.dsf, .dff) (best-effort)
⚠️ If a file does not exist anywhere in your music folders, it cannot be recovered.
________________________________________
4. Step-by-Step Usage Guide
Step 1 – Add Music Folders
Click “Add Music Folder” and select one or more folders containing your music files.
These folders will be scanned to build a searchable index.
________________________________________
Step 2 – Scan / Rebuild Index
Click “Scan / Rebuild Index”.
This creates an index of all audio files so Playlist Fixer knows what is available.
You only need to do this again if you change your music folders.
________________________________________
Step 3 – Import Playlist(s)
Click **“Import Playlist(s)”** and select **a single** `.m3u` or `.m3u8` playlist file.
Playlist Fixer repairs **one playlist at a time**.  
Please complete and save the current playlist before importing another.________________________________________
Step 4 – Repair (Safe)
Click “Repair (Safe)”.
Playlist Fixer will analyze each playlist and classify entries into:
•	Kept – Already valid, no action needed
•	Repaired (Auto) – Fixed automatically
•	Ambiguous – Multiple possible matches found
•	Failed – No match found
Reports will be generated in the reports/ folder.
________________________________________
Step 5 – Review Unresolved Entries
Use the View selector:
•	Unresolved – Entries that still need attention
•	Resolved – Automatically or manually repaired entries (audit view)
Ambiguous
•	Select a row
•	Choose the correct file from the candidate list
•	Click Apply
Failed
•	Select a row
•	Click Browse
•	Manually pick the correct audio file
•	Click Apply
Applied fixes are kept in memory until saved.
________________________________________
Step 6 – Save Fixed Playlist
Click “Save Fixed Playlist”.
This will:
•	Generate a new playlist file (fixed_*_selected.m3u)
•	Save your manual repair selections
•	Remove resolved entries from the Unresolved view
⚠️ This is the only step that writes files to disk.
________________________________________
5. Reports & Output Files Explained
All repair-related files are stored in the reports/ folder.
Important Files
•	repair_report_*.csv
Detailed analysis of each playlist entry
•	fixed_*_selected.m3u
The repaired playlist file (final output)
•	selections_*.json
Your manual repair choices (used for recovery or auditing)
Do not delete these files unless you want to start over.
________________________________________
6. If Something Goes Wrong
If you encounter an issue and need support, please prepare:
Send these files:
•	The original playlist file (.m3u / .m3u8)
•	Corresponding repair_report_*.csv
•	selections_*.json (if exists)
Do NOT send:
•	Your entire music library
•	Large audio files
Include a short description:
•	What you expected
•	What happened instead
•	Your OS (Windows / macOS)
________________________________________
7. Author & Contact
Author: Ne
GitHub: https://github.com/Nechani
Issues & feedback: plfixne@gmail.com
Support: https://ko-fi.com/nechani
If this tool saves you time or rescues your playlists,
consider supporting development ☕
________________________________________
✔ Final Notes
Playlist Fixer is designed to be:
•	Safe (no destructive operations)
•	Transparent (CSV reports)
•	Recoverable (manual selections preserved)
It exists to protect one thing:
your playlists, built over years of listening.

