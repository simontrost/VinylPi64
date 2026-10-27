use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::LazyLock;
use unicode_normalization::UnicodeNormalization;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    #[default]
    Off,
    Vinyl,
    Spotify,
}
impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Vinyl => "vinyl",
            Self::Spotify => "spotify",
        }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Track {
    pub artist: String,
    pub title: String,
    pub album: Option<String>,
    pub cover_url: Option<String>,
    pub genre: Option<String>,
    pub track_id: Option<String>,
    pub artist_id: Option<String>,
    pub duration_ms: Option<i64>,
    pub spotify_url: Option<String>,
    pub progress_ms: Option<i64>,
    #[serde(flatten)]
    pub extra: serde_json::Map<String, Value>,
}
pub fn normalize(s: &str) -> String {
    s.nfkc()
        .flat_map(char::to_lowercase)
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
pub fn canonical_title(s: &str) -> String {
    static SUFFIX: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)[\(\[][^)\]]*(?:remaster|remix|version|edit|deluxe|mono|stereo|reissue|\d{4})[^)\]]*[)\]]").unwrap()
    });
    let v = normalize(s).replace(['–', '—'], "-");
    let v = SUFFIX.replace_all(&v, "");
    normalize(v.split(" - ").next().unwrap_or(&v))
}
impl Track {
    pub fn identity(&self) -> String {
        format!(
            "{}\n{}",
            normalize(&self.artist),
            canonical_title(&self.title)
        )
    }
    pub fn key(&self, mode: Mode) -> String {
        if mode == Mode::Spotify {
            self.track_id.clone().unwrap_or_else(|| self.identity())
        } else {
            format!("{} – {}", self.artist, self.title)
        }
    }
    pub fn from_shazam(v: &Value) -> Option<Self> {
        let t = v.get("track")?;
        let title = t["title"].as_str()?.to_owned();
        let artist = t["subtitle"].as_str()?.to_owned();
        let album = t["sections"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|s| s["metadata"].as_array())
            .flatten()
            .find(|m| {
                m["title"]
                    .as_str()
                    .is_some_and(|s| s.eq_ignore_ascii_case("album"))
            })
            .and_then(|m| m["text"].as_str())
            .map(str::to_owned);
        let text = |key: &str| t.pointer(key).and_then(Value::as_str).map(str::to_owned);
        Some(Self {
            artist,
            title,
            album,
            cover_url: text("/images/coverarthq").or_else(|| text("/images/coverart")),
            genre: text("/genres/primary"),
            track_id: text("/key"),
            artist_id: text("/artists/0/adamid"),
            duration_ms: t["durationInMillis"].as_i64().or(t["duration_ms"].as_i64()),
            ..Default::default()
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn variant_identity() {
        assert_eq!(canonical_title("Song (2011 Remaster)"), "song");
        assert_ne!(canonical_title("Song (Live)"), "song");
        assert_eq!(normalize("  BÖRK  "), "börk");
    }
}
