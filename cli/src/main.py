from pathlib import Path
from typing import Annotated

import typer

from models import Format
from service import SoundCloudService

app = typer.Typer(
    add_completion=False,
    help="Lädt SoundCloud-Tracks und -Playlists herunter.",
)


@app.command()
def download(
    url: Annotated[str, typer.Argument(help="SoundCloud-URL (Track oder Playlist)")],
    dir: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Zielverzeichnis für die Downloads."),
    ] = Path("downloads"),
    format: Annotated[
        Format,
        typer.Option("--format", "-f", help="Welche Version(en) laden."),
    ] = Format.MP3,
) -> None:
    """Lädt einen Track oder eine ganze Playlist."""
    service = SoundCloudService()
    if "/sets/" in url:  # Playlist-URLs enthalten /sets/
        out_dir = service.download_playlist(url, dir, format)
        print(f"\nPlaylist gespeichert in: {out_dir}")
    else:
        out_dir = service.download_song(url, dir, format)
        print(f"\nGespeichert in: {out_dir}")


if __name__ == "__main__":
    app()
