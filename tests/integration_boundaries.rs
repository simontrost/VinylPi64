//! Boundary tests for parsing, file operations and the local Discogs library.
//! No live Spotify, Shazam, Discogs or Pixoo requests are performed in CI.
use serde_json::json;
use vinylpi64::{
    config::{ConfigStore, Config, safe_relative},
    model::{Mode, Track, canonical_title},
    uploads,
};

#[test]
fn recognition_payload_parsing_handles_missing_and_variant_metadata() {
    assert!(Track::from_shazam(&json!({})).is_none());
    assert!(Track::from_shazam(&json!({"track":{"title":"Song"}})).is_none());
    let track = Track::from_shazam(&json!({"track":{
        "title":"A Song (2011 Remaster)","subtitle":"Example Band",
        "key":"shazam-id","genres":{"primary":"Progressive Rock"},
        "images":{"coverart":"https://example.org/small.jpg","coverarthq":"https://example.org/large.jpg"},
        "sections":[{"type":"SONG","metadata":[{"title":"Album","text":"Studio album"}]}]
    }})).unwrap();
    assert_eq!(track.album.as_deref(), Some("Studio album"));
    assert_eq!(track.cover_url.as_deref(), Some("https://example.org/large.jpg"));
    assert_eq!(track.genre.as_deref(), Some("Progressive Rock"));
    assert_eq!(canonical_title(&track.title), "a song");
    assert_eq!(track.identity(), "example band\na song");
    assert_eq!(track.key(Mode::Spotify), "shazam-id");
    assert_ne!(track.key(Mode::Vinyl), track.key(Mode::Spotify));
    assert_ne!(canonical_title("A Song (Live)"), canonical_title("A Song (2011 Remaster)"));
}

#[test]
fn uploads_validate_contents_enforce_size_and_prevent_traversal() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    std::fs::create_dir_all(root.join("assets/fallback/normal")).unwrap();
    std::fs::create_dir_all(root.join("assets/fallback/turn")).unwrap();
    std::fs::create_dir_all(root.join("assets/fonts")).unwrap();
    let cfg = ConfigStore::open(root.join("config.json")).unwrap();
    assert!(uploads::upload(root, b"not a PNG", "fake.png", false, "normal").is_err());
    assert!(uploads::upload(root, &[0u8; 4 * 1024 * 1024 + 1], "big.png", false, "normal").is_err());
    assert!(uploads::upload(root, b"not a font", "fake.ttf", true, "normal").is_err());
    assert!(uploads::upload(root, b"text", "fake.gif", false, "unknown").is_err());
    assert!(!safe_relative("../outside"));
    for path in ["../secret", "/etc/passwd", "nested/../../secret", "C:/secret", "a\\b"] {
        assert!(uploads::read(root, path).is_err(), "{path}");
    }
    let png = vinylpi64::display::png(image::RgbImage::new(8, 8)).unwrap();
    let result = uploads::upload(root, &png, "cover.png", false, "normal").unwrap();
    let relative = result["path"].as_str().unwrap();
    let saved = image::load_from_memory(&std::fs::read(root.join(relative)).unwrap()).unwrap();
    assert_eq!((saved.width(), saved.height()), (64, 64));
    let listed = uploads::images(root, &cfg, "normal").unwrap();
    assert_eq!(listed["images"].as_array().unwrap().len(), 1);
    let name = relative.strip_prefix("assets/fallback/").unwrap();
    uploads::delete(root, &cfg, name, false).unwrap();
    assert!(!root.join(relative).exists());
}

#[test]
fn legacy_settings_are_normalized_without_exposing_discogs_secrets() {
    let config = Config::from_value(json!({
        "behavior":{"auto_sleep":12},
        "pixoo_automations":{"turn_on_on_vinyl_start":true,"play_gif_on_stop":true},
        "discogs":{"token":"private-secret"}
    })).unwrap();
    let public = config.public();
    assert_eq!(public["behavior"]["vinyl_auto_sleep_iterations"].as_f64(), Some(12.0));
    assert_eq!(public["pixoo_automations"]["turn_on_on_start"], true);
    assert_eq!(public["pixoo_automations"]["off_action"], "community_gif");
    assert!(public["discogs"].get("token").is_none());
    assert!(!public.to_string().contains("private-secret"));
}
