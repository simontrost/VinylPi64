from __future__ import annotations

from difflib import SequenceMatcher
import re
import time
from typing import Any

from vinylpi.core.discogs_db import (
    find_exact_title_tracks,
    get_next_track,
    get_release_tracks,
    get_track_counts,
    normalize_artist,
    normalize_text,
)
from vinylpi.core.image_utils import load_image
from vinylpi.core.loop_state import DiscogsPlaybackState
from vinylpi.core.models import RecognizedTrack
from vinylpi.core.title_variants import canonicalize_title


_BRACKETED_VARIANT = re.compile(
    r"[\[(][^\])]*(?:unplugged|live|acoustic|session|radio|bbc|kexp)[^\])]*[\])]",
    flags=re.IGNORECASE,
)
_TRAILING_VARIANT = re.compile(
    r"\s+(?:mtv\s+unplugged|unplugged|live|acoustic|session)(?:\s+version)?\s*$",
    flags=re.IGNORECASE,
)


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _base_title_norm(value: str | None) -> str:
    title = canonicalize_title(value or "")
    title = _BRACKETED_VARIANT.sub("", title)
    title = _TRAILING_VARIANT.sub("", title)
    return normalize_text(title)


def _variant_tags(*values: str | None) -> set[str]:
    text = " ".join(str(value or "") for value in values).casefold()
    tags: set[str] = set()
    if "unplugged" in text:
        tags.update({"unplugged", "live"})
    if "acoustic" in text:
        tags.update({"acoustic", "live"})
    if any(marker in text for marker in (" live", "live ", "live at", "concert", "session")):
        tags.add("live")
    if "remix" in text:
        tags.add("remix")
    if "instrumental" in text:
        tags.add("instrumental")
    if "cover" in text:
        tags.add("cover")
    return tags


def _candidate_key(candidate: dict[str, Any]) -> tuple[int, int]:
    return (int(candidate["release_id"]), int(candidate["track_index"]))


def _next_transition_ready(state: DiscogsPlaybackState) -> bool:
    if state.current_started_at is None:
        return True
    elapsed = time.monotonic() - state.current_started_at
    if state.current_duration_seconds and state.current_duration_seconds > 0:
        threshold = max(35.0, min(150.0, float(state.current_duration_seconds) * 0.55))
    else:
        threshold = 45.0
    return elapsed >= threshold


def _score_candidate(
    candidate: dict[str, Any],
    *,
    title_norm: str,
    base_title_norm: str,
    artist_norm: str,
    album_norm: str,
    observed_variant_tags: set[str],
    state: DiscogsPlaybackState,
    sequence_enabled: bool,
) -> tuple[float, dict[str, Any]]:
    candidate_title_norm = str(candidate.get("normalized_title") or "")
    candidate_base_title = _base_title_norm(candidate.get("track_title"))
    full_title_similarity = _similarity(title_norm, candidate_title_norm)
    base_title_similarity = _similarity(base_title_norm, candidate_base_title)
    title_similarity = max(full_title_similarity, base_title_similarity)
    artist_similarity = _similarity(artist_norm, str(candidate.get("normalized_artist") or ""))
    album_similarity = _similarity(album_norm, normalize_text(candidate.get("release_title")))

    candidate_variant_tags = _variant_tags(
        candidate.get("track_title"),
        candidate.get("release_title"),
    )
    variant_overlap = observed_variant_tags & candidate_variant_tags
    version_score = 0.0
    if observed_variant_tags:
        if "unplugged" in variant_overlap:
            version_score += 48.0
        elif "acoustic" in variant_overlap:
            version_score += 34.0
        elif "live" in variant_overlap:
            version_score += 24.0

        for special in ("remix", "instrumental", "cover"):
            if special in variant_overlap:
                version_score += 35.0

        live_observed = bool(observed_variant_tags & {"live", "unplugged", "acoustic"})
        live_candidate = bool(candidate_variant_tags & {"live", "unplugged", "acoustic"})
        if live_observed and not live_candidate:
            version_score -= 48.0

        for special in ("remix", "instrumental", "cover"):
            if special in observed_variant_tags and special not in candidate_variant_tags:
                version_score -= 55.0

    active_release = (
        state.active_release_id is not None
        and int(candidate["release_id"]) == int(state.active_release_id)
    )
    expected_next = bool(
        active_release
        and state.current_track_index is not None
        and int(candidate["track_index"]) == int(state.current_track_index) + 1
    )
    same_side = bool(active_release and state.current_side and candidate.get("side") == state.current_side)
    transition_ready = not expected_next or _next_transition_ready(state)

    score = title_similarity * 70.0
    score += artist_similarity * 25.0
    score += album_similarity * 10.0
    score += version_score
    if title_similarity == 1.0:
        score += 25.0
    if artist_similarity == 1.0:
        score += 15.0
    if active_release:
        score += 22.0
    if same_side:
        score += 5.0
    if sequence_enabled and expected_next and transition_ready:
        score += 42.0
        if title_similarity >= 0.60 and artist_similarity >= 0.45:
            score += 18.0
    elif expected_next and not transition_ready:
        # Do not let the expected-next bonus force a premature track switch.
        score -= 8.0

    return score, {
        "title_similarity": title_similarity,
        "full_title_similarity": full_title_similarity,
        "base_title_similarity": base_title_similarity,
        "artist_similarity": artist_similarity,
        "album_similarity": album_similarity,
        "active_release": active_release,
        "expected_next": expected_next,
        "transition_ready": transition_ready,
        "variant_overlap": bool(variant_overlap),
        "version_score": version_score,
    }


