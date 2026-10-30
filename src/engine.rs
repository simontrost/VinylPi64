use crate::{
    audio,
    config::{Config, ConfigStore},
    db::Db,
    discogs::Discogs,
    display::{Content, Display},
    metadata::Metadata,
    model::{Mode, Track, album_identity},
    net,
    spotify::Spotify,
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{mpsc, oneshot, watch};
use tokio_util::sync::CancellationToken;

type Observation = (Option<Track>, Option<(f64, f64)>);
enum EngineEvent {
    Stop,
    Command(Option<ModeCommand>),
    Observation(Box<Result<Observation>>),
}
pub struct ModeCommand {
    mode: Mode,
    reply: oneshot::Sender<Result<()>>,
}
pub struct Engine {
    commands: mpsc::Sender<ModeCommand>,
    pub status: watch::Sender<Value>,
    pub mode: watch::Sender<Mode>,
}
pub struct Services {
    pub config: Arc<ConfigStore>,
    pub db: Db,
    pub display: Arc<Display>,
    pub spotify: Arc<Spotify>,
    pub discogs: Arc<Discogs>,
    pub metadata: Arc<Metadata>,
    pub client: reqwest::Client,
}
#[derive(Clone, Default, serde::Serialize, serde::Deserialize)]
struct Confirmation {
    candidate: String,
    consecutive: usize,
    counted: String,
    album: String,
    album_tracks: std::collections::HashSet<String>,
    album_recorded: bool,
    pending_album: String,
    pending_tracks: std::collections::HashSet<String>,
}
impl Confirmation {
    fn observe(&mut self, t: &Track, min: usize) -> (bool, bool) {
        let id = t.identity();
        if self.candidate == id {
            self.consecutive += 1
        } else {
            self.candidate = id.clone();
            self.consecutive = 1
        };
        let count = self.consecutive >= min && self.counted != id;
        let album = t.album.as_deref().map(|a| album_identity(&t.artist, a)).unwrap_or_default();
        let mut new_album = false;
        if count {
            self.counted = id.clone();
            if !album.is_empty() {
                if self.album.is_empty() {
                    self.album = album.clone();
                }
                if self.album == album {
                    self.pending_album.clear();
                    self.pending_tracks.clear();
                    self.album_tracks.insert(id);
                    // Two DISTINCT, confirmed tracks: one session, regardless
                    // of differences in explicit remaster/edition suffixes.
                    if self.album_tracks.len() >= 2 && !self.album_recorded {
                        self.album_recorded = true;
                        new_album = true;
                    }
                } else {
                    // A single confirmed but unrelated album match must not
                    // end an ongoing session (and permit duplicate counting).
                    // Switch only after two confirmed tracks on the new album.
                    if self.pending_album != album {
                        self.pending_album = album.clone();
                        self.pending_tracks.clear();
                    }
                    self.pending_tracks.insert(id);
                    if self.pending_tracks.len() >= 2 {
                        self.album = album;
                        self.album_tracks = std::mem::take(&mut self.pending_tracks);
                        self.pending_album.clear();
                        self.album_recorded = true;
                        new_album = true;
                    }
                }
            }
        };
        (count, new_album)
    }
    fn failure(&mut self) {
        self.candidate.clear();
        self.consecutive = 0;
    }
}
/// Checkpoints preserve the exact confirmed-track and album-session guards.
/// The last-recognized track is stored alongside them so a new song can never
/// accidentally inherit an old song's count protection.
#[derive(serde::Serialize, serde::Deserialize)]
struct ConfirmationCheckpoint {
    seen_ms: i64,
    track: Track,
    state: Confirmation,
}
impl ConfirmationCheckpoint {
    fn key(mode: Mode) -> &'static str {
        match mode {
            Mode::Vinyl => "recognition_checkpoint_vinyl_v1",
            Mode::Spotify => "recognition_checkpoint_spotify_v1",
            Mode::Off => "recognition_checkpoint_off_v1",
        }
    }
    fn load(db: &Db, mode: Mode) -> Result<Option<Self>> {
        let rows = db.query("SELECT value FROM meta WHERE key=?", [Self::key(mode)])?;
        rows.first().and_then(|r| r["value"].as_str())
            .map(serde_json::from_str::<Self>)
            .transpose().map_err(Into::into)
    }
    fn save(db: &Db, mode: Mode, track: &Track, state: &Confirmation, at: i64) -> Result<()> {
        let value = serde_json::to_string(&Self { seen_ms: at, track: track.clone(), state: state.clone() })?;
        db.with(|conn| {
            conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [Self::key(mode), value.as_str()])?;
            Ok(())
        })
    }
    fn restore(&self, current: &Track, mode: Mode, now_ms: i64, state: &mut Confirmation) -> bool {
        if !(0..=PlaybackResume::STATUS_MAX_AGE_MS).contains(&(now_ms - self.seen_ms)) {
            return false;
        }
        let same_song = self.track.identity() == current.identity()
            && (mode != Mode::Spotify || self.track.key(mode) == current.key(mode));
        if mode == Mode::Vinyl {
            let album = current.album.as_deref()
                .map(|name| album_identity(&current.artist, name))
                .unwrap_or_default();
            if !album.is_empty()
                && (album == self.state.album || album == self.state.pending_album)
            {
                // Even if the needle has reached the NEXT song during the
                // deployment, retain the confirmed album and any pending
                // transition without counting a second album session.
                state.album = self.state.album.clone();
                state.album_tracks = self.state.album_tracks.clone();
                state.album_recorded = self.state.album_recorded;
                state.pending_album = self.state.pending_album.clone();
                state.pending_tracks = self.state.pending_tracks.clone();
            }
        }
        if !same_song {
            return false;
        }
        if mode == Mode::Spotify
            && let (Some(old), Some(new)) = (self.track.progress_ms, current.progress_ms)
            && (new + 1500 < old || new > old.saturating_add(now_ms - self.seen_ms + 30_000))
        {
            return false;
        }
        *state = self.state.clone();
        // An interrupted partial run of confirmations does not count as
        // three consecutive results, but already confirmed plays stay counted.
        state.failure();
        true
    }
}

