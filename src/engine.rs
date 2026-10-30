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
#[derive(Clone, Default)]
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
                                let (count, new_album) = confirmation.observe(
                                    &t,
                                    if mode == Mode::Spotify {
                                        1
                                    } else {
                                        cfg.behavior.stats_min_consecutive as usize
                                    },
                                );
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
    fn wake_requires_sustained_signal_and_rearms() {
        let cfg = Config::default();
        let mut w = Wake::default();
        assert!(!w.observe(-30., 3., &cfg));
        assert!(!w.observe(-90., 1., &cfg));
        assert!(!w.observe(-30., 1., &cfg));
        assert!(w.observe(-30., 1., &cfg));
    }
}
