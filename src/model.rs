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
/// Strip only *explicit* edition metadata. Live albums, different mixes and
/// titles containing meaningful numbers remain distinct. Keep the original
/// spelling for display and history; use this only for album identification.
pub fn canonical_album_name(album: &str) -> String {
    static TRAILING_EDITION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)\s*(?:[-–—]\s*)?[\(\[]([^\)\]]+)[\)\]]\s*$").unwrap()
    });
    static EDITION_WORD: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)\b(?:remaster(?:ed)?|anniversary|deluxe|expanded|reissue|special edition|collector'?s? edition|bonus tracks?|explicit)\b").unwrap()
    });
    let mut name = album.trim();
    while let Some(caps) = TRAILING_EDITION.captures(name) {
        let Some(suffix) = caps.get(1) else { break };
        if !EDITION_WORD.is_match(suffix.as_str()) {
            break;
        }
        let Some(full) = caps.get(0) else { break };
        let before = name[..full.start()].trim();
        if before.is_empty() {
            break;
        }
        name = before;
    }
    name.to_owned()
}

/// Include artist to avoid merging unrelated records named "Greatest Hits".
pub fn album_identity(artist: &str, album: &str) -> String {
    let title = normalize(&canonical_album_name(album));
    if title.is_empty() {
        return String::new();
    }
    format!("{}\n{}", normalize(artist), title)
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
    #[test]
    fn album_editions_share_identity_without_conflating_other_records() {
        assert_eq!(canonical_album_name("Meddle (2016 Remaster)"), "Meddle");
        assert_eq!(canonical_album_name("Dirt (Remastered)"), "Dirt");
        assert_eq!(canonical_album_name("Wiped Out! (10th Anniversary Edition)"), "Wiped Out!");
        assert_eq!(canonical_album_name("Album (Deluxe) [Explicit]"), "Album");
        assert!(album_identity("Artist", "  ").is_empty());
        assert_eq!(canonical_album_name("Live (At Wembley)"), "Live (At Wembley)");
        assert_eq!(canonical_album_name("Wish You Were Here 50"), "Wish You Were Here 50");
        assert_eq!(album_identity("Pink Floyd", "Meddle"), album_identity("pink floyd", "Meddle (2016 Remaster)"));
        assert_ne!(album_identity("Singer A", "Greatest Hits"), album_identity("Singer B", "Greatest Hits (Remastered)"));
        assert_ne!(album_identity("Pink Floyd", "Wish You Were Here"), album_identity("Pink Floyd", "Wish You Were Here 50"));
    }
}
