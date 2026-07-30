#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from vinylpi.core.database import get_connection, init_db
from vinylpi.core.stats_db import get_stats_snapshot, import_stats_json
from vinylpi.paths import DB_PATH, STATS_PATH


def print_summary() -> None:
    init_db()
    with get_connection() as conn:
        counts = {
            "songs": conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0],
            "artists": conn.execute("SELECT COUNT(*) FROM artist_totals").fetchone()[0],
            "album sessions": conn.execute("SELECT COUNT(*) FROM album_sessions").fetchone()[0],
            "duration cache": conn.execute("SELECT COUNT(*) FROM duration_cache").fetchone()[0],
            "album covers": conn.execute("SELECT COUNT(*) FROM album_covers").fetchone()[0],
            "tag cache": conn.execute("SELECT COUNT(*) FROM tag_cache").fetchone()[0],
        }
        total_seconds = conn.execute(
            "SELECT total_seconds FROM listening_totals WHERE id = 1"
        ).fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

    print(f"Database: {DB_PATH}")
    for label, value in counts.items():
        print(f"  {label:16}: {value}")
    print(f"  total minutes   : {round(float(total_seconds or 0) / 60.0, 2)}")
    print(f"  integrity check : {integrity}")


def export_json(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(get_stats_snapshot(), indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Exported SQLite statistics to: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import legacy VinylPi stats.json data into SQLite."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=STATS_PATH,
        help=f"Legacy JSON source (default: {STATS_PATH})",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing statistics in the database before importing.",
    )
    parser.add_argument(
        "--export",
        type=Path,
        help="Export the current SQLite statistics to a JSON file instead of importing.",
    )
    args = parser.parse_args()

    if args.export:
        export_json(args.export)
        return

    if not args.source.exists():
        raise SystemExit(f"Source file not found: {args.source}")

    summary = import_stats_json(
        args.source,
        replace=args.replace,
        keep_raw_backup=True,
    )
    print(
        f"Imported {summary['songs']} songs and {summary['artists']} artists "
        f"from {args.source}."
    )
    print_summary()


if __name__ == "__main__":
    main()