def _is_plausible(
    score: float,
    metrics: dict[str, Any],
    minimum_confidence: float,
) -> bool:
    title_similarity = float(metrics["title_similarity"])
    artist_similarity = float(metrics["artist_similarity"])
    album_similarity = float(metrics["album_similarity"])
    active_release = bool(metrics["active_release"])
    expected_next = bool(metrics["expected_next"])
    variant_overlap = bool(metrics["variant_overlap"])
    confidence = min(1.0, max(0.0, score / 140.0))

    if confidence < minimum_confidence:
        return False
    if title_similarity >= 0.88 and (artist_similarity >= 0.55 or album_similarity >= 0.75):
        return True
    if variant_overlap and title_similarity >= 0.84 and artist_similarity >= 0.55:
        return True
    if active_release and title_similarity >= 0.78 and artist_similarity >= 0.45:
        return True
    if expected_next and title_similarity >= 0.60 and artist_similarity >= 0.45:
        return True
    return False


def apply_discogs_match(
    track: RecognizedTrack,
    state: DiscogsPlaybackState,
    config: dict[str, Any],
    *,
    debug_log: bool = False,
) -> RecognizedTrack:
    discogs_cfg = config.get("discogs") or {}
    if not bool(discogs_cfg.get("enabled", False)):
        return track
    if not bool(discogs_cfg.get("prefer_collection", True)):
        return track

    title_norm = normalize_text(canonicalize_title(track.title))
    base_title_norm = _base_title_norm(track.title)
    artist_norm = normalize_artist(track.artist)
    album_norm = normalize_text(track.album)
    observed_variant_tags = _variant_tags(track.title, track.album)
    if not title_norm:
        return track

    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    for candidate in find_exact_title_tracks(title_norm):
        candidates[_candidate_key(candidate)] = candidate

    # Shazam often appends version information to the title while Discogs stores
    # the plain track title and the version on the release, e.g.
    # "Nutshell (Unplugged)" on "MTV Unplugged".
    if base_title_norm and base_title_norm != title_norm:
        for candidate in find_exact_title_tracks(base_title_norm):
            candidates[_candidate_key(candidate)] = candidate

    sequence_enabled = bool(discogs_cfg.get("sequence_matching", True))
    if sequence_enabled and state.active_release_id is not None:
        for candidate in get_release_tracks(state.active_release_id):
            candidates[_candidate_key(candidate)] = candidate

    if not candidates:
        return track

    try:
        minimum_confidence = float(discogs_cfg.get("min_match_confidence", 0.72))
    except (TypeError, ValueError):
        minimum_confidence = 0.72
    minimum_confidence = min(0.95, max(0.5, minimum_confidence))

    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates.values():
        score, metrics = _score_candidate(
            candidate,
            title_norm=title_norm,
            base_title_norm=base_title_norm,
            artist_norm=artist_norm,
            album_norm=album_norm,
            observed_variant_tags=observed_variant_tags,
            state=state,
            sequence_enabled=sequence_enabled,
        )
        ranked.append((score, metrics, candidate))

    ranked.sort(key=lambda item: item[0], reverse=True)
    score, metrics, best = ranked[0]
    if not _is_plausible(score, metrics, minimum_confidence):
        if debug_log:
            print(
                "Discogs: no sufficiently reliable collection match "
                f"for {track.artist} – {track.title} (best={score:.1f})."
            )
        return track

    confidence = min(1.0, max(0.0, score / 140.0))
    source = (
        "sequence"
        if bool(metrics["expected_next"]) and bool(metrics["transition_ready"])
        else "collection"
    )
    original = f"{track.artist} – {track.title} [{track.album or '-'}]"

    track.artist = str(best.get("track_artist") or best.get("release_artist") or track.artist)
    track.title = str(best.get("track_title") or track.title)
    track.album = str(best.get("release_title") or track.album or "") or None
    if not track.duration_ms and best.get("duration_seconds"):
        track.duration_ms = int(best["duration_seconds"]) * 1000

    release_id = int(best["release_id"])
    track_index = int(best["track_index"])
    counts = get_track_counts(release_id, track_index, best.get("side"))
    next_track = get_next_track(release_id, track_index)

    track.discogs_release_id = release_id
    track.discogs_position = best.get("position")
    track.discogs_side = best.get("side")
    track.discogs_track_index = track_index
    track.discogs_track_count = counts["track_count"]
    track.discogs_side_track_number = counts["side_track_number"] or None
    track.discogs_side_track_count = counts["side_track_count"] or None
    track.discogs_match_source = source
    track.discogs_confidence = round(confidence, 3)
    track.discogs_cover_url = best.get("cover_url")
    track.discogs_year = best.get("year")
    track.discogs_label = best.get("label")
    track.discogs_catalog_number = best.get("catalog_number")
    if next_track:
        track.discogs_expected_next_title = next_track.get("track_title")
        track.discogs_expected_next_artist = next_track.get("track_artist")
        track.discogs_expected_next_position = next_track.get("position")
        track.discogs_expected_next_side = next_track.get("side")

    if debug_log:
        corrected = f"{track.artist} – {track.title} [{track.album or '-'}]"
        version_note = " version-aware" if metrics.get("variant_overlap") else ""
        print(
            f"Discogs {source}{version_note} match "
            f"({confidence:.0%}, {best.get('position') or '?'}): "
            f"{original} -> {corrected}"
        )
    return track


