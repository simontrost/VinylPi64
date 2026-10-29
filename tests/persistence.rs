//! Persistence invariants independent of the HTTP server and real hardware.
use serde_json::json;
use chrono::Datelike;
use vinylpi64::{db::{Db, snapshot}, model::{Mode, Track}};

fn song(id: &str, album: &str, cover: Option<&str>) -> Track {
    Track {
        artist: "Example artist".into(), title: id.into(), album: Some(album.into()),
        cover_url: cover.map(str::to_owned), genre: Some("Rock".into()),
        track_id: Some(format!("spotify-{id}")), ..Default::default()
    }
}

#[test]
fn play_counts_album_sessions_and_listening_time_persist_across_restarts() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("library.db");
    {
        let db = Db::open(&path).unwrap();
        let t = song("Song A", "Album A", Some("https://example.org/a.jpg"));
        db.record_play(Mode::Vinyl, &t, true).unwrap();
        db.record_play(Mode::Vinyl, &t, false).unwrap();
        db.seconds(Mode::Vinyl, Some(&t.key(Mode::Vinyl)), 120., false).unwrap();
        db.seconds(Mode::Vinyl, None, 30., true).unwrap();
        assert!(db.record_play(Mode::Off, &t, true).is_err());
        for invalid in [f64::NAN, -1., 1800.1, f64::INFINITY] {
            assert!(db.seconds(Mode::Vinyl, None, invalid, false).is_err());
        }
    }
    let db = Db::open(&path).unwrap();
    let stats = db.stats("vinyl", None).unwrap();
    assert_eq!(stats["top_songs"][0]["count"], 2);
    assert_eq!(stats["top_albums"][0]["count"], 1);
    assert_eq!(stats["total_minutes_listened"], 2);
    assert_eq!(stats["pickup_usage_seconds"], 30.);
    assert_eq!(db.query("SELECT COUNT(*) n FROM playback_events WHERE event_type='play'", []).unwrap()[0]["n"], 2);
    assert!(db.stats("invalid", None).is_err());
}

#[test]
fn sources_are_isolated_even_for_identical_artist_and_title() {
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("database.sqlite")).unwrap();
    let t = song("Same title", "Vinyl album", Some("https://example.org/vinyl.png"));
    let mut spotify = t.clone();
    spotify.album = Some("Streaming album".into());
    db.record_play(Mode::Vinyl, &t, true).unwrap();
    db.record_play(Mode::Spotify, &spotify, false).unwrap();
    db.record_play(Mode::Spotify, &spotify, false).unwrap();
    let vinyl = db.stats("vinyl", None).unwrap();
    let streaming = db.stats("spotify", None).unwrap();
    let combined = db.stats("combined", None).unwrap();
    assert_eq!(vinyl["top_songs"][0]["count"], 1);
    assert_eq!(streaming["top_songs"][0]["count"], 2);
    assert_eq!(combined["top_songs"][0]["count"], 3);
    assert_eq!(vinyl["album_count_unit"], "session");
    assert_eq!(streaming["album_count_unit"], "listen");
}

#[test]
fn last_tracks_are_source_specific_and_restore_missing_artwork_from_history() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db.sqlite");
    {
        let db = Db::open(&path).unwrap();
        let vinyl = song("Vinyl track", "Album", Some("https://example.org/cover.jpg"));
        db.record_play(Mode::Vinyl, &vinyl, true).unwrap();
        db.save_status(Mode::Vinyl, &json!({"artist":vinyl.artist,"title":vinyl.title,"source":"vinyl","is_playing":true})).unwrap();
        let stream = song("Spotify track", "Online", None);
        db.save_status(Mode::Spotify, &json!({"artist":stream.artist,"title":stream.title})).unwrap();
        db.record_play(Mode::Spotify, &stream, false).unwrap();
    }
    let db = Db::open(&path).unwrap();
    assert!(db.last_status(Mode::Off).unwrap().is_none());
    let last_vinyl = db.last_status(Mode::Vinyl).unwrap().unwrap();
    let last_spotify = db.last_status(Mode::Spotify).unwrap().unwrap();
    assert_eq!(last_vinyl["cover_url"], "https://example.org/cover.jpg");
    assert_eq!(last_vinyl["album"], "Album");
    assert_eq!(last_spotify["title"], "Spotify track");
    assert_ne!(last_vinyl["title"], last_spotify["title"]);
    // Merely restoring the dashboard must never count as a new play.
    assert_eq!(db.query("SELECT COUNT(*) n FROM playback_events WHERE event_type='play'", []).unwrap()[0]["n"], 2);
}

