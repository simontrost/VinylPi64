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

#[test]
fn deleting_false_recognition_recalculates_artist_totals_and_yearly_counts() {
    use vinylpi64::stats_search::{search, DeleteEntry};
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("database.db")).unwrap();
    let wrong = Track { artist:"One Artist".into(), title:"Wrong Match".into(), album:Some("Record".into()), ..Default::default() };
    let correct = Track { artist:"One Artist".into(), title:"Correct Match".into(), album:Some("Record".into()), ..Default::default() };
    db.record_play(Mode::Vinyl, &wrong, true).unwrap();
    db.record_play(Mode::Vinyl, &correct, false).unwrap();
    db.record_play(Mode::Vinyl, &correct, false).unwrap();
    db.seconds(Mode::Vinyl, Some(&wrong.key(Mode::Vinyl)), 12., false).unwrap();
    db.seconds(Mode::Vinyl, Some(&correct.key(Mode::Vinyl)), 24., false).unwrap();
    let entries = search(&db,"wrong", "vinyl", None,"song",0,30).unwrap()["items"][0]["delete_entries"].clone();
    let entries: Vec<DeleteEntry> = serde_json::from_value(entries).unwrap();
    let out = db.delete_song_history(&entries).unwrap();
    assert_eq!(out["removed_plays"],1);
    let remaining = db.stats("vinyl",None).unwrap();
    assert_eq!(remaining["top_songs"][0]["count"],2);
    assert_eq!(remaining["top_artists"][0]["count"],2);
    assert_eq!(remaining["total_minutes_listened"],0); // 24 seconds rounds to zero minutes.
    assert_eq!(db.query("SELECT play_count FROM artist_totals WHERE artist='One Artist'",[]).unwrap()[0]["play_count"],2);
    assert_eq!(db.query("SELECT COUNT(*) n FROM playback_events WHERE event_type='play'",[]).unwrap()[0]["n"],2);
    assert_eq!(db.query("SELECT COUNT(*) n FROM yearly_song_seconds WHERE song_key=?", [&wrong.key(Mode::Vinyl)]).unwrap()[0]["n"],0);
    // A second deletion fails without modifying the remaining history.
    assert!(db.delete_song_history(&entries).is_err());
    assert_eq!(db.stats("vinyl",None).unwrap()["top_artists"][0]["count"],2);
    // The remaining song belongs to the same album; the album session remains valid.
    assert_eq!(db.stats("vinyl",None).unwrap()["top_albums"][0]["count"],1);
}

#[test]
fn deleting_last_artist_and_combined_song_keeps_discogs_and_other_source_isolated() {
    use vinylpi64::stats_search::{search, DeleteEntry};
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("database.db")).unwrap();
    let mut track = Track { artist:"Only Artist".into(), title:"Bad Song".into(), album:Some("Discogs Album".into()), track_id:Some("spotify-track".into()), ..Default::default() };
    db.with(|c| {
        c.execute("INSERT INTO discogs_releases(release_id,title,artist) VALUES (88,'Discogs Album','Only Artist')",[])?;
        c.execute("INSERT INTO discogs_tracks(release_id,track_index,title,artist,normalized_title,normalized_artist) VALUES(88,1,'Bad Song','Only Artist','bad song','only artist')",[])?;
        Ok(())
    }).unwrap();
    db.record_play(Mode::Vinyl,&track,true).unwrap();
    db.record_play(Mode::Spotify,&track,false).unwrap();
    let entries: Vec<DeleteEntry> = serde_json::from_value(search(&db,"bad song","vinyl",None,"song",0,30).unwrap()["items"][0]["delete_entries"].clone()).unwrap();
    db.delete_song_history(&entries).unwrap();
    assert_eq!(db.stats("vinyl",None).unwrap()["top_artists"],json!([]));
    assert_eq!(db.stats("spotify",None).unwrap()["top_songs"][0]["count"],1);
    assert_eq!(search(&db,"bad song","vinyl",None,"song",0,30).unwrap()["items"][0]["in_collection"],true);
    assert_eq!(search(&db,"bad song","vinyl",None,"song",0,30).unwrap()["items"][0]["count"],0);
    assert_eq!(search(&db,"bad song","vinyl",None,"song",0,30).unwrap()["items"][0]["delete_entries"],json!([]));
    let spotify_entries: Vec<DeleteEntry> = serde_json::from_value(search(&db,"bad song","spotify",None,"song",0,30).unwrap()["items"][0]["delete_entries"].clone()).unwrap();
    db.delete_song_history(&spotify_entries).unwrap();
    assert_eq!(db.stats("spotify",None).unwrap()["top_artists"],json!([]));
    assert!(db.query("SELECT * FROM spotify_album_totals",[]).unwrap().is_empty());
    assert_eq!(db.query("SELECT COUNT(*) n FROM discogs_tracks",[]).unwrap()[0]["n"],1);
    track.title = "Unrelated".into();
    db.record_play(Mode::Spotify,&track,false).unwrap();
    assert_eq!(db.stats("spotify",None).unwrap()["top_songs"][0]["count"],1);
}