def discogs_transition_ready(
    state: DiscogsPlaybackState,
    track: RecognizedTrack,
    *,
    debug_log: bool = False,
) -> bool:
    """Protect statistics from premature A4/A5-style Shazam oscillation.

    A direct jump to a non-adjacent or previous track is still allowed. Only the
    physically expected next track is held until enough of the current track has
    elapsed. A genuine needle jump therefore becomes countable once it remains
    stable, while momentary alternating Shazam results do not inflate stats.
    """
    if (
        state.active_release_id is None
        or state.current_track_index is None
        or track.discogs_release_id is None
        or track.discogs_track_index is None
    ):
        return True
    if int(track.discogs_release_id) != int(state.active_release_id):
        return True
    if int(track.discogs_track_index) != int(state.current_track_index) + 1:
        return True

    ready = _next_transition_ready(state)
    if debug_log and not ready:
        elapsed = (
            time.monotonic() - state.current_started_at
            if state.current_started_at is not None
            else 0.0
        )
        print(
            "Stats guard: holding expected next Discogs track "
            f"{track.discogs_position or '?'} after only {elapsed:.0f}s."
        )
    return ready


def update_discogs_playback_state(
    state: DiscogsPlaybackState,
    track: RecognizedTrack,
) -> None:
    if track.discogs_release_id is None or track.discogs_track_index is None:
        state.reset()
        return
    state.active_release_id = int(track.discogs_release_id)
    state.current_track_index = int(track.discogs_track_index)
    state.current_side = track.discogs_side
    state.current_position = track.discogs_position
    state.current_started_at = time.monotonic()
    state.current_duration_seconds = (
        float(track.duration_ms) / 1000.0 if track.duration_ms and track.duration_ms > 0 else None
    )
    state.current_cover_url = track.discogs_cover_url or track.cover_url
    state.clear_inference()


def clear_discogs_inference(state: DiscogsPlaybackState) -> None:
    state.clear_inference()



def _side_letter_index(side: str | None) -> int | None:
    value = str(side or "").strip().upper()
    if len(value) != 1 or not ("A" <= value <= "Z"):
        return None
    return ord(value) - ord("A") + 1


def _is_turn_record_transition(current_side: str | None, next_side: str | None) -> bool:
    current_index = _side_letter_index(current_side)
    next_index = _side_letter_index(next_side)
    if current_index is None or next_index is None:
        return False
    return next_index == current_index + 1 and (current_index % 2 == 1)


