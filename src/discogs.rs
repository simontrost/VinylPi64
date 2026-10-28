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
pub fn normalized(s: &str) -> String {
    normalize(&canonical_title(s))
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { ' ' })
        .collect::<String>()
        .split_whitespace()
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
    if track.extra.get("discogs_release_id")?.as_i64().is_none() {
        return None;
    }
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
    if (a - b'A') % 2 == 0 && b == a + 1 {
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
        v["ok"] = json!(true);
        v["enabled"] = json!(cfg.discogs.enabled);
        v["token_configured"] = json!(
            !std::env::var("DISCOGS_API_TOKEN")
                .unwrap_or_default()
                .is_empty()
        );
        v["syncing"] = json!(self.sync.try_lock().is_err());
        v["collection_releases"] = json!(
            self.db
                .query("SELECT count(*) n FROM discogs_releases", [])?[0]["n"]
        );
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
    pub fn tracklist(&self, id: i64) -> Result<Value> {
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
                let mut index=0;for t in detail["tracklist"].as_array().into_iter().flatten(){if t["type_"]=="heading"{continue};index+=1;let position=text(t,"position");let side=position.chars().take_while(char::is_ascii_alphabetic).collect::<String>();let title=text(t,"title");let a=artists(&t["artists"]);let a=if a.is_empty(){artist.clone()}else{a};let duration=text(t,"duration").split(':').try_fold(0i64,|v,p|p.parse::<i64>().ok().map(|n|v*60+n));
                    tx.execute("INSERT INTO discogs_tracks(release_id,track_index,position,side,title,artist,duration_seconds,normalized_title,normalized_artist) VALUES(?,?,?,?,?,?,?,?,?)",params![id,index,position,side,title,a,duration,normalized(&title),normalized(&a)])?;total+=1;
                }
            }
            tx.execute("UPDATE discogs_sync_state SET username=?,status='ready',message='Collection synchronized',last_error=NULL,releases_count=?,tracks_count=?,failed_releases=0,last_synced_at=strftime('%s','now'),updated_at=strftime('%s','now') WHERE id=1",params![username,releases.len() as i64,total])?;tx.commit()?;Ok(())})
    }
    pub fn enrich(&self, t: &mut Track, cfg: &Config, previous: Option<&Track>) -> Result<()> {
        if !cfg.discogs.enabled {
            return Ok(());
        };
        let matches=self.db.query("SELECT t.*,r.title release_title,r.artist release_artist,r.cover_url,r.year,r.label,r.catalog_number FROM discogs_tracks t JOIN discogs_releases r USING(release_id) WHERE normalized_title=? OR replace(normalized_title,' ','')=replace(?,' ','') LIMIT 200",params![normalized(&t.title),normalized(&t.title)])?;
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
                    normalized(a) == normalized(v["release_title"].as_str().unwrap_or(""))
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
            let all = self.db.query(
                "SELECT * FROM discogs_tracks WHERE release_id=? ORDER BY track_index",
                [id],
            )?;
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
                t.extra.insert(format!("discogs_{a}"), v[b].clone());
            }
            t.extra.insert("discogs_confidence".into(), json!(score));
            t.extra
                .insert("discogs_match_source".into(), json!("collection"));
            t.extra
                .insert("discogs_track_count".into(), json!(all.len()));
            let side_tracks = all
                .iter()
                .filter(|r| r["side"] == v["side"])
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
