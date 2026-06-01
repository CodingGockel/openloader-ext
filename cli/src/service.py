import re
import subprocess
from pathlib import Path

import requests
from mutagen.id3 import ID3
from mutagen.id3._frames import APIC, TIT2, TPE1, TRCK
from mutagen.id3._util import ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

from models import (
    Format,
    PlaylistEntry,
    Song,
    SongEntry,
    Transcoding,
    extract_hydration,
    extract_sc_version,
    find_hydratable,
)

_USER_AGENT = "Mozilla/5.0"
_TRACKS_API = "https://api-v2.soundcloud.com/tracks"
_APP_LOCALE = "en"


class SoundCloudService:
    """Bündelt die zwei Download-Pipelines (Song / Playlist) und ihre geteilten Helfer.

    Zustandslos: jeder Request ist ein eigener frischer requests.get(...).
    """

    # --- Öffentliche Pipelines ---

    def download_song(self, url: str, out_dir: Path, fmt: Format) -> Path:
        entry: SongEntry = self._fetch_song(url)
        song: Song = entry.song
        print(f"{song.artist} - {song.title}")
        self._save_track(song, entry.client_id, out_dir, fmt)
        return out_dir

    def download_playlist(self, url: str, out_dir: Path, fmt: Format) -> Path:
        entry: PlaylistEntry = self._fetch_playlist(url)
        dest: Path = out_dir / self._sanitize_filename(entry.title)
        total: int = len(entry.songs)
        print(f"Playlist: {entry.title} ({total} Tracks)")
        for n, song in enumerate(entry.songs, start=1):
            print(f"\n=== [{n}/{total}] {song.artist} - {song.title} ===")
            try:
                self._save_track(song, entry.client_id, dest, fmt, n, total)
            except Exception as e:  # ein kaputter Track stoppt nicht die ganze Playlist
                print(f"  ⚠ Track fehlgeschlagen: {e}")
        return dest

    # --- Geteilter Fetch-Kern ---

    def _get_html(self, url: str) -> str:
        # SoundCloud liefert die inline __sc_hydration nur mit realistischem Browser-UA.
        response = requests.get(url, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        # SoundCloud liefert UTF-8, aber ohne charset-Header rät requests Latin-1 → Umlaute kaputt.
        response.encoding = "utf-8"
        return response.text

    def _fetch_page(self, url: str) -> tuple[str, str, list[dict]]:
        # Gemeinsamer Kern beider Fetches: (sc_version, client_id, hydration).
        html: str = self._get_html(url)
        sc_version: str = extract_sc_version(html)
        hydration: list = extract_hydration(html)
        client_id: str = find_hydratable(hydration, "apiClient")["id"]
        return sc_version, client_id, hydration

    def _fetch_song(self, url: str) -> SongEntry:
        sc_version, client_id, hydration = self._fetch_page(url)
        sound = find_hydratable(hydration, "sound")
        return SongEntry(sc_version=sc_version, client_id=client_id, song=Song.from_track_data(sound))

    def _fetch_playlist(self, url: str) -> PlaylistEntry:
        sc_version, client_id, hydration = self._fetch_page(url)
        playlist = find_hydratable(hydration, "playlist")
        track_ids = [t["id"] for t in playlist["tracks"]]
        tracks = self._fetch_tracks(track_ids, client_id, sc_version)
        # /tracks-Antwort ist unsortiert → in Playlist-Reihenfolge bringen.
        by_id = {t["id"]: t for t in tracks}
        songs = [Song.from_track_data(by_id[tid]) for tid in track_ids if tid in by_id]
        return PlaylistEntry(
            sc_version=sc_version, client_id=client_id, title=playlist["title"], songs=songs
        )

    def _fetch_tracks(
        self, track_ids: list[int], client_id: str, app_version: str
    ) -> list[dict]:
        # Vollständige Track-Daten über die /tracks-API holen (in Blöcken zu max. 50 IDs).
        tracks: list[dict] = []
        for i in range(0, len(track_ids), 50):
            chunk = track_ids[i:i + 50]
            params = {
                "ids": ",".join(str(tid) for tid in chunk),
                "client_id": client_id,
                "app_version": app_version,
                "app_locale": _APP_LOCALE,
            }
            response = requests.get(_TRACKS_API, params=params, headers={"User-Agent": _USER_AGENT})
            response.raise_for_status()
            tracks.extend(response.json())
        return tracks

    # --- Geteilter Download eines einzelnen Songs ---

    def _save_track(
        self,
        song: Song,
        client_id: str,
        out_dir: Path,
        fmt: Format,
        track_number: int | None = None,
        track_total: int | None = None,
    ) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        selected = song.select_transcodings(fmt)
        if not selected:
            print("  ⚠ Keine ladbare Transcoding gefunden.")
            return out_dir
        # Cover einmal pro Song laden und in jede Datei einbetten.
        try:
            cover = self._fetch_cover(song)
        except Exception as e:
            print(f"  ⚠ Cover konnte nicht geladen werden: {e}")
            cover = None
        # Bei mehreren Dateien (Format.ALL) den Dateinamen eindeutig machen.
        disambiguate = len(selected) > 1
        for transcoding in selected:
            label = f"{transcoding.preset} ({transcoding.protocol})"
            print(f"Lade {label} …")
            try:
                dest = self._download_one(
                    transcoding, song, client_id, out_dir, cover,
                    disambiguate, track_number, track_total,
                )
            except Exception as e:  # ein Fehlschlag darf den Rest nicht abbrechen
                print(f"  ⚠ {label} fehlgeschlagen: {e}")
                continue
            print(f"  → {dest}")
        return out_dir

    def _download_one(
        self,
        transcoding: Transcoding,
        song: Song,
        client_id: str,
        out_dir: Path,
        cover: tuple[bytes, str] | None,
        disambiguate: bool,
        track_number: int | None,
        track_total: int | None,
    ) -> Path:
        media_url = self._resolve_media_url(transcoding, client_id, song.track_authorization)
        stem = self._sanitize_filename(f"{song.artist} - {song.title}")
        if disambiguate:
            stem += f"_{transcoding.preset}_{transcoding.protocol}"
        dest_path = out_dir / f"{stem}.{transcoding.file_extension}"
        if transcoding.is_progressive:
            self._download_progressive(media_url, dest_path)
        else:
            self._download_hls(media_url, dest_path)
        self._embed_metadata(dest_path, song, cover, track_number, track_total)
        return dest_path

    def _resolve_media_url(
        self, transcoding: Transcoding, client_id: str, track_authorization: str
    ) -> str:
        # Die transcoding.url ist nur ein API-Endpoint; aufgelöst liefert er die echte CDN-URL.
        params = {"client_id": client_id, "track_authorization": track_authorization}
        response = requests.get(
            transcoding.url, params=params, headers={"User-Agent": _USER_AGENT}
        )
        response.raise_for_status()
        return response.json()["url"]

    def _download_progressive(self, media_url: str, dest_path: Path) -> None:
        # Progressive liefert eine fertige Datei: einfach streamen und schreiben.
        with requests.get(media_url, stream=True, headers={"User-Agent": _USER_AGENT}) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

    def _download_hls(self, media_url: str, dest_path: Path) -> None:
        # ffmpeg lädt die m3u8-Segmente und muxt sie verlustfrei (-c copy) in eine Datei.
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-nostats", "-y",
             "-i", media_url, "-c", "copy", str(dest_path)],
            check=True,
        )

    def _fetch_cover(self, song: Song) -> tuple[bytes, str] | None:
        # Cover in Originalauflösung laden; gibt (Bytes, mime) zurück oder None.
        url = song.artwork_original_url
        if not url:
            return None
        response = requests.get(url, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        data = response.content
        # mime aus den Magic-Bytes ableiten (Original kann jpg oder png sein).
        mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        return data, mime

    def _embed_metadata(
        self,
        audio_path: Path,
        song: Song,
        cover: tuple[bytes, str] | None,
        track_number: int | None = None,
        track_total: int | None = None,
    ) -> None:
        # Titel/Artist (+ optional Cover + Track-Nr) je nach Containerformat einbetten.
        if audio_path.suffix == ".mp3":  # ID3
            try:
                tags = ID3(audio_path)
            except ID3NoHeaderError:
                tags = ID3()  # direkter Download hat noch keinen ID3-Tag
            # UTF-16 (encoding=1) ist in ID3v2.3 gültig und umlautsicher (UTF-8 wäre es nicht).
            tags.setall("TIT2", [TIT2(encoding=1, text=song.title)])
            tags.setall("TPE1", [TPE1(encoding=1, text=song.artist)])
            if track_number is not None:
                trck = f"{track_number}/{track_total}" if track_total else str(track_number)
                tags.setall("TRCK", [TRCK(encoding=0, text=trck)])
            if cover is not None:
                tags.delall("APIC")
                tags.add(APIC(encoding=0, mime=cover[1], type=3, desc="Cover", data=cover[0]))
            # Als ID3v2.3 speichern: Windows Media Player/Explorer liest v2.4 nicht zuverlässig.
            tags.save(audio_path, v2_version=3)
        else:  # .m4a (MP4)
            mp4 = MP4(audio_path)
            mp4["\xa9nam"] = [song.title]
            mp4["\xa9ART"] = [song.artist]
            if track_number is not None:
                mp4["trkn"] = [(track_number, track_total or 0)]
            if cover is not None:
                fmt = MP4Cover.FORMAT_PNG if cover[1] == "image/png" else MP4Cover.FORMAT_JPEG
                mp4["covr"] = [MP4Cover(cover[0], imageformat=fmt)]
            mp4.save()

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        # In Datei-/Ordnernamen unzulässige Zeichen durch _ ersetzen.
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "track"
