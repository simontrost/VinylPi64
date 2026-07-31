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
    discogs_release_id: int | None = None
    discogs_position: str | None = None
    discogs_side: str | None = None
    discogs_track_index: int | None = None
    discogs_track_count: int | None = None
    discogs_side_track_number: int | None = None
    discogs_side_track_count: int | None = None
    discogs_match_source: str | None = None
    discogs_confidence: float | None = None
    discogs_cover_url: str | None = None
    discogs_year: int | None = None
    discogs_label: str | None = None
    discogs_catalog_number: str | None = None
    discogs_expected_next_title: str | None = None
    discogs_expected_next_artist: str | None = None
    discogs_expected_next_position: str | None = None
    discogs_expected_next_side: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return (self.artist.strip().casefold(), self.title.strip().casefold())
