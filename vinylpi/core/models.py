from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass(slots=True)
class RecognizedTrack:
    """Normalized metadata returned by a Shazam recognition request."""

    artist: str
    title: str
    cover_image: Image.Image
    album: str | None = None
    cover_url: str | None = None
    genre: str | None = None
    shazam_track_id: str | None = None
    shazam_artist_id: str | None = None
    duration_ms: int | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return (self.artist.strip().casefold(), self.title.strip().casefold())
