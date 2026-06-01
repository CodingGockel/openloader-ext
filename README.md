# openloader

CLI-Tool zum Herunterladen von SoundCloud-Tracks und -Playlists. Es liest die Track-Daten aus
dem `window.__sc_hydration`-JSON der Seite, löst die Stream-URLs auf, lädt die gewünschte
Version herunter und bettet Metadaten + Cover-Art ein.

> Status: in aktiver Entwicklung. Standardmäßig wird **eine** Datei pro Song in der gewählten
> Qualität geladen (siehe `--format`). Geplant als Nächstes: paralleler Download und
> inkrementeller Playlist-Sync.

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
python main.py <url> [--dir/-d ZIELORDNER] [--format/-f all|best|mp3|m4a] [--worker/-w N] [--retries N]
```

- `<url>` — eine SoundCloud-**Track**- oder **Playlist**-URL. Playlists werden automatisch
  erkannt (die URL enthält `/sets/`).
- `--dir` / `-d` — Zielverzeichnis für die Downloads (Default: `downloads`). Der Ordner wird
  bei Bedarf angelegt.
- `--format` / `-f` — welche Version(en) geladen werden (Default: `mp3`):
  - `mp3` — beste verfügbare MP3 (sonst Fallback auf die beste Version überhaupt).
  - `m4a` — beste verfügbare AAC/M4A (sonst Fallback auf die beste Version überhaupt).
  - `best` — die qualitativ beste Version insgesamt (meist `aac_160k`).
  - `all` — alle nicht-adaptiven Versionen (mehrere Dateien pro Song).
- `--worker` / `-w` — Anzahl paralleler Downloads bei Playlists (Default: `4`, min. `1`). Da
  Downloads netzwerk-gebunden sind, gibt es schon bei wenigen Workern einen großen Speedup; zu
  hohe Werte riskieren Drosselung (HTTP 429) durch SoundCloud.
- `--retries` — Versuche pro Datei bei Fehlern (Default: `3`, min. `1`; `1` = kein Retry).
  Transiente Fehler (Timeouts, 5xx) werden mit exponentiellem Backoff wiederholt; deterministische
  404/403 werden nicht wiederholt.

Hilfe anzeigen:

```bash
python main.py --help
```

### Beispiele

Einzelnen Track als MP3 in den Standardordner `downloads/` laden:

```bash
python main.py https://soundcloud.com/artist/track-name
```

Eine Playlist in bester M4A-Qualität in einen eigenen Ordner laden:

```bash
python main.py https://soundcloud.com/artist/sets/playlist-name --dir ~/Music/openloader --format m4a
```

## Wie es funktioniert

- **Track:** Die Seite wird geladen, der Song (Titel/Artist/Transcodings) wird aus
  `window.__sc_hydration` extrahiert; anschließend wird die per `--format` gewählte Version geladen.
- **Playlist:** SoundCloud hydriert im HTML nur die ersten ~3 Tracks vollständig; die übrigen
  werden per `/tracks`-API anhand ihrer IDs nachgeladen und in Playlist-Reihenfolge gebracht.
  Danach durchläuft jeder Track denselben Download-Ablauf wie ein Einzeltrack.
- **Formate pro Track:**
  - `progressive` → fertige MP3, direkt heruntergeladen.
  - `hls` → m3u8-Playlist, per `ffmpeg -c copy` zu `.m4a` (AAC) bzw. `.mp3` gemuxt.
  - `abr_*` (adaptive Bitrate) → wird immer übersprungen (keine feste Datei).
- **Metadaten:** Titel, Artist, ggf. Track-Nummer und Cover werden eingebettet — MP3 als
  ID3v2.3 (umlautsicher via UTF-16), M4A als MP4-Atome.

Ein fehlgeschlagener Download bricht weder die restlichen Dateien noch die übrige Playlist ab.
Schlägt bei `mp3`/`m4a`/`best` eine Transcoding fehl (z. B. 404 beim Auflösen der Stream-URL — manche
Varianten eines Tracks sind nicht abrufbar), wird automatisch die nächstbeste Transcoding probiert,
sodass trotzdem eine Datei entsteht.

## Ausgabestruktur

Eine Datei pro Song (Standard), flach im Zielordner:

```
<ZIELORDNER>/
├── <Artist> - <Title>.mp3                      # einzelner Track
└── <Playlist-Titel>/                           # nur bei Playlists
    ├── <Artist> - <Title>.mp3
    └── …
```

Mit `--format all` entstehen pro Song mehrere Dateien mit Versions-Suffix
(`<Artist> - <Title>_<preset>_<protocol>.<ext>`) im selben Ordner.

## Projektstruktur (`cli/src/`)

| Datei | Aufgabe |
|-------|---------|
| `models.py` | Datenmodelle (`Transcoding`, `Song`, `SongEntry`, `PlaylistEntry`), `Format`-Filter, HTML-/JSON-Parsing. |
| `service.py` | `SoundCloudService` — die zwei Pipelines (`download_song`, `download_playlist`) plus geteilter Fetch/Download/Tagging. |
| `main.py` | Typer-CLI als Einstiegspunkt. |