#[test]
fn deleting_combined_selection_is_atomic_when_any_key_is_invalid() {
    use vinylpi64::stats_search::{search, DeleteEntry};
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("database.db")).unwrap();
    let track = Track { artist:"Group".into(), title:"Same Track".into(), track_id:Some("stream-1".into()), ..Default::default() };
    db.record_play(Mode::Vinyl,&track,false).unwrap();
    db.record_play(Mode::Spotify,&track,false).unwrap();
    let entries: Vec<DeleteEntry> = serde_json::from_value(search(&db,"same track","combined",None,"song",0,30).unwrap()["items"][0]["delete_entries"].clone()).unwrap();
    assert_eq!(entries.len(),2);
    let invalid = vec![entries[0].clone(), DeleteEntry { source:"spotify".into(), song_key:"missing".into() }];
    assert!(db.delete_song_history(&invalid).is_err());
    assert_eq!(db.stats("combined",None).unwrap()["top_songs"][0]["count"],2);
    db.delete_song_history(&entries).unwrap();
    assert_eq!(db.stats("combined",None).unwrap()["top_songs"],json!([]));
    assert!(db.query("SELECT * FROM yearly_plays",[]).unwrap().is_empty());
}

#[test]
fn reducing_vinyl_play_count_reconciles_events_yearly_minutes_and_album_session() {
    use vinylpi64::stats_search::{search, ReduceRequest};
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("edit.db")).unwrap();
    let t = song("Overcounted", "Album A", Some("https://example.org/a.jpg"));
    for i in 0..3 { db.record_play(Mode::Vinyl, &t, i == 0).unwrap(); }
    db.seconds(Mode::Vinyl, Some(&t.key(Mode::Vinyl)), 180., false).unwrap();
    db.seconds(Mode::Vinyl, None, 50., true).unwrap();
    let entries = search(&db, "overcounted", "vinyl", None, "song", 0, 30).unwrap()["items"][0]["delete_entries"].clone();
    let request = ReduceRequest { entries: serde_json::from_value(entries).unwrap(), expected_count: 3, new_count: 1, year: None };
    let result = db.reduce_song_history(&request).unwrap();
    assert_eq!(result["removed_plays"], 2);
    assert_eq!(db.stats("vinyl", None).unwrap()["top_songs"][0]["count"], 1);
    assert_eq!(db.stats("vinyl", None).unwrap()["top_artists"][0]["count"], 1);
    assert_eq!(db.stats("vinyl", None).unwrap()["top_albums"][0]["count"], 1); // sessions are independent
    assert_eq!(db.stats("vinyl", None).unwrap()["total_minutes_listened"], 1);
    assert_eq!(db.stats("vinyl", None).unwrap()["pickup_usage_seconds"], 50.);
    let seconds = db.query("SELECT measured_listen_seconds FROM songs WHERE song_key=?", [&t.key(Mode::Vinyl)]).unwrap();
    assert!((seconds[0]["measured_listen_seconds"].as_f64().unwrap() - 60.).abs() < 0.00001);
    let year = chrono::Local::now().year();
    assert_eq!(db.stats("vinyl", Some(year)).unwrap()["top_songs"][0]["count"], 1);
    assert_eq!(db.query("SELECT COUNT(*) n FROM playback_events WHERE event_type='play'", []).unwrap()[0]["n"], 1);
    assert_eq!(db.recent_plays("vinyl", 0, 40).unwrap()["items"].as_array().unwrap().len(), 1);
    assert!(db.reduce_song_history(&request).is_err()); // stale form rejected
    assert_eq!(db.stats("vinyl", None).unwrap()["top_songs"][0]["count"], 1);
}

