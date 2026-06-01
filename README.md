# openloader

CLI-Tool zum Herunterladen von SoundCloud-Tracks und -Playlists. Es liest die Track-Daten aus
dem `window.__sc_hydration`-JSON der Seite, löst die Stream-URLs auf, lädt jede verfügbare
Transcoding herunter und bettet Metadaten + Cover-Art ein.

> Status: Prototyp im Umbau. Aktuell lädt das Tool pro Track **alle** verfügbaren Versionen.
> Geplant sind als Nächstes: Best-Quality-Auswahl (eine Datei pro Song), paralleler Download
> und inkrementeller Playlist-Sync.

## Voraussetzungen

- **Python 3.12**
- **`ffmpeg` als System-Binary auf dem PATH** — wird zum verlustfreien Muxen der HLS-Streams
  benötigt (`ffmpeg -c copy`). Das `ffmpeg`-Pip-Paket ist **nicht** gemeint.

## Installation

```bash
python -m venv .openloader-venv
source .openloader-venv/bin/activate      # Windows: .openloader-venv\Scripts\activate
pip install -r requirements.txt
```

Prüfen, ob ffmpeg verfügbar ist:

```bash
ffmpeg -version
```

## Verwendung

```bash
cd cli/src
python main.py <url> [--dir/-d ZIELORDNER]
```

- `<url>` — eine SoundCloud-**Track**- oder **Playlist**-URL. Playlists werden automatisch
  erkannt (die URL enthält `/sets/`).
- `--dir` / `-d` — Zielverzeichnis für die Downloads (Default: `downloads`). Der Ordner wird
  bei Bedarf angelegt.

Hilfe anzeigen:

```bash
python main.py --help
```

### Beispiele

Einzelnen Track in den Standardordner `downloads/` laden:

```bash
python main.py https://soundcloud.com/artist/track-name
```

Eine Playlist in einen eigenen Ordner laden:

```bash
python main.py https://soundcloud.com/artist/sets/playlist-name --dir ~/Music/openloader
```

## Wie es funktioniert

- **Track:** Die Seite wird geladen, der Titel/Artist/die Transcodings werden aus
  `window.__sc_hydration` extrahiert und eine kurze Übersicht ausgegeben. Anschließend wird jede
  ladbare Version heruntergeladen.
- **Playlist:** SoundCloud hydriert im HTML nur die ersten ~3 Tracks vollständig; die übrigen
  werden per `/tracks`-API anhand ihrer IDs nachgeladen und in Playlist-Reihenfolge gebracht.
  Danach wird jeder Track wie oben geladen.
- **Formate pro Track:**
  - `progressive` → fertige MP3, direkt heruntergeladen.
  - `hls` → m3u8-Playlist, per `ffmpeg -c copy` zu `.m4a` (AAC) bzw. `.mp3` gemuxt.
  - `abr_*` (adaptive Bitrate) → wird übersprungen (keine feste Datei).
- **Metadaten:** Titel, Artist, ggf. Track-Nummer und Cover werden eingebettet — MP3 als
  ID3v2.3 (umlautsicher via UTF-16), M4A als MP4-Atome.

Ein fehlgeschlagener Download bricht weder die restlichen Versionen noch die übrige Playlist ab.

## Ausgabestruktur

```
<ZIELORDNER>/
└── <Playlist-Titel>/                 # nur bei Playlists
    └── <Track-Titel>/
        ├── <Track-Titel>_aac_160k_hls.m4a
        ├── <Track-Titel>_mp3_1_0_progressive.mp3
        └── …                          # je eine Datei pro Version
```

Bei einem einzelnen Track entfällt der Playlist-Unterordner.

## Projektstruktur (`cli/src/`)

| Datei | Aufgabe |
|-------|---------|
| `models.py` | Datenmodelle: `Transcoding`, `SongEntry`, `PlaylistEntry` (inkl. HTML-/JSON-Parsing). |
| `client.py` | `SoundCloudClient` — Netzwerk-/Parsing-Schicht: HTML laden, Stream-URLs auflösen, `/tracks`-API. |
| `downloader.py` | `Downloader` — Download (progressive/HLS), Cover, Metadaten-Tagging, Playlist-Orchestrierung. |
| `main.py` | Typer-CLI als Einstiegspunkt. |
