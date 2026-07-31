from vinylpi.core.stats_db import get_ranked_stats


def get_top_stats(limit: int = 10) -> dict:
    try:
        return get_ranked_stats(limit=limit)
    except Exception as exc:
        print(f"Could not load stats from SQLite: {exc}")
        return {
            "top_songs": [],
            "top_artists": [],
            "top_albums": [],
            "top_album_covers": [],
            "top_genres": [],
            "radar_genres": [],
            "total_minutes_listened": 0,
            "metadata_coverage": {
                "songs_total": 0,
                "songs_with_genre": 0,
                "songs_with_shazam_id": 0,
            },
        }
