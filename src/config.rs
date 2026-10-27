pub use crate::config_types::*;
use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Mutex,
};
use tokio::sync::watch;

impl Default for Config {
    fn default() -> Self {
        serde_json::from_str(include_str!("../config/default.json")).expect("bundled configuration")
    }
}

pub fn merge(base: &mut Value, update: Value) {
    match (base, update) {
        (Value::Object(a), Value::Object(b)) => {
            for (k, v) in b {
                merge(a.entry(k).or_insert(Value::Null), v);
            }
        }
        (a, b) => *a = b,
    }
}
impl Config {
    pub fn from_value(mut value: Value) -> Result<Self> {
        ensure!(value.is_object(), "Configuration must be an object");
        if let Some(n) = value
            .pointer("/behavior/auto_sleep")
            .and_then(Value::as_i64)
        {
            let b = value["behavior"]
                .as_object_mut()
                .context("behavior must be an object")?;
            b.entry("vinyl_auto_sleep_enabled").or_insert(json!(n > 0));
            b.entry("vinyl_auto_sleep_iterations")
                .or_insert(json!(n.max(1)));
            b.remove("auto_sleep");
        }
        if let Some(d) = value.get_mut("discogs").and_then(Value::as_object_mut) {
            d.remove("token");
            d.remove("token_configured");
        }
        let mut defaults = serde_json::to_value(Self::default())?;
        merge(&mut defaults, value);
        let cfg: Self =
            serde_json::from_value(defaults).context("Invalid configuration field type")?;
        cfg.validate()?;
        Ok(cfg)
    }
    pub fn validate(&self) -> Result<()> {
        fn range(name: &str, v: f64, min: f64, max: f64) -> Result<()> {
            ensure!(
                v.is_finite() && v >= min && v <= max,
                "{name} must be between {min} and {max}"
            );
            Ok(())
        }
        range("audio.sample_seconds", self.audio.sample_seconds, 1., 30.)?;
        ensure!(
            self.audio.pickup_usage.start_threshold_dbfs
                > self.audio.pickup_usage.stop_threshold_dbfs,
            "Pickup start threshold must exceed stop threshold"
        );
        ensure!(
            [8000., 16000., 22050., 32000., 44100., 48000., 96000.]
                .contains(&self.audio.sample_rate),
            "Unsupported sample rate"
        );
        ensure!(
            [1., 2.].contains(&self.audio.channels),
            "audio.channels must be 1 or 2"
        );
        for n in &self.audio.adaptive_sample.failure_durations_seconds {
            range("adaptive sample", *n, 1., 30.)?;
        }
        range("shazam timeout", self.shazam.timeout_seconds, 1., 60.)?;
        range("Spotify polling", self.spotify.poll_seconds, 1., 60.)?;
        range("Pixoo timeout", self.divoom.timeout, 0.1, 10.)?;
        ensure!(
            self.image.canvas_size == 64.,
            "Pixoo 64 requires a 64x64 canvas"
        );
        for (name, n, min, max) in [
            ("cover_size", self.image.cover_size, 0., 64.),
            ("font_size", self.image.font_size, 1., 32.),
            ("top_margin", self.image.top_margin, 0., 63.),
            (
                "line_spacing_margin",
                self.image.line_spacing_margin,
                0.,
                32.,
            ),
            ("margin_image_text", self.image.margin_image_text, 0., 64.),
            ("marquee_speed", self.image.marquee_speed, 1., 200.),
            ("sleep_seconds", self.image.sleep_seconds, 0.001, 5.),
            ("preview_scale", self.image.preview_scale, 1., 32.),
            ("loop delay", self.behavior.loop_delay_seconds, 0.1, 60.),
            ("min confidence", self.discogs.min_match_confidence, 0., 1.),
        ] {
            range(name, n, min, max)?;
        }
        for color in [&self.image.manual_bg_color, &self.image.text_color] {
            ensure!(color.len() == 3, "Colors require three RGB bytes");
        }
        for path in [
            &self.image.font_path,
            &self.fallback.image_path,
            &self.fallback.side_flip_image_path,
        ] {
            ensure!(
                path.is_empty() || safe_relative(path),
                "Asset path must be relative and inside assets"
            );
            ensure!(
                path.is_empty() || path.replace('\\', "/").starts_with("assets/"),
                "Asset must be inside assets/"
            );
        }
        for (name, n) in [
            ("wake", self.behavior.vinyl_auto_wake_threshold_dbfs),
            ("sleep", self.behavior.vinyl_audio_sleep_threshold_dbfs),
            ("pickup start", self.audio.pickup_usage.start_threshold_dbfs),
            ("pickup stop", self.audio.pickup_usage.stop_threshold_dbfs),
        ] {
            range(name, n, -120., 0.)?;
        }
        for n in [
            self.behavior.vinyl_auto_wake_confirm_seconds,
            self.behavior.vinyl_audio_sleep_confirm_seconds,
            self.audio.pickup_usage.start_confirm_seconds,
            self.audio.pickup_usage.stop_confirm_seconds,
        ] {
            range("confirmation duration", n, 0.1, 600.)?;
        }
        for n in [
            self.behavior.stats_min_consecutive,
            self.behavior.vinyl_auto_sleep_iterations,
            self.spotify.auto_sleep_iterations,
            self.fallback.allowed_failures,
        ] {
            range("iteration count", n, 1., 1000.)?;
            ensure!(n.fract() == 0., "Iteration count must be integral");
        }
        ensure!(
            ["none", "community_gif", "brightness_off"]
                .contains(&self.pixoo_automations.off_action.as_str()),
            "Invalid off_action"
        );
        ensure!(
            ["stream", "gif_url"].contains(&self.divoom.animation_mode.as_str()),
            "Invalid animation mode"
        );
        ensure!(
            ["shazam", "discogs"].contains(&self.discogs.cover_source.as_str()),
            "Invalid cover source"
        );
        if !self.divoom.ip.is_empty() {
            local_ip(&self.divoom.ip)?;
        }
        let discovery = &self.divoom.discovery;
        local_ip(&format!("{}1", discovery.subnet_prefix))?;
        range("IP start", discovery.ip_range_start, 1., 254.)?;
        ensure!(
            discovery.ip_range_start.fract() == 0. && discovery.ip_range_end.fract() == 0.,
            "IP range must be integral"
        );
        range(
            "IP end",
            discovery.ip_range_end,
            discovery.ip_range_start,
            254.,
        )?;
        if !self.homeassistant.base_url.is_empty() {
            let u = url::Url::parse(&self.homeassistant.base_url)?;
            ensure!(
                ["http", "https"].contains(&u.scheme())
                    && u.host_str().is_some()
                    && u.username().is_empty(),
                "Invalid Home Assistant URL"
            );
        }
        Ok(())
    }
    pub fn public(&self) -> Value {
        let mut v = serde_json::to_value(self).expect("serializable config");
        v["discogs"]["token_configured"] = json!(
            !std::env::var("DISCOGS_API_TOKEN")
                .unwrap_or_default()
                .trim()
                .is_empty()
        );
        v
    }
}
pub fn local_ip(s: &str) -> Result<std::net::Ipv4Addr> {
    let ip = s.parse::<std::net::Ipv4Addr>()?;
    ensure!(
        ip.is_private() || ip.is_link_local(),
        "Expected private LAN IPv4 address"
    );
    Ok(ip)
}
pub fn safe_relative(s: &str) -> bool {
    !s.is_empty()
        && !s.contains(['\\', ':', '\0'])
        && Path::new(s)
            .components()
            .all(|c| matches!(c, std::path::Component::Normal(_)))
}
pub fn atomic_write(path: &Path, data: &[u8]) -> Result<()> {
    use std::io::Write;
    let parent = path.parent().context("Missing parent directory")?;
    fs::create_dir_all(parent)?;
    let mut f = tempfile::NamedTempFile::new_in(parent)?;
    f.write_all(data)?;
    f.as_file().sync_all()?;
    f.persist(path).map_err(|e| e.error)?;
    #[cfg(unix)]
    fs::File::open(parent)?.sync_all()?;
    Ok(())
}
pub struct ConfigStore {
    path: PathBuf,
    lock: Mutex<()>,
    pub tx: watch::Sender<Config>,
}
impl ConfigStore {
    pub fn open(path: PathBuf) -> Result<Self> {
        let cfg = if path.exists() {
            Config::from_value(serde_json::from_slice(&fs::read(&path)?)?)?
        } else {
            Config::default()
        };
        let (tx, _) = watch::channel(cfg);
        Ok(Self {
            path,
            lock: Mutex::new(()),
            tx,
        })
    }
    pub fn get(&self) -> Config {
        self.tx.borrow().clone()
    }
    pub fn update(&self, v: Value, reset: bool) -> Result<Config> {
        let _guard = self
            .lock
            .lock()
            .map_err(|_| anyhow::anyhow!("Configuration lock poisoned"))?;
        let mut old = serde_json::to_value(if reset { Config::default() } else { self.get() })?;
        if !v.is_object() {
            bail!("Configuration update must be an object")
        };
        merge(&mut old, v);
        let cfg = Config::from_value(old)?;
        atomic_write(&self.path, &serde_json::to_vec_pretty(&cfg)?)?;
        self.tx.send_replace(cfg.clone());
        Ok(cfg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_invalid_values_and_paths() {
        for v in [
            json!({"audio":{"channels":0}}),
            json!({"audio":{"sample_rate":123}}),
            json!({"image":{"text_color":[1,2]}}),
            json!({"image":{"font_path":"../x"}}),
            json!({"divoom":{"ip":"8.8.8.8"}}),
            json!({"spotify":{"poll_seconds":0}}),
        ] {
            assert!(Config::from_value(v).is_err());
        }
    }
    #[test]
    fn scroll_speed_matches_the_dashboard_range() {
        assert!(Config::from_value(json!({"image":{"marquee_speed":200}})).is_ok());
        assert!(Config::from_value(json!({"image":{"marquee_speed":201}})).is_err());
    }
    #[test]
    fn legacy_sleep_and_secret_cleanup() {
        let c =
            Config::from_value(json!({"behavior":{"auto_sleep":0},"discogs":{"token":"secret"}}))
                .unwrap();
        assert!(!c.behavior.vinyl_auto_sleep_enabled);
        assert!(!c.public().to_string().contains("secret"));
    }
    #[test]
    fn preserves_partial_concurrent_updates() {
        let d = tempfile::tempdir().unwrap();
        let c = std::sync::Arc::new(ConfigStore::open(d.path().join("config.json")).unwrap());
        std::thread::scope(|s| {
            for (k, v) in [("show_artist", false), ("show_title", false)] {
                let c = c.clone();
                s.spawn(move || {
                    c.update(json!({"image":{k:v}}), false).unwrap();
                });
            }
        });
        assert!(!c.get().image.show_artist && !c.get().image.show_title);
    }
}
