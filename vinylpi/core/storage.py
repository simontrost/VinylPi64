from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

from vinylpi.core.database import database_has_statistics, init_db
from vinylpi.core.stats_db import (
    get_current_status,
    get_meta,
    import_stats_json,
    set_meta,
    write_current_status,
)
from vinylpi.paths import DATA_DIR, STATS_PATH, STATUS_PATH

_lock = threading.Lock()
_initialized = False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_legacy_file(path: Path) -> None:
    """Move an imported legacy JSON file out of the active data directory."""
    legacy_dir = DATA_DIR / "legacy"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    destination = legacy_dir / path.name
    if destination.exists():
        destination = legacy_dir / f"{path.stem}_{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(destination))


def _migrate_legacy_statistics_once() -> None:
    """Import legacy JSON only when the SQLite database is still empty."""
    if get_meta("legacy_json_migration_complete") == "1":
        return

    if STATS_PATH.exists():
        source_digest = _sha256(STATS_PATH)

        if database_has_statistics():
            print(
                "Existing SQLite statistics found; preserving them and "
                "archiving the legacy stats.json without overwriting data."
            )
        else:
            summary = import_stats_json(
                STATS_PATH,
                replace=False,
                keep_raw_backup=True,
            )
            print(
                "Migrated legacy stats.json to SQLite: "
                f"{summary['songs']} songs, {summary['artists']} artists."
            )

        set_meta("legacy_stats_sha256", source_digest)
        _archive_legacy_file(STATS_PATH)

    set_meta("legacy_json_migration_complete", "1")


def _migrate_legacy_status_once() -> None:
    if not STATUS_PATH.exists():
        return
    try:
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        if isinstance(status, dict) and get_current_status() is None:
            write_current_status(status)
        _archive_legacy_file(STATUS_PATH)
    except Exception as exc:
        print(f"Could not migrate legacy status.json to SQLite: {exc}")


def initialize_storage() -> None:
    """Initialize SQLite and safely absorb legacy JSON runtime data once."""
    global _initialized
    if _initialized:
        return

    with _lock:
        if _initialized:
            return

        init_db()
        try:
            _migrate_legacy_statistics_once()
        except Exception as exc:
            print(f"Could not migrate legacy stats.json to SQLite: {exc}")
        _migrate_legacy_status_once()
        _initialized = True
