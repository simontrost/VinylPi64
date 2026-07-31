from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from vinylpi.config.runtime import read_config, write_config
from vinylpi.core.discogs_db import (
    delete_releases_not_in,
    get_collection_counts,
    get_detailed_release_ids,
    get_sync_state,
    replace_release_details,
    set_sync_state,
    upsert_release_summary,
)
from vinylpi.integrations.discogs_client import DiscogsClient, DiscogsError

_SIDE_RE = re.compile(r"^([A-Z]+)", re.IGNORECASE)


def get_discogs_token(cfg: dict[str, Any] | None = None) -> str:
    env_token = (os.getenv("DISCOGS_TOKEN") or "").strip()
    if env_token:
        return env_token
    config = cfg if cfg is not None else read_config()
    return str((config.get("discogs") or {}).get("token") or "").strip()


def _artist_name(value: dict[str, Any]) -> str:
    name = str(value.get("name") or "").strip()
    return name


def _join_artists(values: Any, fallback: str = "Unknown artist") -> str:
    if not isinstance(values, list):
        return fallback
    names = [_artist_name(value) for value in values if isinstance(value, dict)]
    names = [name for name in names if name]
    return ", ".join(names) if names else fallback


def _format_text(formats: Any) -> str:
    if not isinstance(formats, list):
        return ""
    parts: list[str] = []
    for item in formats:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        descriptions = item.get("descriptions") or []
        if isinstance(descriptions, list):
            descriptions = [str(value).strip() for value in descriptions if str(value).strip()]
        else:
            descriptions = []
        text = name
        if descriptions:
            text += f" ({', '.join(descriptions)})"
        if text:
            parts.append(text)
    return ", ".join(parts)


def _is_vinyl(formats: Any) -> bool:
    if not isinstance(formats, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("name") or "").casefold() == "vinyl"
        for item in formats
    )


