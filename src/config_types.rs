use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioAdaptiveSample {
    pub enabled: bool,
    pub failure_durations_seconds: Vec<f64>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioPickupUsage {
    pub enabled: bool,
    pub start_threshold_dbfs: f64,
    pub stop_threshold_dbfs: f64,
    pub start_confirm_seconds: f64,
    pub stop_confirm_seconds: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Audio {
    pub device_name_contains: String,
    pub sample_seconds: f64,
    pub sample_rate: f64,
    pub channels: f64,
    pub adaptive_sample: AudioAdaptiveSample,
    pub pickup_usage: AudioPickupUsage,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Image {
    pub canvas_size: f64,
    pub show_cover: bool,
    pub show_artist: bool,
    pub show_title: bool,
    pub show_album: bool,
    pub top_margin: f64,
    pub cover_size: f64,
    pub margin_image_text: f64,
    pub line_spacing_margin: f64,
    pub font_path: String,
    pub font_size: f64,
    pub use_dynamic_bg: bool,
    pub manual_bg_color: Vec<u8>,
    pub use_dynamic_text_color: bool,
    pub invert_dynamic_colors: bool,
    pub text_color: Vec<u8>,
    pub uppercase: bool,
    pub preview_scale: f64,
    pub marquee_speed: f64,
    pub sleep_seconds: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DivoomDiscovery {
    pub enabled: bool,
    pub subnet_prefix: String,
    pub ip_range_start: f64,
    pub ip_range_end: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Divoom {
    pub ip: String,
    pub device_name: String,
    pub device_id: f64,
    pub device_mac: String,
    pub timeout: f64,
    pub auto_reset_gif_id: bool,
    pub animation_mode: String,
    pub discovery: DivoomDiscovery,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Shazam {
    pub timeout_seconds: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Spotify {
    pub poll_seconds: f64,
    pub auto_sleep_enabled: bool,
    pub auto_sleep_iterations: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Discogs {
    pub enabled: bool,
    pub username: String,
    pub prefer_collection: bool,
    pub cover_source: String,
    pub sequence_matching: bool,
    pub infer_unrecognized_next: bool,
    pub vinyl_only: bool,
    pub min_match_confidence: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Debug {
    pub logs: bool,
    pub pixoo_frame_path: String,
    pub preview_path: String,
    pub wav_path: String,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fallback {
    pub enabled: bool,
    pub image_path: String,
    pub side_flip_enabled: bool,
    pub side_flip_image_path: String,
    pub allowed_failures: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Behavior {
    pub loop_delay_seconds: f64,
    pub vinyl_auto_wake_enabled: bool,
    pub vinyl_auto_wake_threshold_dbfs: f64,
    pub vinyl_auto_wake_confirm_seconds: f64,
    pub vinyl_auto_sleep_enabled: bool,
    pub vinyl_manual_shutdown_only: bool,
    pub vinyl_auto_sleep_iterations: f64,
    pub vinyl_audio_sleep_enabled: bool,
    pub vinyl_audio_sleep_threshold_dbfs: f64,
    pub vinyl_audio_sleep_confirm_seconds: f64,
    pub stats_min_consecutive: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PixooAutomations {
    pub turn_on_on_start: bool,
    pub off_action: String,
    pub stop_gif_file_id: String,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Homeassistant {
    pub use_ha: bool,
    pub base_url: String,
    pub webhook_id: String,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub audio: Audio,
    pub image: Image,
    pub divoom: Divoom,
    pub shazam: Shazam,
    pub spotify: Spotify,
    pub discogs: Discogs,
    pub debug: Debug,
    pub fallback: Fallback,
    pub behavior: Behavior,
    pub pixoo_automations: PixooAutomations,
    pub homeassistant: Homeassistant,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}