/// A short service restart may interrupt an already counted playback. The
/// most recent confirmed event and the continuously updated source status are
/// persisted in SQLite, so we can resume that one song without recording it
/// (and its artist/full duration) for a second time.
struct PlaybackResume {
    checkpoint: Option<ConfirmationCheckpoint>,
    previous: Track,
    last_seen_ms: i64,
    counted_track: Option<String>,
    last_counted_at: i64,
    last_album_track: Option<String>,
    last_album_session: Option<(String, String, i64)>,
}
impl PlaybackResume {
    const STATUS_MAX_AGE_MS: i64 = 120_000;

    fn from_db(db: &Db, mode: Mode) -> Result<Option<Self>> {
        if mode == Mode::Off {
            return Ok(None);
        }
        if let Some(checkpoint) = ConfirmationCheckpoint::load(db, mode)? {
            let now_ms = chrono::Utc::now().timestamp_millis();
            if (0..=Self::STATUS_MAX_AGE_MS).contains(&(now_ms - checkpoint.seen_ms)) {
                return Ok(Some(Self {
                    previous: checkpoint.track.clone(),
                    last_seen_ms: checkpoint.seen_ms,
                    counted_track: None,
                    last_counted_at: 0,
                    last_album_track: None,
                    last_album_session: None,
                    checkpoint: Some(checkpoint),
                }));
            }
        }
        let Some(status) = db.last_status(mode)? else {
            return Ok(None);
        };
        let Some(last_seen_ms) = status["updated_at"].as_i64() else {
            return Ok(None);
        };
        let now_ms = chrono::Utc::now().timestamp_millis();
        if !(0..=Self::STATUS_MAX_AGE_MS).contains(&(now_ms - last_seen_ms)) {
            return Ok(None);
        }
        let previous: Track = serde_json::from_value(status)?;
        if previous.artist.is_empty() || previous.title.is_empty() {
            return Ok(None);
        }
        let last = db.query(
            "SELECT artist,title,album,song_key,occurred_at FROM playback_events WHERE source=? AND event_type='play' ORDER BY id DESC LIMIT 1",
            [mode.as_str()],
        )?;
        let last_counted_at = last.first().and_then(|r| r["occurred_at"].as_i64()).unwrap_or(0);
        let last_album_track = last.first().and_then(|r| {
            let name = r["album"].as_str()?;
            let artist = r["artist"].as_str()?;
            let title = r["title"].as_str()?;
            let current_album = previous.album.as_deref()?;
            (album_identity(artist, name) == album_identity(&previous.artist, current_album))
                .then(|| Track { artist: artist.into(), title: title.into(), ..Default::default() }.identity())
        });
        let counted_track = last.first().and_then(|r| {
            if mode == Mode::Spotify {
                return r["song_key"].as_str().map(str::to_owned);
            }
            let artist = r["artist"].as_str()?;
            let title = r["title"].as_str()?;
            Some(Track { artist: artist.into(), title: title.into(), ..Default::default() }.identity())
        });
        let last_album_session = if mode == Mode::Vinyl {
            db.query(
                "SELECT a.album,a.occurred_at,(SELECT p.artist FROM playback_events p WHERE p.source='vinyl' AND p.event_type='play' AND p.album=a.album AND p.occurred_at=a.occurred_at AND p.id<a.id ORDER BY p.id DESC LIMIT 1) artist FROM playback_events a WHERE a.source='vinyl' AND a.event_type='album_session' ORDER BY a.id DESC LIMIT 1",
                [],
            )?.first().and_then(|r| Some((r["album"].as_str()?.to_owned(), r["artist"].as_str()?.to_owned(), r["occurred_at"].as_i64()?)))
        } else {
            None
        };
        Ok(Some(Self {
            checkpoint: None,
            previous,
            last_seen_ms,
            counted_track,
            last_counted_at,
            last_album_track,
            last_album_session,
        }))
    }

    fn matches_song(&self, track: &Track, mode: Mode) -> bool {
        self.previous.identity() == track.identity()
            && (mode != Mode::Spotify || self.previous.key(mode) == track.key(mode))
    }

