import json
import re
from dataclasses import dataclass

_SC_VERSION_RE = re.compile(r'window\.__sc_version\s*=\s*"([^"]+)"')


@dataclass
class Transcoding:
    url: str
    preset: str
    protocol: str  # aus format.protocol
    duration: str

    @property
    def is_progressive(self) -> bool:
        return self.protocol == "progressive"

    @property
    def is_hls(self) -> bool:
        return self.protocol == "hls"

    @property
    def is_adaptive(self) -> bool:
        # abr_* = adaptive Bitrate (Master-Playlist); als feste Datei nicht herunterladbar.
        return self.preset.startswith("abr")

    @property
    def file_extension(self) -> str:
        # progressive ist immer mp3; bei hls hängt es vom preset ab (mp3_* vs aac_*/abr_*).
        if self.is_progressive or self.preset.startswith("mp3"):
            return "mp3"
        return "m4a"

@dataclass
class SongEntry:
    sc_version: str
    client_id: str
    track_id: int
    title: str
    artist: str
    track_authorization: str
    transcodings: list[Transcoding]
    duration: int
    artwork_url: str | None

    @property
    def artwork_original_url(self) -> str | None:
        # SoundCloud liefert standardmäßig die -large (100x100) Variante; -original = volle Auflösung.
        if not self.artwork_url:
            return None
        return self.artwork_url.replace("-large", "-original")

    @staticmethod
    def extract_sc_version(raw_html: str) -> str:
        match = _SC_VERSION_RE.search(raw_html)
        if match is None:
            raise ValueError("window.__sc_version nicht im HTML gefunden")
        return match.group(1)

    @staticmethod
    def extract_hydration(raw_html: str) -> list:
        marker = raw_html.find("window.__sc_hydration")
        if marker == -1:
            raise ValueError("window.__sc_hydration nicht im HTML gefunden")
        start = raw_html.find("[", marker)
        if start == -1:
            raise ValueError("Konnte Beginn des __sc_hydration-Arrays nicht finden")
        # raw_decode parst genau einen JSON-Wert ab `start` und ignoriert den Rest,
        # daher kein Problem mit verschachtelten `];` (z.B. in features/media).
        hydration, _ = json.JSONDecoder().raw_decode(raw_html, start)
        return hydration

    @staticmethod
    def _find_hydratable(hydration: list, name: str) -> dict:
        for entry in hydration:
            if entry.get("hydratable") == name:
                return entry["data"]
        raise ValueError(f"Kein '{name}'-Hydratable in __sc_hydration gefunden")

    @classmethod
    def from_track_data(cls, track: dict, sc_version: str, client_id: str) -> "SongEntry":
        # Baut einen SongEntry aus einem einzelnen Track-JSON (sound-Hydratable ODER /tracks-Eintrag).
        transcodings = [
            Transcoding(
                url=t["url"],
                preset=t["preset"],
                protocol=t["format"]["protocol"],
                duration=t["duration"],
            )
            for t in track["media"]["transcodings"]
        ]
        return cls(
            sc_version=sc_version,
            client_id=client_id,
            track_id=track["id"],
            title=track["title"],
            artist=track["user"]["username"],
            track_authorization=track["track_authorization"],
            transcodings=transcodings,
            duration=track["duration"],
            artwork_url=track.get("artwork_url"),
        )

    @classmethod
    def from_html(cls, raw_html: str) -> "SongEntry":
        sc_version = cls.extract_sc_version(raw_html)
        hydration = cls.extract_hydration(raw_html)
        sound = cls._find_hydratable(hydration, "sound")
        client_id = cls._find_hydratable(hydration, "apiClient")["id"]
        return cls.from_track_data(sound, sc_version, client_id)

    @staticmethod
    def _format_duration(ms: int) -> str:
        seconds = ms // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"

    def print_summary(self) -> None:
        print(f"Titel:       {self.title}")
        print(f"Künstler:    {self.artist}")
        print(f"Track-ID:    {self.track_id}")
        print(f"Dauer:       {self._format_duration(self.duration)} ({self.duration} ms)")
        print(f"sc_version:  {self.sc_version}")
        print(f"client_id:   {self.client_id}")
        print(f"Cover:       {self.artwork_original_url}")
        print(f"Auth:        {self.track_authorization[:24]}…")
        print(f"Transcodings ({len(self.transcodings)}):")
        for t in self.transcodings:
            print(
                f"  - {t.preset:<10} {t.protocol:<12} "
                f"{self._format_duration(t.duration)}  {t.url}"
            )


@dataclass
class PlaylistEntry:
    sc_version: str
    client_id: str
    title: str
    track_ids: list[int]  # in Playlist-Reihenfolge

    @classmethod
    def from_html(cls, raw_html: str) -> "PlaylistEntry":
        sc_version = SongEntry.extract_sc_version(raw_html)
        hydration = SongEntry.extract_hydration(raw_html)
        playlist = SongEntry._find_hydratable(hydration, "playlist")
        client_id = SongEntry._find_hydratable(hydration, "apiClient")["id"]
        return cls(
            sc_version=sc_version,
            client_id=client_id,
            title=playlist["title"],
            track_ids=[t["id"] for t in playlist["tracks"]],
        )
