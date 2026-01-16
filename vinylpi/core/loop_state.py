from dataclasses import dataclass, field
from typing import Optional

@dataclass
class LoopConfig:
    delay: int = 10
    debug_log: bool = False
    fallback_allowed_failures: int = 3
    auto_sleep: int = 50

    @staticmethod
    def from_config(cfg: dict) -> "LoopConfig":
        behavior = cfg.get("behavior", {})
        debug = cfg.get("debug", {})
        fallback = cfg.get("fallback", {})

        return LoopConfig(
            delay=int(behavior.get("loop_delay_seconds", 10)),
            debug_log=bool(debug.get("logs", False)),
            fallback_allowed_failures=int(fallback.get("allowed_failures", 3)),
            auto_sleep=int(behavior.get("auto_sleep", 50)),
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
