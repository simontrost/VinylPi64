use crate::{
    audio,
    config::{Config, ConfigStore},
    db::Db,
    discogs::Discogs,
    display::{Content, Display},
    metadata::Metadata,
    model::{Mode, Track, normalize},
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
    Observation(Result<Observation>),
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
#[derive(Default)]
struct Confirmation {
    candidate: String,
    consecutive: usize,
    counted: String,
    album: String,
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
        let album = t.album.as_deref().map(normalize).unwrap_or_default();
        let new_album = count && !album.is_empty() && self.album != album;
        if count {
            self.counted = id;
            if new_album {
                self.album = album
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
    fn waiting(&self, mode: Mode) {
        self.status.send_replace(json!({"source":mode,"artist":"","title":match mode{Mode::Off=>"Recognition off",Mode::Vinyl=>"Waiting for vinyl…",Mode::Spotify=>"Waiting for Spotify…"},"updated_at":chrono::Utc::now().timestamp_millis(),"bg_color":[0,0,0]}));
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
            s.spotify.current().await?;
        }
        if mode == Mode::Vinyl {
            audio::devices()?;
        }
        let cfg = s.config.get();
        let old = self.get_mode();
        self.mode.send_replace(mode);
        self.waiting(mode);
        s.display.show(Content::Fallback(false));
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
                let audio_cfg = cfg.audio.clone();
                let samples = tokio::task::spawn_blocking(move || {
                    audio::capture(&audio_cfg, seconds, &operation_cancel)
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
            let event = tokio::select! {biased; _=cancel.cancelled()=>EngineEvent::Stop,command=commands.recv()=>EngineEvent::Command(command),result=operation=>EngineEvent::Observation(result)};
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
                        wake = Wake::default();
                        next = tokio::time::Instant::now() + Duration::from_millis(50);
                    }
                    let _ = command.reply.send(result);
                }
                EngineEvent::Observation(result) => {
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
                            s.db.log(
                                "WARNING",
                                &format!(
                                    "{} input unavailable; retry in {delay}s: {e}",
                                    mode.as_str()
                                ),
                            );
                            let mut status = self.status.borrow().clone();
                            status["error"] = json!(e.to_string());
                            status["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
                            self.status.send_replace(status);
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
                                let (count, new_album) = confirmation.observe(
                                    &t,
                                    if mode == Mode::Spotify {
                                        1
                                    } else {
                                        cfg.behavior.stats_min_consecutive as usize
                                    },
                                );
                                if count {
                                    if let Err(e) = s.db.record_play(mode, &t, new_album) {
                                        s.db.log("ERROR", &format!("Statistics write failed: {e}"));
                                        confirmation.counted.clear();
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
                                v["bg_color"] = json!([30, 30, 30]);
                                if let Err(e) = s.db.save_status(mode, &v) {
                                    s.db.log("ERROR", &e.to_string());
                                }
                                self.status.send_replace(v);
                                if changed || display_fallback {
                                    s.display.show(Content::Track(Box::new(t.clone())));
                                    display_fallback = false;
                                }
                                last = Some(t);
                            } else {
                                failures += 1;
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
                                    let _ = self.change(Mode::Off, &s).await;
                                    wake = Wake::default();
                                    confirmation = Confirmation::default();
                                    last = None;
                                } else {
                                    let mut v = self.status.borrow().clone();
                                    v["is_playing"] = json!(false);
                                    let active_flip = failures >= cfg.fallback.allowed_failures as usize
                                        && flip.is_some();
                                    v["side_flip_prompt_active"] = json!(active_flip);
                                    if active_flip {
                                        let side = flip.as_deref().unwrap_or_default();
                                        v["side_flip_from_side"] = last.as_ref()
                                            .and_then(|t| t.extra.get("discogs_side"))
                                            .cloned().unwrap_or(Value::Null);
                                        v["side_flip_to_side"] = json!(side);
                                        v["side_flip_next_title"] = last.as_ref()
                                            .and_then(|t| t.extra.get("discogs_expected_next_title"))
                                            .cloned().unwrap_or(Value::Null);
                                        v["side_flip_next_position"] = last.as_ref()
                                            .and_then(|t| t.extra.get("discogs_expected_next_position"))
                                            .cloned().unwrap_or(Value::Null);
                                    }
                                    v["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
                                    if failures == cfg.fallback.allowed_failures as usize
                                        && mode == Mode::Vinyl
                                        && let Err(e) = s.db.save_status(mode, &v)
                                    {
                                        s.db.log("WARNING", &format!("Saving fallback status failed: {e}"));
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
        assert_eq!(c.observe(&track("one"), 2), (true, true));
        c.failure();
        c.observe(&track("one"), 2);
        assert!(!c.observe(&track("one"), 2).0);
        c.observe(&track("two"), 2);
        assert_eq!(c.observe(&track("two"), 2), (true, false));
        c.observe(&track("one"), 2);
        assert!(c.observe(&track("one"), 2).0);
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
