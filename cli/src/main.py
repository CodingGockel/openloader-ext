from pathlib import Path
from typing import Annotated

import typer

from client import SoundCloudClient
from downloader import Downloader

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
) -> None:
    """Lädt einen Track oder eine ganze Playlist (alle verfügbaren Versionen)."""
    client = SoundCloudClient()
    downloader = Downloader(client)
    base_dir = str(dir)
    if "/sets/" in url:  # Playlist-URLs enthalten /sets/
        out_dir = downloader.download_playlist(url, base_dir=base_dir)
        print(f"\nPlaylist gespeichert in: {out_dir}")
    else:
        entry = client.get_song_entry(url)
        entry.print_summary()
        out_dir = downloader.download_all_versions(entry, base_dir=base_dir)
        print(f"Alle Versionen gespeichert in: {out_dir}")


if __name__ == "__main__":
    app()
