use crate::model::{Mode, Track, album_identity, canonical_album_name};
use anyhow::{Context, Result, ensure};
use chrono::{Datelike, Local, Utc};
use rusqlite::{Connection, OptionalExtension, params, types::ValueRef};
use serde_json::{Value, json};
use std::{
    path::Path,
    collections::HashMap,
    sync::{Arc, Mutex},
    time::Duration,
};

#[derive(Clone)]
pub struct Db(Arc<Mutex<Connection>>);
pub fn rows(c: &Connection, sql: &str, args: impl rusqlite::Params) -> Result<Vec<Value>> {
    let mut stmt = c.prepare(sql)?;
    let names = stmt
        .column_names()
        .iter()
        .map(|s| s.to_string())
        .collect::<Vec<_>>();
    let result = stmt
        .query_map(args, |r| {
            let mut obj = serde_json::Map::new();
            for (i, n) in names.iter().enumerate() {
                let v = match r.get_ref(i)? {
                    ValueRef::Null => Value::Null,
                    ValueRef::Integer(v) => json!(v),
                    ValueRef::Real(v) => json!(v),
                    ValueRef::Text(v) => json!(String::from_utf8_lossy(v)),
                    ValueRef::Blob(_) => Value::Null,
                };
                obj.insert(n.clone(), v);
            }
            Ok(Value::Object(obj))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    Ok(result)
}
/// Group historical album editions at read-time. No migration or rewriting
/// of recorded events is necessary, and original release names remain intact
/// in SQLite for auditing. Artists are included to prevent false merges.
fn rank_albums(rows: Vec<Value>) -> Vec<Value> {
    struct Album {
        name: String,
        artist: String,
        cover_url: Option<String>,
        count: i64,
    }
    let mut by_identity: HashMap<String, Album> = HashMap::new();
    for row in rows {
        let Some(raw_name) = row["name"].as_str() else { continue };
        let name = canonical_album_name(raw_name);
        if name.is_empty() { continue; }
        let artist = row["artist"].as_str().unwrap_or("");
        let count = row["count"].as_i64().unwrap_or(0);
        if count <= 0 { continue; }
        let cover = row["cover_url"].as_str().filter(|s| !s.is_empty()).map(str::to_owned);
        let entry = by_identity.entry(album_identity(artist, raw_name)).or_insert_with(|| Album {
            name,
            artist: artist.to_owned(),
            cover_url: None,
            count: 0,
        });
        entry.count += count;
        if entry.cover_url.is_none() {
            entry.cover_url = cover;
        }
    }
    let mut result = by_identity.into_values().collect::<Vec<_>>();
    result.sort_by(|a,b| b.count.cmp(&a.count).then_with(|| a.name.cmp(&b.name)));
    result.into_iter().take(10).map(|a| json!({
        "name": a.name,
        "artist": a.artist,
        "cover_url": a.cover_url,
        "count": a.count,
    })).collect()
}

pub fn snapshot(source: &Path, dest: &Path) -> Result<()> {
    let c = Connection::open_with_flags(source, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let mut to = Connection::open(dest)?;
    rusqlite::backup::Backup::new(&c, &mut to)?.run_to_completion(
        128,
        Duration::from_millis(10),
        None,
    )?;
    let check: String = to.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    ensure!(check == "ok", "Database integrity check failed");
    Ok(())
}
// Keep schema evolution in one transaction: an interrupted upgrade must not
// leave partially applied columns or annual statistics behind.
fn initialize_schema(connection: &mut Connection) -> Result<()> {
    let tx = connection.transaction()?;
    tx.execute_batch(include_str!("../migrations/001_compatible.sql"))?;

    // Add columns introduced after the original Python schema. The reference
    // database is built from the same bundled schema as a fresh installation.
    let reference = Connection::open_in_memory()?;
    reference.execute_batch(include_str!("../migrations/001_compatible.sql"))?;
    let tables = rows(
        &reference,
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        [],
    )?;
    for table in tables {
        let name = table["name"].as_str().context("table name")?;
        let expected = rows(&reference, &format!("PRAGMA table_info({name})"), [])?;
        let actual = rows(&tx, &format!("PRAGMA table_info({name})"), [])?;
        for column in expected {
            if actual.iter().any(|existing| existing["name"] == column["name"]) {
                continue;
            }
            let key = column["name"].as_str().context("column")?;
            let ty = column["type"].as_str().context("column type")?;
            ensure!(
                column["pk"].as_i64() == Some(0),
                "Cannot migrate missing key {name}.{key}"
            );
            tx.execute_batch(&format!("ALTER TABLE {name} ADD COLUMN {key} {ty}"))?;
            // SQLite cannot ADD a column with a non-constant default.
            // Populate old rows after the column has been added.
            if let Some(default) = column["dflt_value"].as_str() {
                tx.execute_batch(&format!(
                    "UPDATE {name} SET {key}={default} WHERE {key} IS NULL"
                ))?;
            }
        }
    }

    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS runtime_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, level TEXT NOT NULL, logger TEXT NOT NULL, message TEXT NOT NULL, details TEXT);
         CREATE TABLE IF NOT EXISTS rust_cache(key TEXT PRIMARY KEY,payload TEXT NOT NULL,expires INTEGER NOT NULL);
         INSERT OR REPLACE INTO meta(key,value) VALUES('rust_schema_version','1');",
    )?;

    // Historical Python aggregates have no event timestamps. Seed the annual
    // snapshot exactly once rather than fabricating individual play events.
    for (source, table, key, albums, count, usage) in [
        ("vinyl", "songs", "song_key", "album_sessions", "session_count", "listening_totals"),
        ("spotify", "spotify_songs", "track_id", "spotify_album_totals", "play_count", "spotify_listening_totals"),
    ] {
        let marker = format!("annual_seed_{source}_v1");
        let seeded = tx
            .query_row("SELECT 1 FROM meta WHERE key=?", [&marker], |row| row.get::<_, i64>(0))
            .optional()?
            .is_some();
        if seeded {
            continue;
        }
        tx.execute(
            &format!("INSERT INTO yearly_plays(source,year,song_key,artist,title,album,count) SELECT ?,2026,{key},artist,title,album,play_count FROM {table} WHERE play_count>0 ON CONFLICT DO NOTHING"),
            [source],
        )?;
        tx.execute(
            &format!("INSERT INTO yearly_albums(source,year,album,count) SELECT ?,2026,album,{count} FROM {albums} WHERE {count}>0 ON CONFLICT DO NOTHING"),
            [source],
        )?;
        tx.execute(
            &format!("INSERT INTO yearly_usage(source,year,kind,seconds) SELECT ?,2026,'listening',total_seconds FROM {usage} WHERE id=1 AND total_seconds>0 ON CONFLICT DO NOTHING"),
            [source],
        )?;
        if source == "vinyl" {
            tx.execute_batch("INSERT INTO yearly_usage(source,year,kind,seconds) SELECT 'vinyl',2026,'pickup',total_seconds FROM pickup_usage_totals WHERE id=1 AND total_seconds>0 ON CONFLICT DO NOTHING")?;
        }
        tx.execute("INSERT INTO meta(key,value) VALUES(?,'2026')", [marker])?;
    }
    tx.commit()?;
    Ok(())
}

impl Db {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let connection = Connection::open(path)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        connection.execute_batch("PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;")?;

        let initialized = connection
            .query_row(
                "SELECT value FROM meta WHERE key='rust_schema_version'",
                [],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .ok()
            .flatten()
            .is_some();
        if !initialized && path.metadata()?.len() > 4096 {
            snapshot(
                path,
                &path.with_extension(format!("pre-rust-{}.db", uuid::Uuid::new_v4())),
            )?;
        }

        let db = Self(Arc::new(Mutex::new(connection)));
        db.with(initialize_schema)?;
        Ok(db)
    }
    pub fn with<T>(&self, f: impl FnOnce(&mut Connection) -> Result<T>) -> Result<T> {
        let mut c = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("Database mutex poisoned"))?;
        f(&mut c)
    }
    pub async fn call<T: Send + 'static>(
        &self,
        f: impl FnOnce(&mut Connection) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        let d = self.clone();
        tokio::task::spawn_blocking(move || d.with(f)).await?
    }
    pub fn query(&self, sql: &str, args: impl rusqlite::Params) -> Result<Vec<Value>> {
        self.with(|c| rows(c, sql, args))
    }
    pub fn cache(&self, key: &str) -> Result<Option<Value>> {
        self.with(|c| {
            let s: Option<String> = c
                .query_row(
                    "SELECT payload FROM rust_cache WHERE key=? AND expires>?",
                    params![key, Utc::now().timestamp()],
                    |r| r.get(0),
                )
                .optional()?;
            s.map(|s| Ok(serde_json::from_str(&s)?)).transpose()
        })
    }
    pub fn put_cache(&self, key: &str, v: &Value, ttl: i64) -> Result<()> {
        self.with(|c| {
            c.execute(
                "INSERT OR REPLACE INTO rust_cache VALUES(?,?,?)",
                params![key, v.to_string(), Utc::now().timestamp() + ttl],
            )?;
            Ok(())
        })
    }
    pub fn log(&self, level: &str, message: &str) {
        match level {
            "ERROR" => tracing::error!("{message}"),
            "WARNING" => tracing::warn!("{message}"),
            "DEBUG" => tracing::debug!("{message}"),
            _ => tracing::info!("{message}"),
        }
        if let Err(e) = self.with(|c| {
            c.execute(
                "INSERT INTO runtime_logs(timestamp,level,logger,message) VALUES(?,?,?,?)",
                params![
                    Utc::now().timestamp_millis() as f64 / 1000.,
                    level,
                    "vinylpi64",
                    message
                ],
            )?;
            c.execute(
                "DELETE FROM runtime_logs WHERE id < (SELECT MAX(id)-3000 FROM runtime_logs)",
                [],
            )?;
            Ok(())
        }) {
            tracing::error!(error=%e,"Unable to persist diagnostic");
        }
    }
    pub fn record_play(&self, mode: Mode, t: &Track, new_album: bool) -> Result<()> {
        ensure!(mode != Mode::Off, "Cannot record playback for Off");
        let year = Local::now().year();
        let now = Utc::now().timestamp();
        let key = t.key(mode);
        let source = mode.as_str();
        self.with(|c|{let tx=c.transaction()?;
            if mode==Mode::Vinyl {
                tx.execute("INSERT INTO songs(song_key,artist,title,album,cover_url,genre,shazam_track_id,shazam_artist_id,duration_ms,play_count) VALUES(?,?,?,?,?,?,?,?,?,1) ON CONFLICT(song_key) DO UPDATE SET play_count=play_count+1,album=COALESCE(excluded.album,songs.album),cover_url=COALESCE(excluded.cover_url,songs.cover_url),genre=COALESCE(excluded.genre,songs.genre),duration_ms=COALESCE(excluded.duration_ms,songs.duration_ms),updated_at=strftime('%s','now')",params![key,t.artist,t.title,t.album,t.cover_url,t.genre,t.track_id,t.artist_id,t.duration_ms])?;
                tx.execute("INSERT INTO artist_totals(artist,play_count) VALUES(?,1) ON CONFLICT(artist) DO UPDATE SET play_count=play_count+1",[&t.artist])?;
                if new_album && let Some(album)=&t.album {
                    tx.execute("INSERT INTO album_sessions(album,session_count) VALUES(?,1) ON CONFLICT(album) DO UPDATE SET session_count=session_count+1",[album])?;
                    tx.execute("INSERT INTO album_covers(album,artist,play_count,cover_url) VALUES(?,?,1,?) ON CONFLICT(album) DO UPDATE SET play_count=play_count+1,cover_url=COALESCE(excluded.cover_url,album_covers.cover_url)",params![album,t.artist,t.cover_url])?;
                }
            }else{
                tx.execute("INSERT INTO spotify_songs(track_id,artist,title,artist_id,album,cover_url,genre,duration_ms,play_count) VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(track_id) DO UPDATE SET play_count=play_count+1,cover_url=COALESCE(excluded.cover_url,spotify_songs.cover_url),genre=COALESCE(excluded.genre,spotify_songs.genre),updated_at=strftime('%s','now')",params![key,t.artist,t.title,t.artist_id,t.album,t.cover_url,t.genre,t.duration_ms])?;
                tx.execute("INSERT INTO spotify_artist_totals(artist,play_count) VALUES(?,1) ON CONFLICT(artist) DO UPDATE SET play_count=play_count+1",[&t.artist])?;
                if let Some(a)=&t.album{tx.execute("INSERT INTO spotify_album_totals(album,artist,cover_url,play_count) VALUES(?,?,?,1) ON CONFLICT(album) DO UPDATE SET play_count=play_count+1,cover_url=COALESCE(excluded.cover_url,spotify_album_totals.cover_url)",params![a,t.artist,t.cover_url])?;}
            }
            tx.execute("INSERT INTO yearly_plays(source,year,song_key,artist,title,album,count) VALUES(?,?,?,?,?,?,1) ON CONFLICT(source,year,song_key) DO UPDATE SET count=count+1",params![source,year,key,t.artist,t.title,t.album])?;
            tx.execute("INSERT INTO playback_events(source,event_type,occurred_at,song_key,artist,title,album) VALUES(?,'play',?,?,?,?,?)",params![source,now,key,t.artist,t.title,t.album])?;
            if (new_album || mode==Mode::Spotify) && let Some(a)=&t.album {
                tx.execute("INSERT INTO yearly_albums(source,year,album,count) VALUES(?,?,?,1) ON CONFLICT(source,year,album) DO UPDATE SET count=count+1",params![source,year,a])?;
                if mode==Mode::Vinyl{tx.execute("INSERT INTO playback_events(source,event_type,occurred_at,album) VALUES('vinyl','album_session',?,?)",params![now,a])?;}
            }
            tx.commit()?;Ok(())
        })
    }
    pub fn seconds(&self, mode: Mode, key: Option<&str>, seconds: f64, pickup: bool) -> Result<()> {
        ensure!(
            seconds.is_finite() && (0.0..=1800.).contains(&seconds),
            "Invalid listening increment"
        );
        let table = if pickup {
            "pickup_usage_totals"
        } else if mode == Mode::Spotify {
            "spotify_listening_totals"
        } else {
            "listening_totals"
        };
        self.with(|c|{let tx=c.transaction()?;tx.execute(&format!("UPDATE {table} SET total_seconds=total_seconds+? WHERE id=1"),[seconds])?;
            tx.execute("INSERT INTO yearly_usage(source,year,kind,seconds) VALUES(?,?,?,?) ON CONFLICT(source,year,kind) DO UPDATE SET seconds=seconds+excluded.seconds",params![mode.as_str(),Local::now().year(),if pickup{"pickup"}else{"listening"},seconds])?;
            if let Some(key)=key{if mode==Mode::Spotify{tx.execute("UPDATE spotify_songs SET listened_seconds=listened_seconds+? WHERE track_id=?",params![seconds,key])?;}else{tx.execute("UPDATE songs SET measured_listen_seconds=COALESCE(measured_listen_seconds,0)+? WHERE song_key=?",params![seconds,key])?;}}
            tx.commit()?;Ok(())})
    }
    /// Return the last successfully recognized track for this source, not the
    /// currently visible fallback/waiting state.
    pub fn last_status(&self, mode: Mode) -> Result<Option<Value>> {
        if mode == Mode::Off { return Ok(None); }
        self.with(|c| {
            let json: Option<String> = c.query_row(
                "SELECT status_json FROM source_status WHERE source=?",
                [mode.as_str()], |r| r.get(0),
            ).optional()?;
            let cached: Option<Value> = json.as_deref().map(serde_json::from_str::<Value>).transpose()?;
            if let Some(mut remembered) = cached.filter(|s| {
                s["artist"].as_str().is_some_and(|a| !a.is_empty())
                    && s["title"].as_str().is_some_and(|t| !t.is_empty())
            }) {
                if remembered["cover_url"].as_str().is_none_or(|url| url.is_empty()) {
                    let table = if mode == Mode::Spotify { "spotify_songs" } else { "songs" };
                    let query = format!("SELECT cover_url,album FROM {table} WHERE artist=? AND title=? ORDER BY updated_at DESC LIMIT 1");
                    let album = rows(c, &query, params![remembered["artist"].as_str(), remembered["title"].as_str()])?
                        .into_iter().next();
                    if let Some(entry) = album {
                        if entry["cover_url"].as_str().is_some_and(|url| !url.is_empty()) {
                            remembered["cover_url"] = entry["cover_url"].clone();
                        }
                        if remembered["album"].as_str().is_none_or(|name| name.is_empty()) {
                            remembered["album"] = entry["album"].clone();
                        }
                    }
                }
                return Ok(Some(remembered));
            }
            // Existing Python databases have song history but no source_status.
            // Recover the last known song for the dashboard only, without
            // marking it playing or incrementing any statistics.
            let query = if mode == Mode::Spotify {
                "SELECT s.artist,s.title,s.album,s.cover_url,s.genre,s.track_id,s.artist_id,s.duration_ms FROM spotify_songs s LEFT JOIN (SELECT song_key, MAX(occurred_at) last_at FROM playback_events WHERE source='spotify' AND event_type='play' GROUP BY song_key) p ON p.song_key=s.track_id ORDER BY COALESCE(p.last_at,s.updated_at) DESC,s.updated_at DESC LIMIT 1"
            } else {
                "SELECT s.artist,s.title,s.album,s.cover_url,s.genre,s.shazam_track_id AS track_id,s.shazam_artist_id AS artist_id,s.duration_ms FROM songs s LEFT JOIN (SELECT song_key, MAX(occurred_at) last_at FROM playback_events WHERE source='vinyl' AND event_type='play' GROUP BY song_key) p ON p.song_key=s.song_key ORDER BY COALESCE(p.last_at,s.updated_at) DESC,s.updated_at DESC LIMIT 1"
            };
            let candidate = rows(c, query, [])?.into_iter().next();
            Ok(candidate.map(|mut track| {
                track["source"] = json!(mode.as_str());
                track["is_playing"] = json!(false);
                track
            }))
        })
    }
    pub fn save_status(&self, mode: Mode, v: &Value) -> Result<()> {
        self.with(|c|{c.execute("INSERT INTO source_status(source,status_json) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET status_json=excluded.status_json,updated_at=strftime('%s','now')",params![mode.as_str(),v.to_string()])?;Ok(())})
    }
    pub fn stats(&self, scope: &str, year: Option<i32>) -> Result<Value> {
        ensure!(
            ["vinyl", "spotify", "combined"].contains(&scope),
            "Invalid scope"
        );
        self.with(|c|{
            let filter="(?='combined' OR source=?) AND (? IS NULL OR year=?)";
            let args=params![scope,scope,year,year];
            let songs=rows(c,"WITH metadata AS(SELECT 'vinyl' source,song_key,cover_url,genre FROM songs UNION ALL SELECT 'spotify',track_id,cover_url,genre FROM spotify_songs) SELECT p.artist,p.title,MAX(p.album) album,MAX(m.cover_url) cover_url,MAX(m.genre) genre,SUM(p.count) count FROM yearly_plays p LEFT JOIN metadata m ON p.source=m.source AND p.song_key=m.song_key WHERE (?='combined' OR p.source=?) AND (? IS NULL OR year=?) GROUP BY lower(p.artist),lower(p.title) ORDER BY count DESC,p.title LIMIT 10",args)?;
            let artists=rows(c,&format!("SELECT artist name,SUM(count) count FROM yearly_plays WHERE {filter} GROUP BY lower(artist) ORDER BY count DESC,name LIMIT 10"),args)?;
            // Preserve per-source album/artist metadata until after we merge
            // edition aliases. Never LIMIT before grouping: a "Meddle" session
            // must be added to existing "Meddle (2016 Remaster)" sessions.
            let album_rows=rows(c,r#"
                SELECT y.source, y.album name, SUM(y.count) count,
                    CASE WHEN y.source='vinyl' THEN
                        COALESCE(
                            (SELECT artist FROM album_covers WHERE lower(album)=lower(y.album) LIMIT 1),
                            (SELECT artist FROM songs WHERE lower(album)=lower(y.album) ORDER BY play_count DESC LIMIT 1),
                            (SELECT artist FROM yearly_plays WHERE source=y.source AND lower(album)=lower(y.album)
                             GROUP BY artist ORDER BY SUM(count) DESC LIMIT 1), '')
                    ELSE COALESCE(
                            (SELECT artist FROM spotify_album_totals WHERE lower(album)=lower(y.album) LIMIT 1),
                            (SELECT artist FROM spotify_songs WHERE lower(album)=lower(y.album) ORDER BY play_count DESC LIMIT 1),
                            (SELECT artist FROM yearly_plays WHERE source=y.source AND lower(album)=lower(y.album)
                             GROUP BY artist ORDER BY SUM(count) DESC LIMIT 1), '') END artist,
                    CASE WHEN y.source='vinyl' THEN
                        COALESCE(
                            (SELECT cover_url FROM album_covers WHERE lower(album)=lower(y.album)
                             AND trim(COALESCE(cover_url,''))!='' LIMIT 1),
                            (SELECT cover_url FROM songs WHERE lower(album)=lower(y.album)
                             AND trim(COALESCE(cover_url,''))!='' ORDER BY play_count DESC LIMIT 1))
                    ELSE COALESCE(
                            (SELECT cover_url FROM spotify_album_totals WHERE lower(album)=lower(y.album)
                             AND trim(COALESCE(cover_url,''))!='' LIMIT 1),
                            (SELECT cover_url FROM spotify_songs WHERE lower(album)=lower(y.album)
                             AND trim(COALESCE(cover_url,''))!='' ORDER BY play_count DESC LIMIT 1)) END cover_url
                FROM yearly_albums y
                WHERE (?='combined' OR y.source=?) AND (? IS NULL OR y.year=?)
                GROUP BY y.source, lower(y.album)
            "#,args)?;
            let albums=rank_albums(album_rows);
            // The ranked album list may contain legacy sessions without cover art.
            // The image gallery only shows albums for which artwork is known.
            let album_covers = albums.iter().filter(|album| album["cover_url"].as_str().is_some_and(|url| !url.is_empty())).cloned().collect::<Vec<_>>();
            let genres=rows(c,"WITH m AS(SELECT 'vinyl' source,song_key,genre FROM songs UNION ALL SELECT 'spotify',track_id,genre FROM spotify_songs) SELECT m.genre name,SUM(p.count) count FROM yearly_plays p JOIN m ON p.source=m.source AND p.song_key=m.song_key WHERE (?='combined' OR p.source=?) AND (? IS NULL OR year=?) AND m.genre IS NOT NULL AND trim(m.genre)!='' GROUP BY lower(m.genre) ORDER BY count DESC LIMIT 10",args)?;
            let usage=rows(c,&format!("SELECT kind,SUM(seconds) seconds FROM yearly_usage WHERE {filter} GROUP BY kind"),args)?;
            let get=|kind:&str|usage.iter().find(|v|v["kind"]==kind).and_then(|v|v["seconds"].as_f64()).unwrap_or(0.);
            let coverage=rows(c,"WITH m AS(SELECT 'vinyl' source,song_key,genre,shazam_track_id FROM songs UNION ALL SELECT 'spotify',track_id,genre,NULL FROM spotify_songs) SELECT COUNT(DISTINCT p.source||p.song_key) songs_total,COUNT(DISTINCT CASE WHEN m.genre IS NOT NULL AND trim(m.genre)!='' THEN p.source||p.song_key END) songs_with_genre,COUNT(DISTINCT CASE WHEN m.shazam_track_id IS NOT NULL THEN p.source||p.song_key END) songs_with_shazam_id FROM yearly_plays p LEFT JOIN m ON p.source=m.source AND p.song_key=m.song_key WHERE (?='combined' OR p.source=?) AND (? IS NULL OR year=?)",args)?;
            Ok(json!({"scope":scope,"year":year,"top_songs":songs,"top_artists":artists,"top_albums":albums,"top_album_covers":album_covers,"top_genres":genres,"radar_genres":genres.iter().take(6).collect::<Vec<_>>(),"total_minutes_listened":(get("listening")/60.) as i64,"pickup_usage_seconds":get("pickup"),"album_count_unit":if scope=="vinyl"{"session"}else{"listen"},"metadata_coverage":coverage.first()}))
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn legacy_song_history_restores_dashboard_status_without_a_pixoo_command() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("songs.db")).unwrap();
        db.with(|c| {
            c.execute("INSERT INTO songs(song_key,artist,title,album,cover_url) VALUES('v','Vinyl Artist','Vinyl Song','Vinyl Album','https://example.com/v.jpg')", [])?;
            c.execute("INSERT INTO spotify_songs(track_id,artist,title,album,cover_url) VALUES('s','Spotify Artist','Spotify Song','Spotify Album','https://example.com/s.jpg')", [])?;
            Ok(())
        }).unwrap();
        let vinyl = db.last_status(Mode::Vinyl).unwrap().unwrap();
        assert_eq!(vinyl["album"], "Vinyl Album");
        assert_eq!(vinyl["cover_url"], "https://example.com/v.jpg");
        assert_eq!(vinyl["is_playing"], false);
        let spotify = db.last_status(Mode::Spotify).unwrap().unwrap();
        assert_eq!(spotify["title"], "Spotify Song");
        assert_eq!(spotify["is_playing"], false);
    }
    #[test]
    fn transactional_statistics_survive_restart() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("db");
        let db = Db::open(&p).unwrap();
        let t = Track {
            artist: "Artist".into(),
            title: "Song".into(),
            album: Some("Album".into()),
            ..Default::default()
        };
        db.record_play(Mode::Vinyl, &t, true).unwrap();
        db.seconds(Mode::Vinyl, None, 180., false).unwrap();
        drop(db);
        let db = Db::open(&p).unwrap();
        let v = db.stats("vinyl", None).unwrap();
        assert_eq!(v["top_songs"][0]["count"], 1);
        assert_eq!(v["total_minutes_listened"], 3);
        assert_eq!(v["top_albums"][0]["count"], 1);
    }
    #[test]
    fn remembers_tracks_separately_for_vinyl_and_spotify() {
        let d = tempfile::tempdir().unwrap();
        let db = Db::open(&d.path().join("db")).unwrap();
        db.save_status(Mode::Vinyl, &json!({"artist":"Vinyl artist","title":"A"})).unwrap();
        db.save_status(Mode::Spotify, &json!({"artist":"Spotify artist","title":"B"})).unwrap();
        drop(db);
        let db = Db::open(&d.path().join("db")).unwrap();
        assert_eq!(db.last_status(Mode::Vinyl).unwrap().unwrap()["title"], "A");
        assert_eq!(db.last_status(Mode::Spotify).unwrap().unwrap()["title"], "B");
        assert!(db.last_status(Mode::Off).unwrap().is_none());
    }
    #[test]
    fn seeds_legacy_totals_once_without_fabricated_events() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("db");
        let c = Connection::open(&p).unwrap();
        c.execute_batch(include_str!("../migrations/001_compatible.sql"))
            .unwrap();
        c.execute(
            "INSERT INTO songs(song_key,artist,title,play_count) VALUES('a','a','a',8)",
            [],
        )
        .unwrap();
        drop(c);
        for _ in 0..2 {
            let db = Db::open(&p).unwrap();
            assert_eq!(
                db.stats("vinyl", Some(2026)).unwrap()["top_songs"][0]["count"],
                8
            );
            assert!(
                db.query("SELECT * FROM playback_events", [])
                    .unwrap()
                    .is_empty()
            );
        }
    }
}
