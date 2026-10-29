use crate::{
    config::Config,
    db::Db,
    model::{Track, canonical_title, normalize},
    net,
};
use anyhow::{Context, Result, ensure};
use rusqlite::params;
use serde_json::{Value, json};
use std::{sync::Arc, time::Duration};
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

pub struct Discogs {
    client: reqwest::Client,
    pub db: Db,
    sync: Mutex<()>,
    rate: Mutex<tokio::time::Instant>,
}
fn text(v: &Value, key: &str) -> String {
    v[key].as_str().unwrap_or("").to_owned()
}
/// Discogs index tracks have an empty own position. Their nested sub-tracks
/// contain the physical positions (e.g. A1.1–A1.5 or B3.1–B3.4).
/// The parent is one playable work, so use the common position A1 / B3.
fn effective_track_position(entry: &Value) -> Option<String> {
    let own = text(entry, "position");
    if !own.trim().is_empty() {
        return Some(own);
    }
    let children = entry["sub_tracks"].as_array()?;
    let mut parents = children.iter()
        .filter_map(|child| child["position"].as_str().filter(|p| !p.trim().is_empty()))
        .map(|position| position.split_once('.').map_or(position, |(parent, _)| parent));
    let first = parents.next()?;
    // Never manufacture a single position for an index spanning different
    // physical tracks or sides (e.g. A1.1, A2.1 or A1, B1).
    if first.trim().is_empty() || !parents.all(|parent| parent == first) {
        return None;
    }
    Some(first.to_owned())
}

fn release_track_entries(release: &Value) -> Vec<&Value> {
    release["tracklist"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|entry| entry["type_"] != "heading")
        .collect()
}

fn side_for_position(position: &str) -> String {
    position.chars().take_while(char::is_ascii_alphabetic).collect()
}

