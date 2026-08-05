#!/usr/bin/env python3
"""Recalculate listening time from stored play counts and track durations.

Existing Shazam durations are retained. Missing durations are resolved through
MusicBrainz, which is the only external fallback used by the runtime.
"""
from __future__ import annotations

import time

from vinylpi.core.statistics import _musicbrainz_track_length_ms
from vinylpi.core.stats_db import (
    get_stats_snapshot,
    replace_listening_total,
    update_song_duration,
    upsert_duration_cache,
)
from vinylpi.paths import get_active_db_path


def resolve_duration(entry: dict) -> tuple[int | None, str]:
    stored_ms = entry.get("duration_ms")
    stored_source = str(entry.get("duration_source") or "").strip()

    if stored_ms:
        try:
            duration_ms = int(stored_ms)
        except (TypeError, ValueError):
            duration_ms = 0
        if 30_000 <= duration_ms <= 30 * 60_000:
            return duration_ms, stored_source or "stored"

    try:
        duration_ms = _musicbrainz_track_length_ms(
            entry.get("artist") or "",
            entry.get("title") or "",
            entry.get("album"),
        )
    except Exception as exc:
        print(f"  MusicBrainz failed: {exc}")
        return None, "none"

    return (int(duration_ms), "musicbrainz") if duration_ms else (None, "none")


def main() -> None:
    songs = (get_stats_snapshot().get("songs") or {}).values()
    total_seconds = 0.0
    processed = 0
    skipped = 0

    print(f"Recalculating listening time for {len(songs)} songs...\n")

    for entry in songs:
        artist = str(entry.get("artist") or "").strip()
        title = str(entry.get("title") or "").strip()
        album = entry.get("album")
        count = int(entry.get("count") or 0)

        if not artist or not title or count <= 0:
            skipped += 1
            continue

        duration_ms, source = resolve_duration(entry)
        if not duration_ms:
            print(f"[skip] {artist} – {title}: no duration found")
            skipped += 1
            continue

        duration_minutes = duration_ms / 60000.0
        update_song_duration(
            artist,
            title,
            album,
            duration_ms,
            round(duration_minutes, 2),
            source,
        )
        upsert_duration_cache(
            artist,
            title,
            album,
            duration_ms,
            duration_minutes,
            source,
        )

        total_seconds += (duration_ms / 1000.0) * count
        processed += 1
        print(
            f"[{source}] {artist} – {title}: "
            f"{duration_minutes:.2f} min × {count}"
        )

        if source == "musicbrainz":
            time.sleep(1.05)

    replace_listening_total(
        total_seconds,
        recalculated_at=int(time.time()),
        recalculated_from_song_counts=True,
    )

    print("\nDone.")
    print(f"Processed: {processed}; skipped: {skipped}")
    print(f"New total: {total_seconds / 60.0:.2f} minutes")
    print(f"Database updated: {get_active_db_path()}")


if __name__ == "__main__":
    main()
