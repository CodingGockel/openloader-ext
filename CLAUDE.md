# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview
CLI tool that downloads SoundCloud tracks and playlists. It extracts track data from the
page's inline `window.__sc_hydration` JSON, resolves the stream URLs, downloads every available
transcoding, and embeds metadata + cover art.

## Setup & Run
- Virtualenv: `.openloader-venv` (Python 3.12). Install deps: `pip install -r requirements.txt`.
- Run: `cd cli/src && python main.py` — prompts for a URL. Works for a single track URL or a
  playlist URL (contains `/sets/`).
- **System `ffmpeg` binary required on PATH** for HLS muxing (used via `subprocess`). The
  `ffmpeg` entry in requirements.txt is a pip package and is NOT what the code uses.

## Workflow rules
- **Run scripts only when explicitly asked.** `main.py` makes real network requests and writes
  files to `cli/src/downloads/`. Don't run it to "verify" unless the user asks in the moment.
- **Never perform git operations** (no commit/branch/push). The user handles all git.

## Domain gotchas (SoundCloud specifics)
- Track/playlist data lives in `window.__sc_hydration` (a JSON array) in the page HTML.
  Relevant hydratables: `sound` (single track), `playlist`, `apiClient`.
  `client_id = apiClient.data.id`, `app_version = window.__sc_version`.
- Set `response.encoding = "utf-8"` before parsing the HTML, otherwise umlauts break (requests
  guesses Latin-1).
- A `transcoding.url` is only an API endpoint — resolve it with `client_id` +
  `track_authorization` to get the real CDN URL.
- Per transcoding: `progressive` = a ready MP3 (download directly via requests); `hls` = an
  m3u8 → `ffmpeg -c copy` (AAC→`.m4a`, mp3→`.mp3`). Skip `abr_sq` (adaptive; its resolve 404s).
- Playlists: the hydration only fully hydrates the first ~3 tracks; the rest are stubs (`id`
  only). Fetch full data for all via
  `https://api-v2.soundcloud.com/tracks?ids=<comma-sep>&client_id=…&app_version=…&app_locale=en`.
  The response is unordered → reorder by the playlist's `track_ids`.
- Tagging uses `mutagen`. Save mp3 as **ID3v2.3** (`tags.save(path, v2_version=3)`) with UTF-16
  text frames — Windows Media Player/Explorer don't read ID3v2.4 reliably. m4a uses MP4 atoms
  (`©nam`, `©ART`, `trkn`, `covr`).
- Native original-file download (the only path to lossless/WAV) is available only when a track
  has `downloadable: true` AND no `purchase_url`. Rare — most "FREE DOWNLOAD" tracks route
  through external gates (e.g. Hypeddit) and are not downloadable via the API.

## Reference
`docs/` contains captured real example responses for offline reference of the data shapes:
`SongEntryExample.html`, `PlaylistEntryExample.html`, `tracksEndpointResponseExample.json`.