#[test]
fn cache_expiry_and_replacement_are_respected() {
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("db.sqlite")).unwrap();
    db.put_cache("valid", &json!({"version":1}), 300).unwrap();
    assert_eq!(db.cache("valid").unwrap().unwrap()["version"], 1);
    db.put_cache("valid", &json!({"version":2}), 300).unwrap();
    assert_eq!(db.cache("valid").unwrap().unwrap()["version"], 2);
    db.put_cache("expired", &json!({"version":0}), -1).unwrap();
    assert!(db.cache("expired").unwrap().is_none());
}

#[test]
fn sqlite_snapshot_contains_committed_wal_data_and_is_independent() {
    let dir = tempfile::tempdir().unwrap();
    let live = dir.path().join("live.sqlite");
    let backup = dir.path().join("snapshot.sqlite");
    let db = Db::open(&live).unwrap();
    db.record_play(Mode::Vinyl, &song("Before", "Record", None), true).unwrap();
    snapshot(&live, &backup).unwrap();
    db.record_play(Mode::Vinyl, &song("After", "Record", None), false).unwrap();
    let copied = Db::open(&backup).unwrap();
    assert_eq!(copied.query("SELECT COUNT(*) n FROM songs", []).unwrap()[0]["n"], 1);
    assert_eq!(db.query("SELECT COUNT(*) n FROM songs", []).unwrap()[0]["n"], 2);
    assert_eq!(copied.query("PRAGMA integrity_check", []).unwrap()[0]["integrity_check"], "ok");
}

#[test]
fn album_editions_share_a_statistic_without_rewriting_historical_events() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("albums.sqlite");
    let db = Db::open(&path).unwrap();
    let original = Track { artist: "Pink Floyd".into(), title: "One of These Days".into(),
        album: Some("Meddle (2016 Remaster)".into()),
        cover_url: Some("https://example.org/meddle.jpg".into()), ..Default::default() };
    let current = Track { title: "Fearless".into(), album: Some("Meddle".into()), ..original.clone() };
    for _ in 0..5 {
        db.record_play(Mode::Vinyl, &original, true).unwrap();
    }
    db.record_play(Mode::Vinyl, &current, true).unwrap();
    // Source history remains unmodified, while the public ranking merges aliases.
    let history = db.query("SELECT album,count FROM yearly_albums WHERE source='vinyl' ORDER BY album", []).unwrap();
    assert_eq!(history.len(), 2);
    assert_eq!(db.query("SELECT COUNT(*) n FROM playback_events WHERE event_type='album_session'", []).unwrap()[0]["n"], 6);
    let stat = db.stats("vinyl", None).unwrap();
    assert_eq!(stat["top_albums"].as_array().unwrap().len(), 1);
    assert_eq!(stat["top_albums"][0]["name"], "Meddle");
    assert_eq!(stat["top_albums"][0]["count"], 6);
    assert_eq!(stat["top_album_covers"][0]["cover_url"], "https://example.org/meddle.jpg");
    drop(db);
    let db = Db::open(&path).unwrap();
    assert_eq!(db.stats("vinyl", None).unwrap()["top_albums"][0]["count"], 6);
}

#[test]
fn album_ranking_preserves_artists_source_and_year_and_real_other_editions() {
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("albums.sqlite")).unwrap();
    let a = song("A", "Greatest Hits (Remastered)", None);
    let mut other_artist = song("B", "Greatest Hits", None);
    other_artist.artist = "Another artist".into();
    db.record_play(Mode::Vinyl, &a, true).unwrap();
    db.record_play(Mode::Vinyl, &other_artist, true).unwrap();
    let albums = db.stats("vinyl", None).unwrap();
    assert_eq!(albums["top_albums"].as_array().unwrap().len(), 2);
    let spotify = song("C", "Greatest Hits (Deluxe)", None);
    db.record_play(Mode::Spotify, &spotify, false).unwrap();
    assert_eq!(db.stats("spotify", None).unwrap()["top_albums"][0]["count"], 1);
    assert_eq!(db.stats("combined", None).unwrap()["top_albums"].as_array().unwrap().len(), 2);
    let year = chrono::Local::now().year();
    assert_eq!(db.stats("vinyl", Some(year)).unwrap()["top_albums"].as_array().unwrap().len(), 2);
    assert!(db.stats("vinyl", Some(year + 1)).unwrap()["top_albums"].as_array().unwrap().is_empty());
}