#[test]
fn reducing_spotify_and_combined_counts_keeps_sources_isolated_and_never_increases() {
    use vinylpi64::stats_search::{search, DeleteEntry, ReduceRequest};
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("edit.db")).unwrap();
    let t = song("Same song", "Shared album", None);
    db.record_play(Mode::Vinyl, &t, true).unwrap();
    db.record_play(Mode::Spotify, &t, false).unwrap();
    db.record_play(Mode::Spotify, &t, false).unwrap();
    db.seconds(Mode::Spotify, Some(&t.key(Mode::Spotify)), 120., false).unwrap();
    let entries = search(&db, "same song", "spotify", None, "song", 0, 30).unwrap()["items"][0]["delete_entries"].clone();
    let entries: Vec<DeleteEntry> = serde_json::from_value(entries).unwrap();
    assert!(db.reduce_song_history(&ReduceRequest { entries: entries.clone(), expected_count: 2, new_count: 3, year: None }).is_err());
    assert!(db.reduce_song_history(&ReduceRequest { entries: entries.clone(), expected_count: 2, new_count: -1, year: None }).is_err());
    assert!(db.reduce_song_history(&ReduceRequest { entries: entries.clone(), expected_count: 4, new_count: 1, year: None }).is_err());
    db.reduce_song_history(&ReduceRequest { entries, expected_count: 2, new_count: 1, year: None }).unwrap();
    assert_eq!(db.stats("vinyl", None).unwrap()["top_songs"][0]["count"], 1);
    assert_eq!(db.stats("spotify", None).unwrap()["top_songs"][0]["count"], 1);
    assert_eq!(db.stats("spotify", None).unwrap()["top_albums"][0]["count"], 1);
    assert_eq!(db.stats("spotify", None).unwrap()["total_minutes_listened"], 1);
    assert_eq!(db.stats("combined", None).unwrap()["top_songs"][0]["count"], 2);
    assert_eq!(db.recent_plays("combined", 0, 2).unwrap()["items"].as_array().unwrap().len(), 2);
    assert!(!db.recent_plays("combined", 0, 2).unwrap()["has_more"].as_bool().unwrap());
    assert_eq!(db.recent_plays("combined", 0, 1).unwrap()["has_more"], true);
    assert_eq!(db.recent_plays("spotify", 0, 40).unwrap()["items"].as_array().unwrap().len(), 1);
}

#[test]
fn reducing_a_selected_year_only_changes_that_year_and_newest_playback_events() {
    use vinylpi64::stats_search::{search, ReduceRequest};
    let dir = tempfile::tempdir().unwrap();
    let db = Db::open(&dir.path().join("by_year.db")).unwrap();
    let t = song("Yearly song", "Yearly album", None);
    let year = chrono::Local::now().year();
    let older = year - 1;
    for _ in 0..3 { db.record_play(Mode::Vinyl, &t, false).unwrap(); }
    db.seconds(Mode::Vinyl, Some(&t.key(Mode::Vinyl)), 90., false).unwrap();
    // Move one historical aggregate, its measured listening seconds and one
    // event to the previous year while retaining the lifetime counter.
    db.with(|c| {
        c.execute("UPDATE yearly_plays SET count=2 WHERE source='vinyl' AND song_key=? AND year=?", rusqlite::params![t.key(Mode::Vinyl),year])?;
        c.execute("INSERT INTO yearly_plays(source,year,song_key,artist,title,album,count) VALUES('vinyl',?,?,?,?,?,1)",
            rusqlite::params![older,t.key(Mode::Vinyl),t.artist,t.title,t.album])?;
        c.execute("UPDATE yearly_song_seconds SET seconds=60 WHERE source='vinyl' AND song_key=? AND year=?", rusqlite::params![t.key(Mode::Vinyl),year])?;
        c.execute("INSERT INTO yearly_song_seconds(source,year,song_key,seconds) VALUES('vinyl',?,?,30)", rusqlite::params![older,t.key(Mode::Vinyl)])?;
        c.execute("UPDATE yearly_usage SET seconds=60 WHERE source='vinyl' AND kind='listening' AND year=?",[year])?;
        c.execute("INSERT INTO yearly_usage(source,year,kind,seconds) VALUES('vinyl',?,'listening',30)",[older])?;
        c.execute("UPDATE playback_events SET occurred_at=strftime('%s',? || '-06-15 12:00:00') WHERE id=(SELECT MIN(id) FROM playback_events WHERE source='vinyl' AND event_type='play')",[older.to_string()])?;
        Ok(())
    }).unwrap();
    let entries = search(&db, "yearly song", "vinyl", Some(year), "song", 0, 30).unwrap()["items"][0]["delete_entries"].clone();
    db.reduce_song_history(&ReduceRequest { entries: serde_json::from_value(entries).unwrap(), expected_count: 2, new_count: 1, year: Some(year) }).unwrap();
    assert_eq!(db.stats("vinyl", Some(year)).unwrap()["top_songs"][0]["count"], 1);
    assert_eq!(db.stats("vinyl", Some(older)).unwrap()["top_songs"][0]["count"], 1);
    assert_eq!(db.stats("vinyl", None).unwrap()["top_songs"][0]["count"], 2);
    assert_eq!(db.query("SELECT COUNT(*) n FROM playback_events WHERE source='vinyl' AND event_type='play'", []).unwrap()[0]["n"], 2);
    assert_eq!(db.query("PRAGMA integrity_check",[]).unwrap()[0]["integrity_check"], "ok");
}