def _duration_seconds(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _side_from_position(position: str | None) -> str | None:
    match = _SIDE_RE.match((position or "").strip())
    return match.group(1).upper() if match else None


def _primary_image(details: dict[str, Any], fallback: str | None = None) -> str | None:
    images = details.get("images") or []
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and image.get("type") == "primary" and image.get("uri"):
                return str(image["uri"])
        for image in images:
            if isinstance(image, dict) and image.get("uri"):
                return str(image["uri"])
    return fallback


def collection_summary(entry: dict[str, Any]) -> dict[str, Any]:
    basic = entry.get("basic_information") or {}
    artists = basic.get("artists") or []
    labels = basic.get("labels") or []
    first_label = labels[0] if labels and isinstance(labels[0], dict) else {}
    return {
        "release_id": int(entry.get("id") or basic.get("id")),
        "instance_id": entry.get("instance_id"),
        "folder_id": entry.get("folder_id"),
        "title": str(basic.get("title") or "Unknown release"),
        "artist": str(basic.get("artists_sort") or _join_artists(artists)),
        "year": basic.get("year") or None,
        "country": basic.get("country") or None,
        "label": first_label.get("name"),
        "catalog_number": first_label.get("catno"),
        "format_text": _format_text(basic.get("formats")),
        "thumb_url": basic.get("thumb"),
        "cover_url": basic.get("cover_image"),
        "date_added": entry.get("date_added"),
        "details_loaded": False,
        "formats": basic.get("formats") or [],
    }


def parse_release_details(
    details: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    release_artist = str(
        details.get("artists_sort")
        or _join_artists(details.get("artists"), summary.get("artist") or "Unknown artist")
    )
    labels = details.get("labels") or []
    first_label = labels[0] if labels and isinstance(labels[0], dict) else {}
    release = {
        **summary,
        "title": str(details.get("title") or summary.get("title") or "Unknown release"),
        "artist": release_artist,
        "year": details.get("year") or summary.get("year"),
        "country": details.get("country") or summary.get("country"),
        "label": first_label.get("name") or summary.get("label"),
        "catalog_number": first_label.get("catno") or summary.get("catalog_number"),
        "format_text": _format_text(details.get("formats")) or summary.get("format_text"),
        "cover_url": _primary_image(details, summary.get("cover_url")),
        "details_loaded": True,
    }

    tracks: list[dict[str, Any]] = []

    def append_track(track: dict[str, Any], inherited_position: str = "") -> None:
        track_type = str(track.get("type_") or "track").casefold()
        if track_type not in {"track", "index"}:
            return
        sub_tracks = track.get("sub_tracks") or []
        if isinstance(sub_tracks, list) and sub_tracks:
            parent_position = str(track.get("position") or inherited_position or "").strip()
            for sub_track in sub_tracks:
                if isinstance(sub_track, dict):
                    append_track(sub_track, parent_position)
            return

        title = str(track.get("title") or "").strip()
        if not title:
            return
        position = str(track.get("position") or inherited_position or "").strip()
        track_artist = str(
            track.get("artists_sort")
            or _join_artists(track.get("artists"), release_artist)
        )
        tracks.append(
            {
                "track_index": len(tracks),
                "position": position or None,
                "side": _side_from_position(position),
                "title": title,
                "artist": track_artist,
                "duration_seconds": _duration_seconds(track.get("duration")),
            }
        )

    for item in details.get("tracklist") or []:
        if isinstance(item, dict):
            append_track(item)

    return release, tracks


class DiscogsSyncManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._runtime: dict[str, Any] = {
            "syncing": False,
            "current": 0,
            "total": 0,
            "message": "",
        }

    def status(self) -> dict[str, Any]:
        cfg = read_config()
        discogs_cfg = cfg.get("discogs") or {}
        token = get_discogs_token(cfg)
        persisted = get_sync_state()
        counts = get_collection_counts()
        with self._lock:
            runtime = dict(self._runtime)
        return {
            "enabled": bool(discogs_cfg.get("enabled", False)),
            "connected": bool(token),
            "username": discogs_cfg.get("username") or persisted.get("username") or "",
            "token_source": "environment" if os.getenv("DISCOGS_TOKEN") else ("config" if token else ""),
            "releases_count": counts["releases"],
            "tracks_count": counts["tracks"],
            "last_synced_at": persisted.get("last_synced_at"),
            "sync_status": persisted.get("status") or "never",
            "last_error": persisted.get("last_error") or "",
            "failed_releases": int(persisted.get("failed_releases") or 0),
            **runtime,
        }

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._runtime = {
                "syncing": True,
                "current": 0,
                "total": 0,
                "message": "Connecting to Discogs…",
            }
            self._thread = threading.Thread(target=self._run, daemon=True, name="discogs-sync")
            self._thread.start()
            return True

    def _progress(self, current: int, total: int, message: str) -> None:
        with self._lock:
            self._runtime.update({"current": current, "total": total, "message": message})

    def _finish(self, message: str) -> None:
        with self._lock:
            self._runtime.update({"syncing": False, "message": message})

    def _run(self) -> None:
        failed = 0
        try:
            cfg = read_config(force=True)
            discogs_cfg = cfg.get("discogs") or {}
            token = get_discogs_token(cfg)
            client = DiscogsClient(token)
            identity = client.identity()
            username = str(identity.get("username") or discogs_cfg.get("username") or "").strip()
            if not username:
                raise DiscogsError("Discogs did not return an account name.")

            write_config({"discogs": {"username": username, "enabled": True}})
            set_sync_state(username=username, status="syncing", message="Loading collection…", error=None)

            vinyl_only = bool(discogs_cfg.get("vinyl_only", True))
            entries_by_release: dict[int, dict[str, Any]] = {}
            for entry in client.iter_collection_releases(username):
                summary = collection_summary(entry)
                if vinyl_only and not _is_vinyl(summary.get("formats")):
                    continue
                entries_by_release[int(summary["release_id"])] = summary

            entries = list(entries_by_release.values())
            total = len(entries)
            self._progress(0, total, f"Found {total} releases. Preparing details…")
            detailed_ids = get_detailed_release_ids()
            seen_ids: set[int] = set()

            for index, summary in enumerate(entries, start=1):
                release_id = int(summary["release_id"])
                seen_ids.add(release_id)
                upsert_release_summary(summary)
                if release_id in detailed_ids:
                    self._progress(index, total, f"Indexed {index} of {total}: {summary['title']}")
                    continue

                self._progress(index - 1, total, f"Loading {summary['artist']} – {summary['title']}")
                try:
                    details = client.get_release(release_id)
                    release, tracks = parse_release_details(details, summary)
                    replace_release_details(release, tracks)
                    detailed_ids.add(release_id)
                except Exception as exc:
                    failed += 1
                    print(f"Discogs release {release_id} could not be imported: {exc}")
                self._progress(index, total, f"Indexed {index} of {total}: {summary['title']}")

            delete_releases_not_in(seen_ids)
            result_message = f"Discogs collection synchronized: {total} releases."
            if failed:
                result_message += f" {failed} release details could not be loaded."
            set_sync_state(
                username=username,
                status="complete_with_warnings" if failed else "complete",
                message=result_message,
                error=None,
                failed_releases=failed,
                completed=True,
            )
            self._finish(result_message)
        except Exception as exc:
            message = str(exc)
            set_sync_state(
                status="error",
                message="Discogs synchronization failed.",
                error=message,
                failed_releases=failed,
            )
            self._finish(message)


SYNC_MANAGER = DiscogsSyncManager()
