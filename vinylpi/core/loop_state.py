from dataclasses import dataclass, field
from typing import Optional

@dataclass
class LoopConfig:
    delay: int = 10
    debug_log: bool = False
    fallback_allowed_failures: int = 3
    auto_sleep: int = 50
    base_sample_seconds: float = 4.0
    adaptive_sample_enabled: bool = False
    adaptive_failure_durations: tuple[float, ...] = (6.0, 8.0)

    def sample_seconds_for_failures(self, consecutive_failures: int) -> float:
        if not self.adaptive_sample_enabled or consecutive_failures <= 0:
            return self.base_sample_seconds
        if not self.adaptive_failure_durations:
            return self.base_sample_seconds
        index = min(consecutive_failures - 1, len(self.adaptive_failure_durations) - 1)
        return max(0.5, float(self.adaptive_failure_durations[index]))

    @staticmethod
    def from_config(cfg: dict) -> "LoopConfig":
        behavior = cfg.get("behavior", {})
        debug = cfg.get("debug", {})
        fallback = cfg.get("fallback", {})
        audio = cfg.get("audio", {})
        adaptive = audio.get("adaptive_sample", {}) or {}
        durations = adaptive.get("failure_durations_seconds", [6, 8])
        if not isinstance(durations, (list, tuple)):
            durations = [6, 8]
        cleaned_values: list[float] = []
        for value in durations:
            try:
                cleaned_values.append(max(0.5, float(value)))
            except (TypeError, ValueError):
                continue
        cleaned_durations = tuple(cleaned_values)

        return LoopConfig(
            delay=int(behavior.get("loop_delay_seconds", 10)),
            debug_log=bool(debug.get("logs", False)),
            fallback_allowed_failures=int(fallback.get("allowed_failures", 3)),
            auto_sleep=int(behavior.get("auto_sleep", 50)),
            base_sample_seconds=max(0.5, float(audio.get("sample_seconds", 4))),
            adaptive_sample_enabled=bool(adaptive.get("enabled", False)),
            adaptive_failure_durations=cleaned_durations or (6.0, 8.0),
        )

@dataclass
class DisplayState:
    last_song_id: Optional[tuple[str, str]] = None
    last_song_variant_score: Optional[int] = None
    last_display_was_fallback: bool = False
    consecutive_failures: int = 0

@dataclass
class AlbumState:
    current_album: Optional[str] = None
    current_album_session_counted: bool = False
    current_album_unique_tracks: set[str] = field(default_factory=set)
    candidate_album: Optional[str] = None
    candidate_streak: int = 0

@dataclass
class StatsSwitchState:
    current_song_id: Optional[tuple[str, str]] = None
    candidate_song_id: Optional[tuple[str, str]] = None
    candidate_streak: int = 0

@dataclass
class TimedListenState:
    active_song_id: Optional[tuple[str, str]] = None
    active_artist: Optional[str] = None
    active_title: Optional[str] = None
    active_album: Optional[str] = None
    active_started_at: Optional[float] = None
    active_needs_timer_fallback: bool = False