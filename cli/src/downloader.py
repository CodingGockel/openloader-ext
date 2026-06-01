import re
import subprocess
from pathlib import Path

import requests
from mutagen.id3 import ID3, APIC, ID3NoHeaderError, TIT2, TPE1, TRCK
from mutagen.mp4 import MP4, MP4Cover

from client import SoundCloudClient, _USER_AGENT
from models import SongEntry, Transcoding


class Downloader:
    """Lädt Transcodings/Cover herunter und bettet Metadaten in die Dateien ein."""

    def __init__(self, client: SoundCloudClient):
        self.client = client

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        # In Datei-/Ordnernamen unzulässige Zeichen durch _ ersetzen.
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "track"

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

    def _download_cover(self, entry: SongEntry) -> tuple[bytes, str] | None:
        # Cover in Originalauflösung laden; gibt (Bytes, mime) zurück oder None.
        url = entry.artwork_original_url
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
        entry: SongEntry,
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
            tags.setall("TIT2", [TIT2(encoding=1, text=entry.title)])
            tags.setall("TPE1", [TPE1(encoding=1, text=entry.artist)])
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
            mp4["\xa9nam"] = [entry.title]
            mp4["\xa9ART"] = [entry.artist]
            if track_number is not None:
                mp4["trkn"] = [(track_number, track_total or 0)]
            if cover is not None:
                fmt = MP4Cover.FORMAT_PNG if cover[1] == "image/png" else MP4Cover.FORMAT_JPEG
                mp4["covr"] = [MP4Cover(cover[0], imageformat=fmt)]
            mp4.save()

    def download_transcoding(
        self,
        transcoding: Transcoding,
        entry: SongEntry,
        out_dir: Path,
        cover: tuple[bytes, str] | None,
        track_number: int | None = None,
        track_total: int | None = None,
    ) -> Path:
        media_url = self.client.resolve_media_url(
            transcoding, entry.client_id, entry.track_authorization
        )
        filename = (
            f"{self._sanitize_filename(entry.title)}"
            f"_{transcoding.preset}_{transcoding.protocol}.{transcoding.file_extension}"
        )
        dest_path = out_dir / filename
        if transcoding.is_progressive:
            self._download_progressive(media_url, dest_path)
        else:
            self._download_hls(media_url, dest_path)
        self._embed_metadata(dest_path, entry, cover, track_number, track_total)
        return dest_path

    def download_all_versions(
        self,
        entry: SongEntry,
        base_dir: str = "downloads",
        track_number: int | None = None,
        track_total: int | None = None,
    ) -> Path:
        # Ordner trägt den Songtitel und enthält alle transcodierten Versionen.
        out_dir = Path(base_dir) / self._sanitize_filename(entry.title)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Cover einmal laden und in jede Datei einbetten.
        try:
            cover = self._download_cover(entry)
        except Exception as e:
            print(f"  ⚠ Cover konnte nicht geladen werden: {e}")
            cover = None
        downloaded = 0
        skipped = 0
        for transcoding in entry.transcodings:
            label = f"{transcoding.preset} ({transcoding.protocol})"
            # Adaptive (abr_*) Transcodings sind keine feste Datei → überspringen.
            if transcoding.is_adaptive:
                print(f"Überspringe {label}: adaptive Bitrate, nicht als Datei ladbar.")
                skipped += 1
                continue
            print(f"Lade {label} …")
            try:
                dest = self.download_transcoding(
                    transcoding, entry, out_dir, cover, track_number, track_total
                )
            except Exception as e:  # ein Fehlschlag darf den Rest nicht abbrechen
                print(f"  ⚠ {label} fehlgeschlagen: {e}")
                skipped += 1
                continue
            print(f"  → {dest}")
            downloaded += 1
        print(f"\n{downloaded} geladen, {skipped} übersprungen/fehlgeschlagen.")
        return out_dir

    def download_playlist(self, url: str, base_dir: str = "downloads") -> Path:
        playlist = self.client.get_playlist_entry(url)
        print(f"Playlist: {playlist.title} ({len(playlist.track_ids)} Tracks)")
        tracks = self.client.fetch_tracks(
            playlist.track_ids, playlist.client_id, playlist.sc_version
        )
        # /tracks-Antwort ist unsortiert → in Playlist-Reihenfolge bringen.
        by_id = {t["id"]: t for t in tracks}
        ordered = [by_id[tid] for tid in playlist.track_ids if tid in by_id]
        playlist_dir = f"{base_dir}/{self._sanitize_filename(playlist.title)}"
        total = len(ordered)
        for n, track in enumerate(ordered, start=1):
            entry = SongEntry.from_track_data(track, playlist.sc_version, playlist.client_id)
            print(f"\n=== [{n}/{total}] {entry.artist} - {entry.title} ===")
            try:
                self.download_all_versions(
                    entry, base_dir=playlist_dir, track_number=n, track_total=total
                )
            except Exception as e:  # ein kaputter Track stoppt nicht die ganze Playlist
                print(f"  ⚠ Track fehlgeschlagen: {e}")
        return Path(playlist_dir)
