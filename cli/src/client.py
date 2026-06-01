import requests

from models import PlaylistEntry, SongEntry, Transcoding

_USER_AGENT = "Mozilla/5.0"
_TRACKS_API = "https://api-v2.soundcloud.com/tracks"
_APP_LOCALE = "en"


class SoundCloudClient:
    """Reine Netzwerk-/Parsing-Schicht: holt HTML/JSON von SoundCloud und löst URLs auf."""

    def get_song_entry(self, url: str) -> SongEntry:
        # SoundCloud liefert die inline __sc_hydration nur mit realistischem Browser-UA.
        headers = {"User-Agent": _USER_AGENT}
        response: requests.Response = requests.get(url, headers=headers)
        response.raise_for_status()
        # SoundCloud liefert UTF-8, aber ohne charset-Header rät requests Latin-1 → Umlaute kaputt.
        response.encoding = "utf-8"
        return SongEntry.from_html(response.text)

    def get_playlist_entry(self, url: str) -> PlaylistEntry:
        headers = {"User-Agent": _USER_AGENT}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = "utf-8"
        return PlaylistEntry.from_html(response.text)

    def resolve_media_url(
        self, transcoding: Transcoding, client_id: str, track_authorization: str
    ) -> str:
        # Die transcoding.url ist nur ein API-Endpoint; aufgelöst liefert er die echte CDN-URL.
        headers = {"User-Agent": _USER_AGENT}
        params = {"client_id": client_id, "track_authorization": track_authorization}
        response = requests.get(transcoding.url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()["url"]

    def fetch_tracks(
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
