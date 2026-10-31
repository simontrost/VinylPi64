//! JSON-only import into an empty staging database. Never merges user counters.
use crate::db::Db;
use anyhow::{Context, Result, ensure};
use rusqlite::params;
use serde_json::Value;
use sha2::{Digest, Sha256};

pub fn import(db: &Db, raw: &str) -> Result<()> {
    let v: Value = serde_json::from_str(raw)?;
    ensure!(v.is_object(), "Legacy statistics must be an object");
    let object = |key: &str| -> Result<serde_json::Map<String, Value>> {
        match v.get(key) {
            None | Some(Value::Null) => Ok(Default::default()),
            Some(Value::Object(m)) => Ok(m.clone()),
            _ => anyhow::bail!("Legacy {key} must be an object"),
        }
    };
    let songs = object("songs")?;
    let artists = object("artists")?;
    let albums = object("albums")?;
    let covers = object("album_covers")?;
    let durations = object("durations_cache")?;
    let tags = object("tag_cache")?;
    let count = |v: &Value| -> Result<i64> {
        let n = if v.is_null() {
            0
        } else {
            v.as_i64().context("Invalid legacy counter")?
        };
        ensure!(n >= 0, "Negative legacy counter");
        Ok(n)
    };
    db.with(|connection| {
        let tx = connection.transaction()?;
        let existing: i64 = tx.query_row("SELECT COUNT(*) FROM songs", [], |row| row.get(0))?;
        ensure!(
            existing == 0,
            "JSON import requires an empty statistics database"
        );

        for (key, song) in &songs {
            let artist = song["artist"].as_str().context("Song missing artist")?;
            let title = song["title"].as_str().context("Song missing title")?;
            tx.execute(
                "INSERT INTO songs(song_key,artist,title,album,cover_url,genre,genre_source,shazam_track_id,shazam_artist_id,play_count,duration_ms,duration_minutes,duration_source,measured_listen_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                params![
                    key,
                    artist,
                    title,
                    song["album"].as_str(),
                    song["cover_url"].as_str(),
                    song["genre"].as_str(),
                    song["genre_source"].as_str(),
                    song["shazam_track_id"].as_str(),
                    song["shazam_artist_id"].as_str(),
                    count(&song["count"])?,
                    song["duration_ms"].as_i64(),
                    song["duration_minutes"].as_f64(),
                    song["duration_source"].as_str(),
                    song["measured_listen_seconds"].as_f64(),
                ],
            )?;
        }
        if artists.is_empty() {
            tx.execute(
                "INSERT INTO artist_totals(artist,play_count) SELECT artist,SUM(play_count) FROM songs GROUP BY artist",
                [],
            )?;
        } else {
            for (artist, plays) in &artists {
                tx.execute(
                    "INSERT INTO artist_totals(artist,play_count) VALUES(?,?)",
                    params![artist, count(plays)?],
                )?;
            }
        }
        for (album, sessions) in &albums {
            tx.execute(
                "INSERT INTO album_sessions(album,session_count) VALUES(?,?)",
                params![album, count(sessions)?],
            )?;
        }
        for (key, table) in [
            ("listening", "listening_totals"),
            ("pickup_usage", "pickup_usage_totals"),
        ] {
            let seconds = v[key]["total_seconds"].as_f64().unwrap_or(0.);
            ensure!(
                seconds.is_finite() && seconds >= 0.,
                "Invalid legacy listening total"
            );
            tx.execute(
                &format!("UPDATE {table} SET total_seconds=? WHERE id=1"),
                [seconds],
            )?;
        }
        for (album, cover) in &covers {
            tx.execute(
                "INSERT INTO album_covers(album,artist,play_count,mbid,cover_url) VALUES(?,?,?,?,?)",
                params![
                    album,
                    cover["artist"].as_str(),
                    count(&cover["count"])?,
                    cover["mbid"].as_str(),
                    cover["cover_url"].as_str(),
                ],
            )?;
        }
        for (key, duration) in &durations {
            tx.execute(
                "INSERT INTO duration_cache(cache_key,artist,title,album,duration_ms,duration_minutes,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
                params![
                    key,
                    duration["artist"].as_str().unwrap_or(""),
                    duration["title"].as_str().unwrap_or(""),
                    duration["album"].as_str(),
                    duration["ms"].as_i64().context("Legacy duration missing ms")?,
                    duration["minutes"]
                        .as_f64()
                        .context("Legacy duration missing minutes")?,
                    duration["source"].as_str(),
                    duration["ts"].as_i64(),
                ],
            )?;
        }
        for (key, tag) in &tags {
            ensure!(tag["tags"].is_array(), "Invalid legacy genre cache");
            tx.execute(
                "INSERT INTO tag_cache(cache_key,artist,title,tags_json,fetched_at) VALUES(?,?,?,?,?)",
                params![
                    key,
                    tag["artist"].as_str().unwrap_or(""),
                    tag["title"].as_str().unwrap_or(""),
                    tag["tags"].to_string(),
                    tag["ts"].as_i64(),
                ],
            )?;
        }

        let digest = format!("{:x}", Sha256::digest(raw.as_bytes()));
        tx.execute(
            "INSERT INTO legacy_imports(source_name,source_sha256,raw_json) VALUES('stats.json',?,?)",
            params![digest, raw],
        )?;
        tx.execute_batch(
            "DELETE FROM meta WHERE key='annual_seed_vinyl_v1';
             DELETE FROM yearly_plays WHERE source='vinyl';
             DELETE FROM yearly_albums WHERE source='vinyl';
             DELETE FROM yearly_usage WHERE source='vinyl';",
        )?;
        tx.commit()?;
        Ok(())
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn json_import_preserves_counts_and_raw_backup() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("db");
        {
            let db = Db::open(&p).unwrap();
            import(&db,r#"{"songs":{"a":{"artist":"Artist","title":"Title","count":12}},"listening":{"total_seconds":180}}"#).unwrap();
        }
        let db = Db::open(&p).unwrap();
        assert_eq!(
            db.stats("vinyl", Some(2026)).unwrap()["top_songs"][0]["count"],
            12
        );
        assert_eq!(
            db.stats("vinyl", None).unwrap()["total_minutes_listened"],
            3
        );
        assert_eq!(
            db.query("SELECT * FROM legacy_imports", []).unwrap().len(),
            1
        );
    }

    #[test]
    fn invalid_import_is_rolled_back_and_does_not_block_retry() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("legacy.sqlite")).unwrap();
        let invalid = r#"{
            "songs":{"song":{"artist":"Artist","title":"Title","count":1}},
            "listening":{"total_seconds":-30}
        }"#;
        assert!(import(&db, invalid).is_err());
        assert!(db.query("SELECT * FROM songs", []).unwrap().is_empty());
        assert!(db.query("SELECT * FROM legacy_imports", []).unwrap().is_empty());

        import(
            &db,
            r#"{"songs":{"song":{"artist":"Artist","title":"Title","count":1}}}"#,
        )
        .unwrap();
        assert_eq!(db.query("SELECT COUNT(*) AS n FROM songs", []).unwrap()[0]["n"], 1);
        assert!(import(&db, "{}").is_err());
    }
}