pub fn normalized(s: &str) -> String {
    normalize(&canonical_title(s))
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
/// Normalize aliases used by Shazam and Discogs for multi-part vinyl tracks.
/// Do not discard part numbers: parts 1-5 must not match parts 6-9.
fn track_match_key(title: &str) -> String {
    let normalized = normalized(title);
    let mut in_parts = false;
    normalized
        .split_whitespace()
        .map(|token| match token {
            "pt" | "pts" | "part" | "parts" => {
                in_parts = true;
                "part"
            }
            "i" if in_parts => "1",
            "ii" if in_parts => "2",
            "iii" if in_parts => "3",
            "iv" if in_parts => "4",
            "v" if in_parts => "5",
            "vi" if in_parts => "6",
            "vii" if in_parts => "7",
            "viii" if in_parts => "8",
            "ix" if in_parts => "9",
            _ => token,
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Shazam sometimes appends an anniversary number to an otherwise identical
/// album (e.g. "Wish You Were Here 50"). That is not a different LP title.
fn album_match_key(album: &str) -> String {
    let normalized = normalized(album);
    let mut words = normalized.split_whitespace().collect::<Vec<_>>();
    while words.last().is_some_and(|w| matches!(*w, "edition" | "anniversary")) {
        words.pop();
    }
    if words.len() >= 3 && words.last().is_some_and(|w| matches!(*w, "50" | "50th" | "40th" | "40" | "30th" | "30" | "25th" | "25")) {
        words.pop();
    }
    words.join(" ")
}

/// First few words only select SQL candidates; a complete normalized title
/// comparison below is required to avoid false-positive release matches.
fn track_search_prefix(title: &str) -> String {
    normalized(title)
        .split_whitespace()
        .take(5)
        .collect::<Vec<_>>()
        .join(" ")
}

fn artists(v: &Value) -> String {
    v.as_array()
        .into_iter()
        .flatten()
        .filter_map(|a| a["name"].as_str())
        .map(|s| {
            let s = s
                .rsplit_once(" (")
                .filter(|(_, n)| n.trim_end_matches(')').chars().all(|c| c.is_ascii_digit()))
                .map_or(s, |(s, _)| s);
            s.to_owned()
        })
        .collect::<Vec<_>>()
        .join(", ")
}
/// Return a side-flip target only for the next physical side of the same
/// already matched Discogs release (A->B, C->D, E->F, ...).
/// Other transitions, unmatched tracks, and missing metadata are ignored.
pub fn side_flip_target(track: &Track) -> Option<String> {
    track.extra.get("discogs_release_id")?.as_i64()?;
    let from = track
        .extra
        .get("discogs_side")?
        .as_str()?
        .trim()
        .to_ascii_uppercase();
    let to = track
        .extra
        .get("discogs_expected_next_side")?
        .as_str()?
        .trim()
        .to_ascii_uppercase();
    if from.len() != 1 || to.len() != 1 {
        return None;
    }
    let a = from.as_bytes()[0];
    let b = to.as_bytes()[0];
    if !a.is_ascii_uppercase() || !b.is_ascii_uppercase() {
        return None;
    }
    if (a - b'A').is_multiple_of(2) && b == a + 1 {
        Some(to)
    } else {
        None
    }
}

impl Discogs {
    pub fn new(client: reqwest::Client, db: Db) -> Self {
        Self {
            client,
            db,
            sync: Mutex::new(()),
            rate: Mutex::new(tokio::time::Instant::now()),
        }
    }
    pub async fn get(&self, path: &str) -> Result<Value> {
        let token = std::env::var("DISCOGS_API_TOKEN").unwrap_or_default();
        ensure!(
            !token.trim().is_empty(),
            "Set DISCOGS_API_TOKEN in vinylpi.env"
        );
        let mut last = self.rate.lock().await;
        tokio::time::sleep_until(*last).await;
        *last = tokio::time::Instant::now() + Duration::from_millis(1100);
        let r = self
            .client
            .get(format!("https://api.discogs.com{path}"))
            .header("Authorization", format!("Discogs token={token}"))
            .send()
            .await?;
        ensure!(
            r.status() != 429,
            "Discogs rate limit reached; retry sync later"
        );
        Ok(serde_json::from_slice(
            &net::bytes(r, 8 * 1024 * 1024).await?,
        )?)
    }
    pub fn status(&self, cfg: &Config) -> Result<Value> {
        let mut v = self
            .db
            .query("SELECT * FROM discogs_sync_state WHERE id=1", [])?
            .into_iter()
            .next()
            .unwrap_or(json!({}));
        let token_configured = !std::env::var("DISCOGS_API_TOKEN")
            .unwrap_or_default()
            .trim()
            .is_empty();
        let releases_count = self
            .db
            .query("SELECT count(*) n FROM discogs_releases", [])?;
        let tracks_count = self.db.query("SELECT count(*) n FROM discogs_tracks", [])?;
        let sync_status = v.get("status").cloned().unwrap_or(Value::Null);
        v["ok"] = json!(true);
        v["enabled"] = json!(cfg.discogs.enabled);
        v["token_configured"] = json!(token_configured);
        // The settings UI reads `connected`; the old endpoint omitted this field.
        v["connected"] = json!(token_configured);
        v["username"] = json!(&cfg.discogs.username);
        v["syncing"] = json!(self.sync.try_lock().is_err());
        v["sync_status"] = sync_status;
        // Use the actual database counts, including imported Python collections.
        v["collection_releases"] = releases_count[0]["n"].clone();
        v["releases_count"] = releases_count[0]["n"].clone();
        v["tracks_count"] = tracks_count[0]["n"].clone();
        Ok(v)
    }
    pub async fn folders(&self, username: &str) -> Result<Value> {
        let local = self.local_folders()?;
        if !username.is_empty() {
            let cache_key = format!("discogs-folders:{username}");
            if self.db.cache(&cache_key)?.is_none() {
                let user =
                    url::form_urlencoded::byte_serialize(username.as_bytes()).collect::<String>();
                if let Ok(v) = self.get(&format!("/users/{user}/collection/folders")).await {
                    self.db.with(|c|{let tx=c.transaction()?;for f in v["folders"].as_array().into_iter().flatten(){tx.execute("INSERT OR REPLACE INTO discogs_folders(folder_id,username,name,fetched_at) VALUES(?,?,?,?)",params![f["id"].as_i64(),username,f["name"].as_str(),chrono::Utc::now().timestamp()])?;}tx.commit()?;Ok(())})?;
                    self.db.put_cache(&cache_key, &json!(true), 86400)?;
                    return Ok(json!({"ok":true,"folders":self.local_folders()?}));
                }
            }
        }
        Ok(json!({"ok":true,"folders":local}))
    }
    fn local_folders(&self) -> Result<Vec<Value>> {
        let mut folders = self.db.query(
            "SELECT 0 id,'All records' name,COUNT(*) count FROM discogs_releases",
            [],
        )?;
        folders.extend(self.db.query("SELECT r.folder_id id,COALESCE(f.name,'Folder '||r.folder_id) name,COUNT(*) count FROM discogs_releases r LEFT JOIN discogs_folders f ON r.folder_id=f.folder_id WHERE r.folder_id!=0 GROUP BY r.folder_id ORDER BY name",[])?);
        Ok(folders)
    }
    pub fn random(&self, exclude: Option<i64>, folder: Option<i64>) -> Result<Value> {
        let query = "SELECT *,release_id AS id,'https://www.discogs.com/release/'||release_id url FROM discogs_releases WHERE (? IS NULL OR folder_id=?) AND (? IS NULL OR release_id!=?) ORDER BY RANDOM() LIMIT 1";
        let mut found = self
            .db
            .query(query, params![folder, folder, exclude, exclude])?;
        if found.is_empty() && exclude.is_some() {
            found = self.db.query(
                query,
                params![folder, folder, Option::<i64>::None, Option::<i64>::None],
            )?;
        }
        if let Some(release) = found.first_mut() {
            release["collection_count"] = self.db.query(
                "SELECT COUNT(*) n FROM discogs_releases WHERE ? IS NULL OR folder_id=?",
                params![folder, folder],
            )?[0]["n"]
                .clone();
        }
        Ok(json!({"ok":true,"release":found.first()}))
    }
    /// Repair old collection imports without discarding songs, statistics or
    /// the user's current release selection. Use the *cached Discogs release*
    /// instead of guessing an A/B side from neighboring songs. Even an expired
    /// cache is adequate: it is the snapshot used when the release was imported.
    fn repair_cached_track_positions(&self, release_id: i64) -> Result<()> {
        let existing = self.db.query(
            "SELECT track_index,position FROM discogs_tracks WHERE release_id=? ORDER BY track_index",
            [release_id],
        )?;
        if existing.is_empty() || existing.iter().all(|row| row["position"].as_str().is_some_and(|p| !p.trim().is_empty())) {
            return Ok(());
        }
        let cached = self.db.query(
            "SELECT payload FROM rust_cache WHERE key=?",
            [format!("discogs-release:{release_id}")],
        )?;
        let Some(payload) = cached.first().and_then(|row| row["payload"].as_str()) else {
            // Imported legacy collections may not have a cached Discogs release.
            // A fresh collection sync will populate it, without speculative sides.
            return Ok(());
        };
        let Ok(detail) = serde_json::from_str::<Value>(payload) else {
            tracing::warn!(release_id, "Cached Discogs release is invalid; skipping automatic position repair");
            return Ok(());
        };
        let entries = release_track_entries(&detail);
        if entries.len() != existing.len() {
            tracing::warn!(release_id, stored = existing.len(), cached = entries.len(), "Discogs tracklist changed; skipping position repair until resync");
            return Ok(());
        }
        let repairs = existing.iter().zip(entries).filter_map(|(row, entry)| {
            if row["position"].as_str().is_some_and(|p| !p.trim().is_empty()) {
                return None;
            }
            Some((row["track_index"].as_i64()?, effective_track_position(entry)?))
        }).collect::<Vec<_>>();
        if repairs.is_empty() {
            return Ok(());
        }
        self.db.with(|conn| {
            let tx = conn.transaction()?;
            for (index, position) in &repairs {
                tx.execute(
                    "UPDATE discogs_tracks SET position=?,side=? WHERE release_id=? AND track_index=? AND (position IS NULL OR trim(position)='')",
                    params![position, side_for_position(position), release_id, index],
                )?;
            }
            tx.commit()?;
            Ok(())
        })?;
        tracing::info!(release_id, repaired = repairs.len(), "Repaired Discogs index-track positions from cached release");
        Ok(())
    }

    pub fn tracklist(&self, id: i64) -> Result<Value> {
        self.repair_cached_track_positions(id)?;
        let release = self
            .db
            .query(
                "SELECT title,artist FROM discogs_releases WHERE release_id=?",
                [id],
            )?
            .into_iter()
            .next()
            .context("Release not found")?;
        let tracks=self.db.query("SELECT track_index,position,side,title,artist,duration_seconds FROM discogs_tracks WHERE release_id=? ORDER BY track_index",[id])?;
        Ok(
            json!({"ok":true,"release_id":id,"title":release["title"],"artist":release["artist"],"tracks":tracks,"track_count":tracks.len()}),
        )
    }
    pub async fn sync(self: Arc<Self>, cfg: Config, cancel: CancellationToken) -> Result<bool> {
        let Ok(_guard) = self.sync.try_lock() else {
            return Ok(false);
        };
        self.db.with(|c|{c.execute("UPDATE discogs_sync_state SET status='syncing',last_error=NULL,message='Loading collection' WHERE id=1",[])?;Ok(())})?;
        let result = tokio::select! {_ = cancel.cancelled()=>Err(anyhow::anyhow!("Discogs sync interrupted; existing data retained")),r=self.sync_inner(&cfg)=>r};
        if let Err(e) = result {
            self.db.with(|c|{c.execute("UPDATE discogs_sync_state SET status='error',last_error=?,message='Previous collection retained' WHERE id=1",[e.to_string()])?;Ok(())})?;
            return Err(e);
        };
        Ok(true)
    }
    async fn sync_inner(&self, cfg: &Config) -> Result<()> {
        let identity = self.get("/oauth/identity").await?;
        let username = identity["username"]
            .as_str()
            .context("Discogs username missing")?;
        let encoded = url::form_urlencoded::byte_serialize(username.as_bytes()).collect::<String>();
        let mut releases = vec![];
        let mut page = 1;
        loop {
            let v = self
                .get(&format!(
                    "/users/{encoded}/collection/folders/0/releases?per_page=100&page={page}"
                ))
                .await?;
            let entries = v["releases"]
                .as_array()
                .context("Discogs collection missing releases")?;
            for r in entries {
                if cfg.discogs.vinyl_only
                    && !r["basic_information"]["formats"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .any(|f| f["name"] == "Vinyl")
                {
                    continue;
                };
                releases.push(r.clone());
            }
            ensure!(releases.len() <= 20000, "Collection exceeds safe sync size");
            let pages = v["pagination"]["pages"]
                .as_u64()
                .context("Discogs pagination missing")?;
            if page >= pages {
                break;
            };
            page += 1;
            ensure!(page <= 500, "Too many Discogs pages");
        }
        // Stage the entire replacement in memory; no deletion or partial collection
        // becomes visible if a page or release request fails.
        let mut details = Vec::with_capacity(releases.len());
        let mut bytes = releases.iter().map(|v| v.to_string().len()).sum::<usize>();
        for (i, r) in releases.iter().enumerate() {
            let id = r["id"].as_i64().context("Release missing id")?;
            let cache_key = format!("discogs-release:{id}");
            let detail = if let Some(cached) = self.db.cache(&cache_key)? {
                cached
            } else {
                let v = self.get(&format!("/releases/{id}")).await?;
                self.db.put_cache(&cache_key, &v, 30 * 86400)?;
                v
            };
            bytes += detail.to_string().len();
            ensure!(
                bytes <= 32 * 1024 * 1024,
                "Collection exceeds the 32 MiB staging limit; previous collection retained"
            );
            details.push(detail);
            self.db.with(|c| {
                c.execute(
                    "UPDATE discogs_sync_state SET message=? WHERE id=1",
                    [format!("Loaded {} / {} releases", i + 1, releases.len())],
                )?;
                Ok(())
            })?;
        }
        self.db.with(|c|{let tx=c.transaction()?;tx.execute("DELETE FROM discogs_tracks",[])?;tx.execute("DELETE FROM discogs_releases",[])?;let mut total=0;
            for (summary,detail) in releases.iter().zip(&details){let basic=&summary["basic_information"];let id=summary["id"].as_i64().context("Release id")?;let artist=artists(&detail["artists"]);let title=text(detail,"title");let cover=detail["images"][0]["uri"].as_str().or(basic["cover_image"].as_str());let format=basic["formats"].as_array().into_iter().flatten().filter_map(|f|f["name"].as_str()).collect::<Vec<_>>().join(", ");
                tx.execute("INSERT INTO discogs_releases(release_id,instance_id,folder_id,title,artist,year,country,label,catalog_number,format_text,thumb_url,cover_url,date_added,details_loaded) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)",params![id,summary["instance_id"].as_i64(),summary["folder_id"].as_i64(),title,artist,detail["year"].as_i64(),detail["country"].as_str(),detail["labels"][0]["name"].as_str(),detail["labels"][0]["catno"].as_str(),format,basic["thumb"].as_str(),cover,summary["date_added"].as_str()])?;
                let mut index=0;
                for t in release_track_entries(detail) {
                    index += 1;
                    let position = effective_track_position(t).unwrap_or_default();
                    let side = side_for_position(&position);
                    let title = text(t, "title");
                    let a = artists(&t["artists"]);
                    let a = if a.is_empty() { artist.clone() } else { a };
                    let duration = text(t,"duration").split(':').try_fold(0i64,|v,p|p.parse::<i64>().ok().map(|n|v*60+n));
                    tx.execute("INSERT INTO discogs_tracks(release_id,track_index,position,side,title,artist,duration_seconds,normalized_title,normalized_artist) VALUES(?,?,?,?,?,?,?,?,?)",params![id,index,position,side,title,a,duration,normalized(&title),normalized(&a)])?;
                    total += 1;
                }
            }
            tx.execute("UPDATE discogs_sync_state SET username=?,status='ready',message='Collection synchronized',last_error=NULL,releases_count=?,tracks_count=?,failed_releases=0,last_synced_at=strftime('%s','now'),updated_at=strftime('%s','now') WHERE id=1",params![username,releases.len() as i64,total])?;tx.commit()?;Ok(())})
    }
    pub fn enrich(&self, t: &mut Track, cfg: &Config, previous: Option<&Track>) -> Result<()> {
        if !cfg.discogs.enabled {
            return Ok(());
        };
        // Discogs uses labels such as "Parts I-V" while Shazam returns
        // "Pts. 1-5". Strict SQL equality silently missed these releases.
        let title = normalized(&t.title);
        let prefix = track_search_prefix(&t.title);
        let matches = self.db.query(
            "SELECT t.*,r.title release_title,r.artist release_artist,r.cover_url,r.year,r.label,r.catalog_number FROM discogs_tracks t JOIN discogs_releases r USING(release_id) WHERE normalized_title=? OR replace(normalized_title,' ','')=replace(?,' ','') OR normalized_title LIKE ? LIMIT 500",
            params![title, title, format!("{prefix}%")],
        )?;
        let wanted_title = track_match_key(&t.title);
        let wanted = normalized(&t.artist);
        let old_id = previous
            .and_then(|t| t.extra.get("discogs_release_id"))
            .and_then(Value::as_i64);
        let old_idx = previous
            .and_then(|t| t.extra.get("discogs_track_index"))
            .and_then(Value::as_i64);
        let best = matches
            .iter()
            .filter_map(|v| {
                if track_match_key(v["title"].as_str().unwrap_or("")) != wanted_title {
                    return None;
                }
                let a = normalized(v["artist"].as_str().unwrap_or(""));
                let artist_match = a == wanted
                    || (!a.is_empty()
                        && wanted.len() > 3
                        && (a.contains(&wanted) || wanted.contains(&a)));
                if !artist_match {
                    return None;
                };
                let sequence = cfg.discogs.sequence_matching
                    && old_id == v["release_id"].as_i64()
                    && old_idx.is_some_and(|i| v["track_index"] == i || v["track_index"] == i + 1);
                let score = if sequence {
                    1.0
                } else if t.album.as_deref().is_some_and(|a| {
                    album_match_key(a) == album_match_key(v["release_title"].as_str().unwrap_or(""))
                }) {
                    0.96
                } else {
                    0.80
                };
                Some((v, score))
            })
            .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        if let Some((v, score)) = best
            && score >= cfg.discogs.min_match_confidence
        {
            let id = v["release_id"].as_i64().context("Release id")?;
            let index = v["track_index"].as_i64().context("Track index")?;
            self.repair_cached_track_positions(id)?;
            let all = self.db.query(
                "SELECT * FROM discogs_tracks WHERE release_id=? ORDER BY track_index",
                [id],
            )?;
            let current = all.iter().find(|row| row["track_index"].as_i64() == Some(index)).context("Matched Discogs track missing")?;
            t.album = v["release_title"].as_str().map(str::to_owned);
            if t.duration_ms.is_none() {
                t.duration_ms = v["duration_seconds"]
                    .as_i64()
                    .filter(|s| *s > 0)
                    .map(|s| s * 1000);
            }
            for (a, b) in [
                ("release_id", "release_id"),
                ("position", "position"),
                ("side", "side"),
                ("track_index", "track_index"),
                ("cover_url", "cover_url"),
                ("year", "year"),
                ("label", "label"),
                ("catalog_number", "catalog_number"),
            ] {
                let value = if matches!(b, "position" | "side" | "track_index") { &current[b] } else { &v[b] };
                t.extra.insert(format!("discogs_{a}"), value.clone());
            }
            t.extra.insert("discogs_confidence".into(), json!(score));
            t.extra
                .insert("discogs_match_source".into(), json!("collection"));
            t.extra
                .insert("discogs_track_count".into(), json!(all.len()));
            let side_tracks = all
                .iter()
                .filter(|r| r["side"] == current["side"])
                .collect::<Vec<_>>();
            t.extra
                .insert("discogs_side_track_count".into(), json!(side_tracks.len()));
            t.extra.insert(
                "discogs_side_track_number".into(),
                json!(
                    side_tracks
                        .iter()
                        .position(|r| r["track_index"] == index)
                        .map(|i| i + 1)
                ),
            );
            if let Some(next) = all.iter().find(|r| r["track_index"] == index + 1) {
                for key in ["title", "artist", "position", "side"] {
                    t.extra
                        .insert(format!("discogs_expected_next_{key}"), next[key].clone());
                }
            }
            if cfg.discogs.cover_source == "discogs" {
                t.cover_url = v["cover_url"]
                    .as_str()
                    .map(str::to_owned)
                    .or(t.cover_url.clone());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod side_flip_tests {
    use super::*;

    fn matched(from: &str, to: &str) -> Track {
        let mut track = Track::default();
        track.extra.insert("discogs_release_id".into(), json!(10));
        track.extra.insert("discogs_side".into(), json!(from));
        track
            .extra
            .insert("discogs_expected_next_side".into(), json!(to));
        track
    }

    #[test]
    fn only_paired_side_transitions_prompt() {
        assert_eq!(side_flip_target(&matched("a", "b")), Some("B".to_owned()));
        assert_eq!(side_flip_target(&matched("C", "D")), Some("D".to_owned()));
        for (from, to) in [("B", "C"), ("A", "C"), ("D", "A"), ("A", "A"), ("A1", "B")] {
            assert!(
                side_flip_target(&matched(from, to)).is_none(),
                "{from} -> {to}"
            );
        }
        let mut no_release = matched("A", "B");
        no_release.extra.remove("discogs_release_id");
        assert!(side_flip_target(&no_release).is_none());
    }
}

#[cfg(test)]
mod index_track_position_tests {
    use super::*;

    fn wish_you_were_here_release() -> Value {
        json!({"tracklist":[
            {"type_":"index", "title":"Shine On You Crazy Diamond (1 - 5)","position":"", "sub_tracks":[
                {"position":"A1.1","title":"Part 1"},{"position":"A1.2","title":"Part 2"},
                {"position":"A1.3","title":"Part 3"},{"position":"A1.4","title":"Part 4"},
                {"position":"A1.5","title":"Part 5"}]},
            {"type_":"track","position":"A2","title":"Welcome To The Machine"},
            {"type_":"track","position":"B1","title":"Have A Cigar"},
            {"type_":"track","position":"B2","title":"Wish You Were Here"},
            {"type_":"index","position":"","title":"Shine On You Crazy Diamond (6 - 9)","sub_tracks":[
                {"position":"B3.1","title":"Part 6"},{"position":"B3.2","title":"Part 7"},
                {"position":"B3.3","title":"Part 8"},{"position":"B3.4","title":"Part 9"}]}
        ]})
    }

    #[test]
    fn derives_physical_sides_from_nested_discogs_index_tracks() {
        let release = wish_you_were_here_release();
        let entries = release_track_entries(&release);
        let positions = entries.iter().map(|entry| effective_track_position(entry).unwrap()).collect::<Vec<_>>();
        assert_eq!(positions, ["A1", "A2", "B1", "B2", "B3"]);
        let sides = positions.iter().map(|p| side_for_position(p)).collect::<Vec<_>>();
        assert_eq!(sides, ["A", "A", "B", "B", "B"]);
        assert_eq!(effective_track_position(&json!({"position":"","type_":"index"})), None);
        assert_eq!(effective_track_position(&json!({"position":"","sub_tracks":[{"position":"A1.1"},{"position":"B2.1"}]})), None);
    }

    #[test]
    fn repairs_already_synchronized_release_from_snapshot_without_resync() {
        let tmp = tempfile::tempdir().unwrap();
        let db = Db::open(&tmp.path().join("discogs.db")).unwrap();
        let release = wish_you_were_here_release();
        db.put_cache("discogs-release:9180570", &release, 86400).unwrap();
        db.with(|conn| {
            conn.execute("INSERT INTO discogs_releases(release_id,title,artist) VALUES(9180570,'Wish You Were Here','Pink Floyd')", [])?;
            for (index, entry) in release_track_entries(&release).iter().enumerate() {
                let position = text(entry, "position");
                conn.execute("INSERT INTO discogs_tracks(release_id,track_index,position,side,title,artist,normalized_title,normalized_artist) VALUES(?,?,?,?,?,?,?,?)",
                    params![9180570, index as i64+1, position, side_for_position(&position), text(entry,"title"), "Pink Floyd", normalized(&text(entry,"title")), "pink floyd"])?;
            }
            Ok(())
        }).unwrap();
        let discogs = Discogs::new(reqwest::Client::new(), db);
        let data = discogs.tracklist(9180570).unwrap();
        assert_eq!(data["track_count"], 5);
        let tracks = data["tracks"].as_array().unwrap();
        assert_eq!(tracks.iter().map(|t| t["position"].as_str().unwrap()).collect::<Vec<_>>(), ["A1", "A2", "B1", "B2", "B3"]);
        // Repair is idempotent, and matching sees the fixed physical side too.
        assert_eq!(discogs.tracklist(9180570).unwrap()["tracks"], data["tracks"]);
        let mut cfg = Config::default();
        cfg.discogs.enabled = true;
        let mut track = Track{artist:"Pink Floyd".into(),title:"Shine On You Crazy Diamond (1 - 5)".into(),album:Some("Wish You Were Here".into()), ..Default::default()};
        discogs.enrich(&mut track, &cfg, None).unwrap();
        assert_eq!(track.extra["discogs_position"], "A1");
        assert_eq!(track.extra["discogs_side"], "A");
        assert_eq!(track.extra["discogs_side_track_number"], 1);
        assert_eq!(track.extra["discogs_side_track_count"], 2);
    }
}

#[cfg(test)]
mod vinyl_matching_tests {
    use super::*;
    #[test]
    fn shazam_anniversary_and_parts_match_without_conflating_sides() {
        assert_eq!(album_match_key("Wish You Were Here 50"), album_match_key("Wish You Were Here"));
        assert_eq!(album_match_key("Wish You Were Here 50th Anniversary"), "wish you were here");
        assert_eq!(track_match_key("Shine On You Crazy Diamond (Pts. 1-5)"),
                   track_match_key("Shine On You Crazy Diamond (Parts I-V)"));
        assert_ne!(track_match_key("Shine On You Crazy Diamond (Pts. 1-5)"),
                   track_match_key("Shine On You Crazy Diamond (Parts VI-IX)"));
    }
    #[test]
    fn lookup_uses_own_collection_and_matches_reissue_aliases() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("discogs.db")).unwrap();
        let name = "Shine On You Crazy Diamond (Parts I-V)";
        db.with(|c| {
            c.execute("INSERT INTO discogs_releases(release_id,title,artist,cover_url) VALUES(123,'Wish You Were Here','Pink Floyd','https://example.com/original.jpg')", [])?;
            c.execute("INSERT INTO discogs_tracks(release_id,track_index,position,side,title,artist,normalized_title,normalized_artist) VALUES(123,1,'A1','A',?,'Pink Floyd',?,'pink floyd')",params![name,normalized(name)])?;
            Ok(())
        }).unwrap();
        let discogs = Discogs::new(reqwest::Client::new(), db);
        let mut cfg = Config::default();
        cfg.discogs.enabled = true;
        let mut track = Track {
            artist: "Pink Floyd".to_owned(),
            title: "Shine On You Crazy Diamond (Pts. 1-5)".to_owned(),
            album: Some("Wish You Were Here 50".to_owned()),
            ..Default::default()
        };
        discogs.enrich(&mut track, &cfg, None).unwrap();
        assert_eq!(track.extra["discogs_release_id"].as_i64(), Some(123));
        assert!((track.extra["discogs_confidence"].as_f64().unwrap() - 0.96).abs() < 1e-9);
        assert_eq!(track.album.as_deref(), Some("Wish You Were Here"));
    }
}