def get_side_flip_prompt(
    state: DiscogsPlaybackState,
    config: dict[str, Any],
    *,
    consecutive_failures: int,
    debug_log: bool = False,
) -> dict[str, Any] | None:
    discogs_cfg = config.get("discogs") or {}
    if not bool(discogs_cfg.get("enabled", False)):
        return None
    if consecutive_failures < 1:
        return None
    if (
        state.active_release_id is None
        or state.current_track_index is None
        or state.current_started_at is None
        or not state.current_duration_seconds
    ):
        return None

    next_track = get_next_track(state.active_release_id, state.current_track_index)
    if not next_track:
        return None

    next_side = next_track.get("side")
    current_side = state.current_side
    if not _is_turn_record_transition(current_side, next_side):
        return None

    elapsed = time.monotonic() - state.current_started_at
    threshold = max(30.0, float(state.current_duration_seconds) * 0.72)
    if elapsed < threshold:
        return None

    prompt = {
        "from_side": current_side,
        "to_side": next_side,
        "next_title": next_track.get("track_title"),
        "next_artist": next_track.get("track_artist"),
        "next_position": next_track.get("position"),
        "release_id": state.active_release_id,
    }
    if debug_log:
        print(
            "Discogs side-flip prompt: "
            f"{current_side or '?'} -> {next_side or '?'} "
            f"({next_track.get('position') or '?'})"
        )
    return prompt

def infer_expected_next_track(
    state: DiscogsPlaybackState,
    config: dict[str, Any],
    *,
    consecutive_failures: int,
    debug_log: bool = False,
) -> RecognizedTrack | None:
    discogs_cfg = config.get("discogs") or {}
    if not bool(discogs_cfg.get("enabled", False)):
        return None
    if not bool(discogs_cfg.get("sequence_matching", True)):
        return None
    if not bool(discogs_cfg.get("infer_unrecognized_next", True)):
        return None
    if consecutive_failures < 2:
        return None
    if (
        state.active_release_id is None
        or state.current_track_index is None
        or state.current_started_at is None
        or not state.current_duration_seconds
    ):
        return None

    elapsed = time.monotonic() - state.current_started_at
    threshold = max(30.0, float(state.current_duration_seconds) * 0.72)
    if elapsed < threshold:
        return None

    next_track = get_next_track(state.active_release_id, state.current_track_index)
    if not next_track:
        return None
    if state.current_side and next_track.get("side") != state.current_side:
        # Never infer a side flip. The user may stop or change the record.
        return None
    next_index = int(next_track["track_index"])
    if state.inferred_track_index == next_index:
        return None

    cover_url = next_track.get("cover_url") or state.current_cover_url
    if not cover_url:
        return None
    try:
        cover_image = load_image(str(cover_url))
    except Exception as exc:
        if debug_log:
            print(f"Discogs: could not load cover for sequence estimate: {exc}")
        return None

    counts = get_track_counts(
        int(next_track["release_id"]),
        next_index,
        next_track.get("side"),
    )
    after_next = get_next_track(int(next_track["release_id"]), next_index)
    inferred = RecognizedTrack(
        artist=str(next_track.get("track_artist") or next_track.get("release_artist") or "Unknown artist"),
        title=str(next_track.get("track_title") or "Unknown track"),
        cover_image=cover_image,
        album=str(next_track.get("release_title") or "") or None,
        cover_url=str(cover_url),
        duration_ms=(
            int(next_track["duration_seconds"]) * 1000
            if next_track.get("duration_seconds")
            else None
        ),
    )
    inferred.discogs_release_id = int(next_track["release_id"])
    inferred.discogs_position = next_track.get("position")
    inferred.discogs_side = next_track.get("side")
    inferred.discogs_track_index = next_index
    inferred.discogs_track_count = counts["track_count"]
    inferred.discogs_side_track_number = counts["side_track_number"] or None
    inferred.discogs_side_track_count = counts["side_track_count"] or None
    inferred.discogs_match_source = "sequence_inferred"
    inferred.discogs_confidence = 0.68
    inferred.discogs_cover_url = str(cover_url)
    inferred.discogs_year = next_track.get("year")
    inferred.discogs_label = next_track.get("label")
    inferred.discogs_catalog_number = next_track.get("catalog_number")
    if after_next:
        inferred.discogs_expected_next_title = after_next.get("track_title")
        inferred.discogs_expected_next_artist = after_next.get("track_artist")
        inferred.discogs_expected_next_position = after_next.get("position")
        inferred.discogs_expected_next_side = after_next.get("side")

    state.inferred_track_index = next_index
    state.inferred_started_at = time.monotonic()
    state.inferred_duration_seconds = (
        float(inferred.duration_ms) / 1000.0 if inferred.duration_ms else None
    )
    if debug_log:
        print(
            "Discogs sequence estimate: "
            f"{inferred.discogs_position or '?'} – {inferred.artist} – {inferred.title}"
        )
    return inferred


def should_hold_inferred_track(state: DiscogsPlaybackState) -> bool:
    if state.inferred_track_index is None or state.inferred_started_at is None:
        return False
    duration = state.inferred_duration_seconds or 180.0
    return (time.monotonic() - state.inferred_started_at) < max(45.0, duration * 1.20)