    /// Reuse the previous state on a matching song, or carry just the album
    /// state once a different song has passed its full confirmation threshold.
    fn resume(&self, current: &Track, mode: Mode, now_ms: i64, state: &mut Confirmation) -> bool {
        if let Some(checkpoint) = &self.checkpoint {
            // Return true only if this playback was already counted.
            return checkpoint.restore(current, mode, now_ms, state)
                && state.counted == current.identity();
        }
        if !(0..=Self::STATUS_MAX_AGE_MS).contains(&(now_ms - self.last_seen_ms)) {
            return false;
        }
        let now = now_ms / 1000;
        let album = current.album.as_deref().map(|a| album_identity(&current.artist, a)).unwrap_or_default();
        let previous_album = self.previous.album.as_deref()
            .map(|a| album_identity(&self.previous.artist, a)).unwrap_or_default();
        if mode == Mode::Vinyl && !album.is_empty() && album == previous_album {
            // Preserve the already counted album session across the restart,
            // preventing a second session on the next two confirmed tracks.
            if let Some((name, artist, at)) = &self.last_album_session
                && (0..=7200).contains(&(now - at))
                && album == album_identity(artist, name)
            {
                state.album = album.clone();
                state.album_recorded = true;
            }
            if let Some(id) = &self.last_album_track
                && (0..=7200).contains(&(now - self.last_counted_at))
            {
                state.album = album;
                state.album_tracks.insert(id.clone());
            }
        }
        if current.identity() != self.previous.identity()
            || (mode == Mode::Spotify && current.key(mode) != self.previous.key(mode))
        {
            return false;
        }
        let counted_key = if mode == Mode::Spotify {
            current.key(mode)
        } else {
            current.identity()
        };
        if self.counted_track.as_deref() != Some(counted_key.as_str()) {
            return false;
        }
        let duration_ms = current.duration_ms.or(self.previous.duration_ms);
        // Allow enough time for the current track to finish, but never treat
        // an arbitrarily old play as a continuation. Unknown lengths use a
        // bounded 10-minute window. This is a heuristic, not audio position.
        let window_secs = duration_ms
            .filter(|ms| *ms > 0)
            .map(|ms| (ms / 1000 + 60).clamp(90, 1800))
            .unwrap_or(600);
        if !(0..=window_secs).contains(&(now - self.last_counted_at)) {
            return false;
        }
        if mode == Mode::Spotify {
            // Spotify exposes track progress. If it restarted at position 0,
            // this is a real replay, not a process-restart continuation.
            if let (Some(previous), Some(current)) = (self.previous.progress_ms, current.progress_ms) {
                let gap_ms = now_ms - self.last_seen_ms;
                if current + 1500 < previous || current > previous.saturating_add(gap_ms + 30_000) {
                    return false;
                }
            }
        }
        state.counted = current.identity();
        true
    }
}
#[derive(Default)]
struct Wake {
    armed: bool,
    above: f64,
    below: f64,
}
impl Wake {
    fn observe(&mut self, level: f64, seconds: f64, cfg: &Config) -> bool {
        if !cfg.behavior.vinyl_auto_wake_enabled {
            return false;
        };
        let threshold = cfg.behavior.vinyl_auto_wake_threshold_dbfs;
        if !self.armed {
            if level <= threshold - 3. {
                self.below += seconds;
                if self.below >= 1. {
                    self.armed = true;
                    self.below = 0.;
                }
            } else {
                self.below = 0.;
            }
            if cfg.audio.pickup_usage.start_threshold_dbfs >= threshold + 3.
                && level >= cfg.audio.pickup_usage.start_threshold_dbfs
            {
                self.above += seconds
            } else {
                self.above = 0.
            };
        } else if level >= threshold {
            self.above += seconds
        } else {
            self.above = 0.
        };
        if self.above >= cfg.behavior.vinyl_auto_wake_confirm_seconds {
            self.above = 0.;
            true
        } else {
            false
        }
    }
}
impl Engine {
    pub fn new() -> (Arc<Self>, mpsc::Receiver<ModeCommand>) {
        let (tx, rx) = mpsc::channel(16);
        let (status, _) = watch::channel(
            json!({"source":"off","artist":"","title":"Recognition off","updated_at":chrono::Utc::now().timestamp_millis(),"bg_color":[0,0,0]}),
        );
        let (mode, _) = watch::channel(Mode::Off);
        (
            Arc::new(Self {
                commands: tx,
                status,
                mode,
            }),
            rx,
        )
    }
    pub fn get_mode(&self) -> Mode {
        *self.mode.borrow()
    }
    pub async fn set_mode(&self, mode: Mode) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.commands
            .send(ModeCommand { mode, reply: tx })
            .await
            .context("Recognition engine stopped")?;
        rx.await.context("Recognition engine stopped")?
    }
    fn waiting(&self, mode: Mode, last: Option<Value>) {
        if let Some(mut status) = last.filter(|s| s["artist"].as_str().is_some_and(|v| !v.is_empty()) && s["title"].as_str().is_some_and(|v| !v.is_empty())) {
            status["source"] = json!(mode);
            status["is_playing"] = json!(false);
            status["restored"] = json!(true);
            if let Some(v) = status.as_object_mut() {
                for key in ["error", "side_flip_prompt_active", "side_flip_from_side", "side_flip_to_side", "side_flip_next_title", "side_flip_next_position"] {
                    v.remove(key);
                }
            }
            self.status.send_replace(status);
        } else {
            self.status.send_replace(json!({"source":mode,"artist":"","title":match mode{Mode::Off=>"Recognition off",Mode::Vinyl=>"Waiting for vinyl…",Mode::Spotify=>"Waiting for Spotify…"},"is_playing":false,"updated_at":chrono::Utc::now().timestamp_millis(),"bg_color":[0,0,0]}));
        }
    }
    async fn change(&self, mode: Mode, s: &Services) -> Result<()> {
        if mode == self.get_mode() {
            return Ok(());
        };
        if mode == Mode::Spotify {
            ensure!(
                s.spotify.status()?["connected"] == true,
                "Connect Spotify in Settings first"
            );
            // A paused player, expired access token or temporary Spotify API
            // outage must not prevent choosing the source or showing its last
            // cached song. The polling loop handles network failures/retries.
        }
        if mode == Mode::Vinyl {
            audio::devices()?;
        }
        let cfg = s.config.get();
        let old = self.get_mode();
        let remembered = s.db.last_status(mode)?;
        self.mode.send_replace(mode);
        self.waiting(mode, remembered.clone());
        // The dashboard may show the last recognized track while waiting.
        // On the physical Pixoo, immediately replace any old album art or
        // standby GIF with the normal fallback image when Vinyl or Spotify
        // starts. Do not wait for the recognition-failure threshold.
        // Fallback(false) is intentionally independent of fallback.enabled:
        // that setting only governs the later failure-triggered fallback.
        s.display.show(Content::Fallback(false));
        if mode != Mode::Off {
            if cfg.fallback.image_path.is_empty() {
                s.db.log("WARNING", "Pixoo startup fallback image is not configured");
            } else {
                s.db.log(
                    "INFO",
                    &format!("Pixoo startup fallback queued for {}", mode.as_str()),
                );
            }
        }
        if mode == Mode::Off && old != Mode::Off {
            match cfg.pixoo_automations.off_action.as_str() {
                "brightness_off" => {
                    s.display.show(Content::Hold);
                    if let Err(e) = s
                        .display
                        .pixoo
                        .command(json!({"Command":"Channel/SetBrightness","Brightness":0}))
                        .await
                    {
                        s.db.log("WARNING", &format!("Pixoo off automation: {e}"));
                    }
                }
                "community_gif" if !cfg.pixoo_automations.stop_gif_file_id.is_empty() => {
                    s.display.show(Content::Hold);
                    if let Err(e)=s.display.pixoo.command(json!({"Command":"Draw/SendRemote","FileId":cfg.pixoo_automations.stop_gif_file_id})).await{s.db.log("WARNING",&format!("Pixoo stop GIF: {e}"));}
                }
                _ => {}
            }
        }
        if mode != Mode::Off
            && cfg.pixoo_automations.turn_on_on_start
            && let Err(e) = s
                .display
                .pixoo
                .command(json!({"Command":"Channel/SetBrightness","Brightness":100}))
                .await
        {
            s.db.log("WARNING", &format!("Pixoo start automation: {e}"));
        }
        s.db.log("INFO", &format!("Source changed to {}", mode.as_str()));
        Ok(())
    }
    pub async fn run(
        self: Arc<Self>,
        mut commands: mpsc::Receiver<ModeCommand>,
        s: Services,
        cancel: CancellationToken,
    ) {
        let mut confirmation = Confirmation::default();
        let mut resume: Option<PlaybackResume> = None;
        let mut last: Option<Track> = None;
        let mut failures = 0usize;
        let mut silence = 0.;
        let mut wake = Wake {
            armed: true,
            ..Default::default()
        };
        let mut manual = false;
        let mut pickup = crate::pickup::Pickup::default();
        let epoch = Instant::now();
        let mut display_fallback = true;
        let mut next = tokio::time::Instant::now();
        let mut spotify_previous: Option<(String, i64, Instant)> = None;
        let mut unavailable = 0u32;
        loop {
            let mode = self.get_mode();
            let cfg = s.config.get();
            let seconds = if mode == Mode::Off {
                0.5
            } else if cfg.audio.adaptive_sample.enabled && failures > 0 {
                cfg.audio
                    .adaptive_sample
                    .failure_durations_seconds
                    .get(failures - 1)
                    .or_else(|| cfg.audio.adaptive_sample.failure_durations_seconds.last())
                    .copied()
                    .unwrap_or(cfg.audio.sample_seconds)
            } else {
                cfg.audio.sample_seconds
            };
            let operation_cancel = cancel.child_token();
            let _cancel_on_drop = operation_cancel.clone().drop_guard();
            let operation = async {
                tokio::time::sleep_until(next).await;
                if mode == Mode::Spotify {
                    return Ok::<_, anyhow::Error>((s.spotify.current().await?, None));
                };
                if mode == Mode::Off
                    && (!cfg.behavior.vinyl_auto_wake_enabled || !cfg!(target_os = "linux"))
                {
                    cancel.cancelled().await;
                    return Ok((None, None));
                }
                if mode == Mode::Vinyl && cfg.debug.logs {
                    s.db.log("DEBUG", &format!("Recording vinyl audio sample ({seconds:.1}s)…"));
                }
                let audio_cfg = cfg.audio.clone();
                let wav_path = cfg.debug.wav_path.clone();
                let samples = tokio::task::spawn_blocking(move || {
                    audio::capture(&audio_cfg, seconds, &operation_cancel, &wav_path)
                })
                .await??;
                let level = audio::dbfs(&samples);
                let observed = epoch.elapsed().as_secs_f64();
                if mode == Mode::Off {
                    return Ok((None, Some((level, observed))));
                };
                if cfg.behavior.vinyl_audio_sleep_enabled
                    && level < cfg.behavior.vinyl_audio_sleep_threshold_dbfs
                {
                    return Ok((None, Some((level, observed))));
                };
                if cfg.debug.logs { s.db.log("DEBUG", "Audio sample recorded; starting Shazam recognition…"); }
                let mut track =
                    net::recognize(&s.client, samples, cfg.shazam.timeout_seconds).await?;
                if let Some(t) = &mut track {
                    if let Err(e) = s.discogs.enrich(t, &cfg, last.as_ref()) {
                        // Matching is optional enrichment. Never discard a valid
                        // Shazam result because the local Discogs database failed.
                        s.db.log("WARNING", &format!("Discogs matching unavailable: {e}"));
                    }
                    if let Err(e) = s.metadata.enrich(t).await {
                        s.db.log("WARNING", &format!("Metadata enrichment unavailable: {e}"));
                    }
                }
                Ok((track, Some((level, observed))))
            };
            let event = tokio::select! {biased; _=cancel.cancelled()=>EngineEvent::Stop,command=commands.recv()=>EngineEvent::Command(command),result=operation=>EngineEvent::Observation(Box::new(result))};
            match event {
                EngineEvent::Stop => break,
                EngineEvent::Command(command) => {
                    let Some(command) = command else { break };
                    let changed = command.mode != mode;
                    let result = self.change(command.mode, &s).await;
                    if result.is_ok() && changed {
                        resume = match PlaybackResume::from_db(&s.db, command.mode) {
                            Ok(guard) => guard,
                            Err(e) => {
                                s.db.log("WARNING", &format!("Unable to restore playback continuity: {e}"));
                                None
                            }
                        };
                        confirmation = Confirmation::default();
                        last = None;
                        failures = 0;
                        silence = 0.;
                        manual = command.mode == Mode::Vinyl;
                        pickup.reset();
                        display_fallback = true;
                        spotify_previous = None;
                        unavailable = 0;
                        wake = Wake::default();
                        next = tokio::time::Instant::now() + Duration::from_millis(50);
                    }
                    let _ = command.reply.send(result);
                }
                EngineEvent::Observation(result) => {
                    let result = *result;
                    next = tokio::time::Instant::now()
                        + Duration::from_secs_f64(if mode == Mode::Spotify {
                            cfg.spotify.poll_seconds
                        } else if mode == Mode::Off {
                            0.02
                        } else {
                            cfg.behavior.loop_delay_seconds
                        });
                    match result {
                        Err(e) => {
                            pickup.reset();
                            unavailable = (unavailable + 1).min(6);
                            let delay = (5u64 << unavailable.saturating_sub(1)).min(300);
                            next = tokio::time::Instant::now() + Duration::from_secs(delay);
                            // Auto-wake probes USB in Off mode too. Do not turn a
                            // missing turntable into a permanent stream of warnings.
                            if mode != Mode::Off || unavailable == 1 {
                                s.db.log(
                                    if mode == Mode::Off { "INFO" } else { "WARNING" },
                                    &format!(
                                        "{} audio input unavailable; retry in {delay}s: {e}{}",
                                        mode.as_str(),
                                        if mode == Mode::Off { " (auto-wake is enabled; disable Vinyl auto wake in Settings to stop probing)" } else { "" },
                                    ),
                                );
                            }
                            if mode != Mode::Off {
                                let mut status = self.status.borrow().clone();
                                status["error"] = json!(e.to_string());
                                self.status.send_replace(status);
                            }
                            confirmation.failure();
                            spotify_previous = None;
                        }
                        Ok((track, level)) => {
                            unavailable = 0;
                            if let Some((level, observed)) = level {
                                if mode == Mode::Off {
                                    if wake.observe(level, seconds, &cfg)
                                        && self.change(Mode::Vinyl, &s).await.is_ok()
                                    {
                                        manual = false;
                                        resume = PlaybackResume::from_db(&s.db, Mode::Vinyl).unwrap_or_else(|e| {
                                            s.db.log("WARNING", &format!("Unable to restore playback continuity: {e}"));
                                            None
                                        });
                                        confirmation = Confirmation::default();
                                        failures = 0;
                                        silence = 0.;
                                    }
                                    continue;
                                }
                                if level < cfg.behavior.vinyl_audio_sleep_threshold_dbfs {
                                    silence += seconds
                                } else {
                                    silence = 0.
                                };
                                let usage = pickup.observe(
                                    level,
                                    seconds,
                                    observed,
                                    &cfg.audio.pickup_usage,
                                );
                                if usage > 0.
                                    && let Err(e) =
                                        s.db.seconds(Mode::Vinyl, None, usage.min(1800.), true)
                                {
                                    s.db.log("ERROR", &e.to_string());
                                }
                            }
                            if let Some(t) = track {
                                failures = 0;
                                let id = t.identity();
                                let changed = last.as_ref().is_none_or(|old| old.identity() != id);
                                // Do not discard the restart guard because
                                // of one stray Shazam match. A *different* song
                                // must reach the usual confirmation threshold.
                                let threshold = if mode == Mode::Spotify {
                                    1
                                } else {
                                    cfg.behavior.stats_min_consecutive as usize
                                };
                                let confirmed_different = if confirmation.candidate == id {
                                    confirmation.consecutive + 1 >= threshold
                                } else {
                                    threshold <= 1
                                };
                                let apply_resume = resume.as_ref().is_some_and(|guard| {
                                    guard.matches_song(&t, mode) || confirmed_different
                                });
                                if apply_resume
                                    && let Some(guard) = resume.take()
                                    && guard.resume(&t, mode, chrono::Utc::now().timestamp_millis(), &mut confirmation)
                                {
                                    s.db.log("INFO", &format!("Continuing already counted playback after restart: {} – {} [{}]; duplicate statistics suppressed", t.artist, t.title, mode.as_str()));
                                }
                                if mode == Mode::Spotify {
                                    let progress = t.progress_ms.unwrap_or(0);
                                    let now = Instant::now();
                                    if let Some((previous, p, at)) = &spotify_previous {
                                        let delta = progress - *p;
                                        let elapsed = now.duration_since(*at).as_secs_f64();
                                        if previous == &id
                                            && delta >= 0
                                            && (delta as f64 / 1000. - elapsed).abs() <= 3.
                                            && delta <= 15000
                                            && let Err(e) = s.db.seconds(
                                                mode,
                                                Some(&t.key(mode)),
                                                delta as f64 / 1000.,
                                                false,
                                            )
                                        {
                                            s.db.log("ERROR", &e.to_string());
                                        }
                                        if previous == &id
                                            && progress + 30000 < *p
                                            && progress < 10000
                                        {
                                            confirmation.counted.clear();
                                        }
                                    }
                                    spotify_previous = Some((id.clone(), progress, now));
                                }
                                // A failed SQLite transaction must not consume a
                                // confirmation or lose a pending album session.
                                let before_confirmation = confirmation.clone();
                                let (count, new_album) = confirmation.observe(&t, threshold);
                                if cfg.debug.logs && !count && mode == Mode::Vinyl && changed {
                                    s.db.log("DEBUG", &format!("Recognition candidate: {} – {} (confirmation {}/{})", t.artist, t.title, confirmation.consecutive, cfg.behavior.stats_min_consecutive as usize));
                                }
                                if count {
                                    s.db.log("INFO", &format!("Play confirmed: {} – {} [{}]{}", t.artist, t.title, mode.as_str(), if new_album { "; album session recorded" } else { "" }));
                                    if let Err(e) = s.db.record_play(mode, &t, new_album) {
                                        s.db.log("ERROR", &format!("Statistics write failed: {e}"));
                                        confirmation = before_confirmation;
                                    } else if mode == Mode::Vinyl
                                        && let Some(duration) = t.duration_ms
                                        && let Err(e) =
                                            s.db.seconds(mode, None, duration as f64 / 1000., false)
                                    {
                                        s.db.log("ERROR", &e.to_string());
                                    }
                                }
                                if mode == Mode::Vinyl
                                    && confirmation.counted == id
                                    && t.duration_ms.is_none()
                                    && let Err(e) =
                                        s.db.seconds(mode, Some(&t.key(mode)), seconds, false)
                                {
                                    s.db.log("ERROR", &e.to_string());
                                }
                                let mut v = serde_json::to_value(&t).expect("Track serialization");
                                v["source"] = json!(mode);
                                v["is_playing"] = json!(true);
                                v["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
                                let previous = self.status.borrow().clone();
                                let keep_existing_color = previous["source"] == json!(mode)
                                    && previous["artist"] == json!(t.artist)
                                    && previous["title"] == json!(t.title)
                                    && previous.get("bg_color").is_some();
                                v["bg_color"] = if keep_existing_color {
                                    previous["bg_color"].clone()
                                } else {
                                    json!([30, 30, 30])
                                };
                                if let Err(e) = s.db.save_status(mode, &v) {
                                    s.db.log("ERROR", &e.to_string());
                                }
                                // A single unconfirmed mismatching match must
                                // not overwrite the prior restart checkpoint.
                                if resume.is_none()
                                    && let Err(e) = ConfirmationCheckpoint::save(
                                        &s.db,
                                        mode,
                                        &t,
                                        &confirmation,
                                        v["updated_at"].as_i64().unwrap_or_default(),
                                    )
                                {
                                    s.db.log("WARNING", &format!("Unable to persist recognition checkpoint: {e}"));
                                }
                                self.status.send_replace(v);
                                let returning_from_fallback = display_fallback;
                                if changed || returning_from_fallback {
                                    s.display.show(Content::Track(Box::new(t.clone())));
                                    display_fallback = false;
                                }
                                if cfg.debug.logs {
                                    let action = if changed {
                                        "Pixoo update queued (new track)"
                                    } else if returning_from_fallback {
                                        "Pixoo update queued (returning from fallback)"
                                    } else {
                                        "same as before; Pixoo unchanged"
                                    };
                                    s.db.log(
                                        if changed { "INFO" } else { "DEBUG" },
                                        &format!(
                                            "{} recognized: {} – {}{}; {action}",
                                            mode.as_str(),
                                            t.artist,
                                            t.title,
                                            t.album.as_ref().map(|a| format!(" ({a})")).unwrap_or_default()
                                        ),
                                    );
                                }
                                last = Some(t);
                            } else {
                                failures += 1;
                                if cfg.debug.logs {
                                    s.db.log("DEBUG", &format!("{}: no song recognized ({} consecutive unsuccessful samples)",mode.as_str(), failures));
                                }
                                confirmation.failure();
                                spotify_previous = None;
                                let flip = if mode == Mode::Vinyl
                                    && cfg.discogs.enabled
                                    && cfg.fallback.side_flip_enabled
                                {
                                    last.as_ref().and_then(crate::discogs::side_flip_target)
                                } else {
                                    None
                                };
                                if failures == cfg.fallback.allowed_failures as usize {
                                    s.db.log("INFO", if flip.is_some() { "Recognition failed repeatedly; displaying record side-flip prompt" } else if cfg.fallback.enabled { "Recognition failed repeatedly; displaying fallback image" } else { "Recognition failed repeatedly; fallback disabled" });
                                    if let Some(side) = &flip {
                                        s.display.show(Content::SideFlip(side.clone()));
                                        display_fallback = true;
                                    } else if cfg.fallback.enabled {
                                        s.display.show(Content::Fallback(false));
                                        display_fallback = true;
                                    }
                                }
                                let sleep = if mode == Mode::Spotify {
                                    cfg.spotify.auto_sleep_enabled
                                        && failures >= cfg.spotify.auto_sleep_iterations as usize
                                } else {
                                    (!manual || !cfg.behavior.vinyl_manual_shutdown_only)
                                        && ((cfg.behavior.vinyl_audio_sleep_enabled
                                            && silence
                                                >= cfg.behavior.vinyl_audio_sleep_confirm_seconds)
                                            || (cfg.behavior.vinyl_auto_sleep_enabled
                                                && failures
                                                    >= cfg.behavior.vinyl_auto_sleep_iterations
                                                        as usize))
                                };
                                if sleep {
                                    s.db.log("INFO", &format!("{} auto sleep: recognition/silence threshold reached",mode.as_str()));
                                    let _ = self.change(Mode::Off, &s).await;
                                    wake = Wake::default();
                                    confirmation = Confirmation::default();
                                    resume = None;
                                    last = None;
                                } else {
                                    let mut v = self.status.borrow().clone();
                                    v["is_playing"] = json!(false);
                                    let active_flip = failures
                                        >= cfg.fallback.allowed_failures as usize
                                        && flip.is_some();
                                    v["side_flip_prompt_active"] = json!(active_flip);
                                    if active_flip {
                                        let side = flip.as_deref().unwrap_or_default();
                                        v["side_flip_from_side"] = last
                                            .as_ref()
                                            .and_then(|t| t.extra.get("discogs_side"))
                                            .cloned()
                                            .unwrap_or(Value::Null);
                                        v["side_flip_to_side"] = json!(side);
                                        v["side_flip_next_title"] = last
                                            .as_ref()
                                            .and_then(|t| {
                                                t.extra.get("discogs_expected_next_title")
                                            })
                                            .cloned()
                                            .unwrap_or(Value::Null);
                                        v["side_flip_next_position"] = last
                                            .as_ref()
                                            .and_then(|t| {
                                                t.extra.get("discogs_expected_next_position")
                                            })
                                            .cloned()
                                            .unwrap_or(Value::Null);
                                    }
                                    v["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
                                    if failures == cfg.fallback.allowed_failures as usize
                                        && mode == Mode::Vinyl
                                        && let Err(e) = s.db.save_status(mode, &v)
                                    {
                                        s.db.log(
                                            "WARNING",
                                            &format!("Saving fallback status failed: {e}"),
                                        );
                                    }
                                    self.status.send_replace(v);
                                }
                            }
                        }
                    }
                }
            }
        }
        self.mode.send_replace(Mode::Off);
        s.db.log("INFO", "Recognition engine stopped");
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn track(title: &str) -> Track {
        Track {
            artist: "a".into(),
            title: title.into(),
            album: Some("album".into()),
            ..Default::default()
        }
    }
    #[test]
    fn counts_confirmed_transitions_and_retains_guard_across_failures() {
        let mut c = Confirmation::default();
        assert!(!c.observe(&track("one"), 2).0);
        assert_eq!(c.observe(&track("one"), 2), (true, false));
        c.failure();
        c.observe(&track("one"), 2);
        assert!(!c.observe(&track("one"), 2).0);
        c.observe(&track("two"), 2);
        assert_eq!(c.observe(&track("two"), 2), (true, true));
        c.observe(&track("one"), 2);
        assert!(c.observe(&track("one"), 2).0);
    }
    #[test]
    fn counts_one_album_session_for_confirmed_editions_but_not_unconfirmed_tracks() {
        let mut c = Confirmation::default();
        let first = track("one");
        let mut second = track("two");
        second.album = Some("album (2016 Remaster)".into());
        assert_eq!(c.observe(&first, 3), (false, false));
        assert_eq!(c.observe(&first, 3), (false, false));
        assert_eq!(c.observe(&first, 3), (true, false));
        assert_eq!(c.observe(&second, 3), (false, false));
        c.failure();
        assert_eq!(c.observe(&second, 3), (false, false));
        assert_eq!(c.observe(&second, 3), (false, false));
        assert_eq!(c.observe(&second, 3), (true, true));
        let mut third = track("three");
        third.album = Some("album (Deluxe)".into());
        for _ in 0..3 {
            assert!(!c.observe(&third, 3).1);
        }
    }

    #[test]
    fn a_single_confirmed_wrong_album_cannot_duplicate_an_active_session() {
        let mut c = Confirmation::default();
        for title in ["one", "two"] {
            c.observe(&track(title), 2);
            assert_eq!(c.observe(&track(title), 2).1, title == "two");
        }
        let mut wrong = track("other");
        wrong.artist = "different artist".into();
        wrong.album = Some("unrelated album".into());
        c.observe(&wrong, 2);
        assert_eq!(c.observe(&wrong, 2), (true, false));
        c.observe(&track("three"), 2);
        assert_eq!(c.observe(&track("three"), 2), (true, false));
        c.observe(&track("four"), 2);
        assert_eq!(c.observe(&track("four"), 2), (true, false));
    }

    #[test]
    fn a_new_album_requires_two_distinct_confirmed_tracks_to_start_a_new_session() {
        let mut c = Confirmation::default();
        c.observe(&track("one"), 2);
        assert_eq!(c.observe(&track("one"), 2), (true, false));
        c.observe(&track("two"), 2);
        assert_eq!(c.observe(&track("two"), 2), (true, true));
        let mut next = track("three");
        next.album = Some("another album".into());
        c.observe(&next, 2);
        assert_eq!(c.observe(&next, 2), (true, false));
        let mut later = track("four");
        later.album = Some("another album (2016 Remaster)".into());
        c.observe(&later, 2);
        assert_eq!(c.observe(&later, 2), (true, true));
        c.observe(&track("five"), 2);
        assert!(!c.observe(&track("five"), 2).1);
    }

    #[test]
    fn album_state_can_be_restored_after_failed_statistics_transaction() {
        let mut c = Confirmation::default();
        c.observe(&track("one"), 2);
        assert_eq!(c.observe(&track("one"), 2), (true, false));
        c.observe(&track("two"), 2);
        let saved = c.clone();
        assert_eq!(c.observe(&track("two"), 2), (true, true));
        c = saved; // as engine does when the database transaction fails
        assert_eq!(c.observe(&track("two"), 2), (true, true));
    }

    #[test]
    fn restart_does_not_recount_a_confirmed_song_artist_duration_or_album() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("continuity.sqlite")).unwrap();
        let mut first = track("Why Worry");
        first.duration_ms = Some(360_000);
        db.record_play(Mode::Vinyl, &first, true).unwrap();
        db.seconds(Mode::Vinyl, None, 360., false).unwrap();
        let mut status = serde_json::to_value(&first).unwrap();
        status["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
        db.save_status(Mode::Vinyl, &status).unwrap();
        drop(db);
        let db = Db::open(&dir.path().join("continuity.sqlite")).unwrap();
        let guard = PlaybackResume::from_db(&db, Mode::Vinyl).unwrap().unwrap();
        let mut confirmation = Confirmation::default();
        assert!(guard.resume(&first, Mode::Vinyl, chrono::Utc::now().timestamp_millis(), &mut confirmation));
        for _ in 0..4 {
            assert_eq!(confirmation.observe(&first, 3), (false, false));
        }
        let second = track("The Man's Too Strong");
        confirmation.observe(&second, 3);
        confirmation.observe(&second, 3);
        assert_eq!(confirmation.observe(&second, 3), (true, false));
        assert_eq!(db.query("SELECT count(*) n FROM playback_events WHERE event_type='play'", []).unwrap()[0]["n"], 1);
        assert_eq!(db.stats("vinyl", None).unwrap()["total_minutes_listened"], 6);
    }

    #[test]
    fn restart_lets_new_tracks_count_and_rejects_stale_continuations() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("continuity.sqlite")).unwrap();
        let previous = track("Why Worry");
        db.record_play(Mode::Vinyl, &previous, false).unwrap();
        let now = chrono::Utc::now().timestamp_millis();
        let mut status = serde_json::to_value(&previous).unwrap();
        status["updated_at"] = json!(now);
        db.save_status(Mode::Vinyl, &status).unwrap();
        let guard = PlaybackResume::from_db(&db, Mode::Vinyl).unwrap().unwrap();
        let mut confirmation = Confirmation::default();
        assert!(!guard.resume(&track("Different Song"), Mode::Vinyl, now, &mut confirmation));
        assert_eq!(confirmation.observe(&track("Different Song"), 2), (false, false));
        // The previous track was already counted before the restart. Once a
        // different song on the SAME album is confirmed, both distinct tracks
        // qualify for the album's first session. Resuming must not suppress it.
        assert_eq!(confirmation.observe(&track("Different Song"), 2), (true, true));
        assert!(confirmation.album_recorded);
        let mut stale = Confirmation::default();
        assert!(!guard.resume(&previous, Mode::Vinyl, now + 121_000, &mut stale));
        assert_eq!(stale.observe(&previous, 2), (false, false));
        assert_eq!(stale.observe(&previous, 2), (true, false));
    }

    #[test]
    fn persisted_checkpoint_retains_album_state_and_prevents_recounting() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("checkpoint.sqlite")).unwrap();
        let a = track("A");
        let b = track("B");
        let mut before = Confirmation::default();
        for _ in 0..3 { before.observe(&a, 3); }
        for _ in 0..3 { before.observe(&b, 3); }
        assert!(before.album_recorded);
        assert_eq!(before.counted, b.identity());
        let now = chrono::Utc::now().timestamp_millis();
        ConfirmationCheckpoint::save(&db, Mode::Vinyl, &b, &before, now).unwrap();
        drop(db);
        let db = Db::open(&dir.path().join("checkpoint.sqlite")).unwrap();
        let mut after = Confirmation::default();
        let recovered = PlaybackResume::from_db(&db, Mode::Vinyl).unwrap().unwrap();
        assert!(recovered.resume(&b, Mode::Vinyl, now + 1000, &mut after));
        assert!(after.album_recorded);
        assert_eq!(after.album_tracks.len(), 2);
        for _ in 0..3 { assert_eq!(after.observe(&b, 3), (false, false)); }
        let next = track("C");
        for _ in 0..2 { after.observe(&next, 3); }
        assert_eq!(after.observe(&next, 3), (true, false));
    }

    #[test]
    fn incomplete_pre_restart_confirmation_needs_three_new_recognitions() {
        let now = chrono::Utc::now().timestamp_millis();
        let track = track("Uncounted");
        let mut before = Confirmation::default();
        assert_eq!(before.observe(&track, 3), (false, false));
        assert_eq!(before.observe(&track, 3), (false, false));
        let checkpoint = ConfirmationCheckpoint {
            seen_ms: now - 1_000, track: track.clone(), state: before,
        };
        let mut after = Confirmation::default();
        assert!(checkpoint.restore(&track, Mode::Vinyl, now, &mut after));
        assert_eq!(after.observe(&track, 3), (false, false));
        assert_eq!(after.observe(&track, 3), (false, false));
        assert_eq!(after.observe(&track, 3), (true, false));
    }

    #[test]
    fn persisted_checkpoint_does_not_suppress_a_different_first_track() {
        let previous = track("Why Worry");
        let now = chrono::Utc::now().timestamp_millis();
        let mut old = Confirmation::default();
        for _ in 0..3 { old.observe(&previous, 3); }
        let checkpoint = ConfirmationCheckpoint { seen_ms: now, track: previous, state: old };
        let mut state = Confirmation::default();
        let mut different = track("Ride Across the River");
        different.album = Some("Different album".into());
        assert!(!checkpoint.restore(&different, Mode::Vinyl, now + 1000, &mut state));
        assert_eq!(state.observe(&different, 3), (false, false));
        assert_eq!(state.observe(&different, 3), (false, false));
        assert_eq!(state.observe(&different, 3), (true, false));
    }

    #[test]
    fn next_song_after_restart_preserves_existing_album_session() {
        let now = chrono::Utc::now().timestamp_millis();
        let mut before = Confirmation::default();
        for name in ["one", "two"] {
            for _ in 0..3 { before.observe(&track(name), 3); }
        }
        assert!(before.album_recorded);
        let checkpoint = ConfirmationCheckpoint {
            seen_ms: now - 10_000, track: track("two"), state: before,
        };
        let mut after = Confirmation::default();
        let next = track("three");
        assert!(!checkpoint.restore(&next, Mode::Vinyl, now, &mut after));
        assert!(after.album_recorded);
        for _ in 0..2 { after.observe(&next, 3); }
        assert_eq!(after.observe(&next, 3), (true, false));
    }

    #[test]
    fn persisted_checkpoint_expires_and_spotify_restarts_from_beginning() {
        let now = chrono::Utc::now().timestamp_millis();
        let mut previous = track("Repeat");
        previous.track_id = Some("spotify:test:123".into());
        previous.progress_ms = Some(180_000);
        let mut prior = Confirmation::default();
        assert!(prior.observe(&previous, 1).0);
        let checkpoint = ConfirmationCheckpoint {
            seen_ms: now - 20_000, track: previous.clone(), state: prior,
        };
        let mut repeated = previous;
        repeated.progress_ms = Some(2_000);
        let mut fresh = Confirmation::default();
        assert!(!checkpoint.restore(&repeated, Mode::Spotify, now, &mut fresh));
        assert!(fresh.observe(&repeated, 1).0);
        let mut after_gap = Confirmation::default();
        assert!(!checkpoint.restore(&repeated, Mode::Spotify, now + 121_000, &mut after_gap));
    }

    #[test]
    fn spotify_rewind_after_restart_is_a_new_play() {
        let now = chrono::Utc::now().timestamp_millis();
        let mut previous = track("Repeat");
        previous.progress_ms = Some(153_000);
        let guard = PlaybackResume {
            checkpoint: None,
            previous: previous.clone(), last_seen_ms: now - 5_000,
            counted_track: Some(previous.identity()), last_counted_at: now / 1000 - 40,
            last_album_track: None, last_album_session: None,
        };
        let mut resumed = previous.clone();
        resumed.progress_ms = Some(156_000);
        let mut normal = Confirmation::default();
        assert!(guard.resume(&resumed, Mode::Spotify, now, &mut normal));
        assert!(!normal.observe(&resumed, 1).0);
        resumed.progress_ms = Some(1_000);
        let mut replay = Confirmation::default();
        assert!(!guard.resume(&resumed, Mode::Spotify, now, &mut replay));
        assert!(replay.observe(&resumed, 1).0);
    }
    #[test]
    fn wake_requires_sustained_signal_and_rearms() {
        let cfg = Config::default();
        let mut w = Wake::default();
        assert!(!w.observe(-30., 3., &cfg));
        assert!(!w.observe(-90., 1., &cfg));
        assert!(!w.observe(-30., 1., &cfg));
        assert!(w.observe(-30., 1., &cfg));
    }
}
