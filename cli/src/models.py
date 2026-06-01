import json
import re
from dataclasses import dataclass
from enum import StrEnum

_SC_VERSION_RE = re.compile(r'window\.__sc_version\s*=\s*"([^"]+)"')
_BITRATE_RE = re.compile(r"(\d+)k")


class Format(StrEnum):
    """Filter, welche Transcoding(s) eines Songs geladen werden."""

    ALL = "all"    # alle nicht-adaptiven Versionen
    BEST = "best"  # die qualitativ beste insgesamt
    MP3 = "mp3"    # beste mp3 (sonst Fallback aufs Beste)
    M4A = "m4a"    # beste m4a (sonst Fallback aufs Beste)


# --- Parse-Helfer (geteilt von Song- und Playlist-Parsing) ---

def extract_sc_version(raw_html: str) -> str:
    match = _SC_VERSION_RE.search(raw_html)
    if match is None:
        raise ValueError("window.__sc_version nicht im HTML gefunden")
    return match.group(1)


def extract_hydration(raw_html: str) -> list[dict]:
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


def find_hydratable(hydration: list[dict], name: str) -> dict:
    for entry in hydration:
        if entry.get("hydratable") == name:
            return entry["data"]
    raise ValueError(f"Kein '{name}'-Hydratable in __sc_hydration gefunden")


@dataclass
class Transcoding:
    url: str
    preset: str
    protocol: str  # aus format.protocol
    duration: int  # Millisekunden

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

    @property
    def bitrate(self) -> int:
        # Aus dem preset abgeleitet: aac_160k→160, aac_96k→96; mp3_* hat keine kbps im preset → 128.
        match = _BITRATE_RE.search(self.preset)
        if match:
            return int(match.group(1))
        return 128 if self.preset.startswith("mp3") else 0


@dataclass
class Song:
    """Die downloadbare Einheit: ein Track mit seinen Transcodings und Metadaten."""

    track_id: int
    title: str
    artist: str
    duration: int
    artwork_url: str | None
    track_authorization: str
    transcodings: list[Transcoding]

    @property
    def artwork_original_url(self) -> str | None:
        # SoundCloud liefert standardmäßig die -large (100x100) Variante; -original = volle Auflösung.
        if not self.artwork_url:
            return None
        return self.artwork_url.replace("-large", "-original")

    def select_transcodings(self, fmt: Format) -> list[Transcoding]:
        # Adaptive sind keine feste Datei → nie auswählbar.
        usable = [t for t in self.transcodings if not t.is_adaptive]
        if not usable:
            return []
        if fmt is Format.ALL:
            return usable
        if fmt is Format.BEST:
            return [max(usable, key=lambda t: t.bitrate)]
        # mp3/m4a: bestes des gewünschten Containers, sonst Fallback aufs Beste insgesamt.
        same = [t for t in usable if t.file_extension == fmt.value]
        pool = same or usable
        return [max(pool, key=lambda t: t.bitrate)]

    @classmethod
    def from_track_data(cls, track: dict) -> "Song":
        # Baut einen Song aus einem Track-JSON (sound-Hydratable ODER /tracks-Eintrag).
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
            track_id=track["id"],
            title=track["title"],
            artist=track["user"]["username"],
            duration=track["duration"],
            artwork_url=track.get("artwork_url"),
            track_authorization=track["track_authorization"],
            transcodings=transcodings,
        )


@dataclass
class SongEntry:
    """Geparste Song-Seite: App-/Seiten-Kontext + der Song."""

    sc_version: str
    client_id: str
    song: Song

    @classmethod
    def from_html(cls, raw_html: str) -> "SongEntry":
        sc_version = extract_sc_version(raw_html)
        hydration = extract_hydration(raw_html)
        client_id = find_hydratable(hydration, "apiClient")["id"]
        sound = find_hydratable(hydration, "sound")
        return cls(sc_version=sc_version, client_id=client_id, song=Song.from_track_data(sound))


@dataclass
class PlaylistEntry:
    """Geparste Playlist-Seite: App-/Seiten-Kontext + die (aufgelösten) Songs."""

    sc_version: str
    client_id: str
    title: str
    songs: list[Song]
