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
    db.with(|c|{let tx=c.transaction()?;let existing:i64=tx.query_row("SELECT COUNT(*) FROM songs",[],|r|r.get(0))?;ensure!(existing==0,"JSON import requires an empty statistics database");
        for(key,t)in &songs{let artist=t["artist"].as_str().context("Song missing artist")?;let title=t["title"].as_str().context("Song missing title")?;tx.execute("INSERT INTO songs(song_key,artist,title,album,cover_url,genre,genre_source,shazam_track_id,shazam_artist_id,play_count,duration_ms,duration_minutes,duration_source,measured_listen_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![key,artist,title,t["album"].as_str(),t["cover_url"].as_str(),t["genre"].as_str(),t["genre_source"].as_str(),t["shazam_track_id"].as_str(),t["shazam_artist_id"].as_str(),count(&t["count"])?,t["duration_ms"].as_i64(),t["duration_minutes"].as_f64(),t["duration_source"].as_str(),t["measured_listen_seconds"].as_f64()])?;}
        if artists.is_empty(){tx.execute("INSERT INTO artist_totals(artist,play_count) SELECT artist,SUM(play_count) FROM songs GROUP BY artist",[])?;}else{for(a,n)in &artists{tx.execute("INSERT INTO artist_totals(artist,play_count) VALUES(?,?)",params![a,count(n)?])?;}}
        for(a,n)in &albums{tx.execute("INSERT INTO album_sessions(album,session_count) VALUES(?,?)",params![a,count(n)?])?;}
        for(key,table)in [("listening","listening_totals"),("pickup_usage","pickup_usage_totals")]{let seconds=v[key]["total_seconds"].as_f64().unwrap_or(0.);ensure!(seconds.is_finite()&&seconds>=0.,"Invalid legacy listening total");tx.execute(&format!("UPDATE {table} SET total_seconds=? WHERE id=1"),[seconds])?;}
        for(a,t)in &covers{tx.execute("INSERT INTO album_covers(album,artist,play_count,mbid,cover_url) VALUES(?,?,?,?,?)",params![a,t["artist"].as_str(),count(&t["count"])?,t["mbid"].as_str(),t["cover_url"].as_str()])?;}
        for(key,t)in &durations{tx.execute("INSERT INTO duration_cache(cache_key,artist,title,album,duration_ms,duration_minutes,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)",params![key,t["artist"].as_str().unwrap_or(""),t["title"].as_str().unwrap_or(""),t["album"].as_str(),t["ms"].as_i64().context("Legacy duration missing ms")?,t["minutes"].as_f64().context("Legacy duration missing minutes")?,t["source"].as_str(),t["ts"].as_i64()])?;}
        for(key,t)in &tags{ensure!(t["tags"].is_array(),"Invalid legacy genre cache");tx.execute("INSERT INTO tag_cache(cache_key,artist,title,tags_json,fetched_at) VALUES(?,?,?,?,?)",params![key,t["artist"].as_str().unwrap_or(""),t["title"].as_str().unwrap_or(""),t["tags"].to_string(),t["ts"].as_i64()])?;}
        let digest=format!("{:x}",Sha256::digest(raw.as_bytes()));tx.execute("INSERT INTO legacy_imports(source_name,source_sha256,raw_json) VALUES('stats.json',?,?)",params![digest,raw])?;
        tx.execute_batch("DELETE FROM meta WHERE key='annual_seed_vinyl_v1'; DELETE FROM yearly_plays WHERE source='vinyl'; DELETE FROM yearly_albums WHERE source='vinyl'; DELETE FROM yearly_usage WHERE source='vinyl';")?;
        tx.commit()?;Ok(())
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
}
