//! Read-only search across playback aggregates and the locally cached Discogs collection.
//! Collection entries have no synthetic play events: an unplayed record stays at zero.
use crate::{
    db::{Db, rows},
    model::{album_identity, canonical_album_name, canonical_title, normalize},
};
use anyhow::{Result, ensure};
use rusqlite::params;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::HashMap;

#[derive(Serialize)]
struct Hit {
    kind: &'static str,
    title: String,
    artist: String,
    album: String,
    cover_url: Option<String>,
    count: i64,
    in_collection: bool,
    #[serde(skip_serializing)]
    album_names: Vec<String>,
}

impl Hit {
    fn new(kind: &'static str, title: &str, artist: &str) -> Self {
        Self {
            kind,
            title: title.to_owned(),
            artist: artist.to_owned(),
            album: String::new(),
            cover_url: None,
            count: 0,
            in_collection: false,
            album_names: Vec::new(),
        }
    }

    fn add_album(&mut self, album: &str) {
        if !album.trim().is_empty() && !self.album_names.iter().any(|name| name == album) {
            self.album_names.push(album.to_owned());
            if self.album.is_empty() {
                self.album = album.to_owned();
            }
        }
    }

    fn matches(&self, term: &str) -> bool {
        normalize(&self.title).contains(term)
            || normalize(&self.artist).contains(term)
            || self.album_names.iter().any(|album| normalize(album).contains(term))
    }

    fn relevance(&self, term: &str) -> u8 {
        let title = normalize(&self.title);
        if title == term { 0 }
        else if title.starts_with(term) { 1 }
        else if normalize(&self.artist).starts_with(term) { 2 }
        else { 3 }
    }
}

fn field<'a>(row: &'a Value, name: &str) -> &'a str {
    row[name].as_str().unwrap_or("")
}

fn cover(hit: &mut Hit, url: &str) {
    if hit.cover_url.is_none() && (url.starts_with("https://") || url.starts_with("http://")) {
        hit.cover_url = Some(url.to_owned());
    }
}

/// Albums have two different statistics: vinyl *sessions* and Spotify *plays*.
/// Keep the existing aggregation semantics and expose the unit in the response.
pub fn search(
    db: &Db,
    term: &str,
    scope: &str,
    year: Option<i32>,
    kind: &str,
    offset: usize,
    limit: usize,
) -> Result<Value> {
    ensure!(["vinyl", "spotify", "combined"].contains(&scope), "invalid_scope");
    ensure!(["all", "song", "artist", "album"].contains(&kind), "invalid_type");
    ensure!(term.chars().count() <= 120, "search_too_long");
    ensure!(offset <= 100_000 && (1..=50).contains(&limit), "invalid_pagination");
    let term = normalize(term.trim());
    if term.chars().count() < 2 {
        return Ok(json!({"items":[],"total":0,"offset":offset,"limit":limit}));
    }

    // Keep the SQLite lock only while reading a consistent snapshot; ranking
    // a large collection should never block the recognition loop's DB writes.
    let (releases, tracks, plays, album_plays) = db.with(|c| {
        let tx = c.transaction()?;
        let releases = if scope != "spotify" {
            rows(&tx, "SELECT title,artist,COALESCE(cover_url,thumb_url,'') cover_url FROM discogs_releases", [])?
        } else { Vec::new() };
        let tracks = if scope != "spotify" {
            rows(&tx, "SELECT t.title,t.artist,r.title album,COALESCE(r.cover_url,r.thumb_url,'') cover_url FROM discogs_tracks t JOIN discogs_releases r USING(release_id)", [])?
        } else { Vec::new() };
        let plays = rows(&tx, r#"
            SELECT p.artist,p.title,COALESCE(p.album,'') album,SUM(p.count) count,
                   MAX(COALESCE(s.cover_url,sp.cover_url,'')) cover_url
            FROM yearly_plays p
            LEFT JOIN songs s ON p.source='vinyl' AND p.song_key=s.song_key
            LEFT JOIN spotify_songs sp ON p.source='spotify' AND p.song_key=sp.track_id
            WHERE (?1='combined' OR p.source=?1) AND (?2 IS NULL OR p.year=?2)
            GROUP BY lower(p.artist),lower(p.title),lower(COALESCE(p.album,''))
        "#, params![scope, year])?;
        let album_plays = rows(&tx, r#"
            SELECT y.source,y.album,SUM(y.count) count,
                CASE WHEN y.source='vinyl' THEN COALESCE(
                    (SELECT artist FROM album_covers WHERE lower(album)=lower(y.album) LIMIT 1),
                    (SELECT artist FROM songs WHERE lower(album)=lower(y.album) ORDER BY play_count DESC LIMIT 1), '')
                ELSE COALESCE(
                    (SELECT artist FROM spotify_album_totals WHERE lower(album)=lower(y.album) LIMIT 1),
                    (SELECT artist FROM spotify_songs WHERE lower(album)=lower(y.album) ORDER BY play_count DESC LIMIT 1), '') END artist,
                CASE WHEN y.source='vinyl' THEN COALESCE(
                    (SELECT cover_url FROM album_covers WHERE lower(album)=lower(y.album) AND cover_url IS NOT NULL LIMIT 1),
                    (SELECT cover_url FROM songs WHERE lower(album)=lower(y.album) AND cover_url IS NOT NULL LIMIT 1), '')
                ELSE COALESCE(
                    (SELECT cover_url FROM spotify_album_totals WHERE lower(album)=lower(y.album) AND cover_url IS NOT NULL LIMIT 1),
                    (SELECT cover_url FROM spotify_songs WHERE lower(album)=lower(y.album) AND cover_url IS NOT NULL LIMIT 1), '') END cover_url
            FROM yearly_albums y
            WHERE (?1='combined' OR y.source=?1) AND (?2 IS NULL OR y.year=?2)
            GROUP BY y.source,lower(y.album)
        "#, params![scope, year])?;
        tx.commit()?;
        Ok((releases, tracks, plays, album_plays))
    })?;

    let mut songs: HashMap<String, Hit> = HashMap::new();
    let mut artists: HashMap<String, Hit> = HashMap::new();
    let mut albums: HashMap<String, Hit> = HashMap::new();

        if scope != "spotify" {
            // A release exists even when Discogs has no tracklist. Therefore it
            // can appear as an unplayed album (and its artist can be searched).
            for r in releases {
                let (title, artist) = (field(&r, "title"), field(&r, "artist"));
                let key = album_identity(artist, title);
                if !key.is_empty() {
                    let hit = albums.entry(key).or_insert_with(|| Hit::new("album", &canonical_album_name(title), artist));
                    hit.in_collection = true;
                    hit.add_album(title);
                    cover(hit, field(&r, "cover_url"));
                }
                if !artist.trim().is_empty() {
                    artists.entry(normalize(artist))
                        .or_insert_with(|| Hit::new("artist", artist, ""))
                        .in_collection = true;
                }
            }
            for r in tracks {
                let (title, artist, album) = (field(&r, "title"), field(&r, "artist"), field(&r, "album"));
                let key = format!("{}\n{}", normalize(artist), canonical_title(title));
                let hit = songs.entry(key).or_insert_with(|| Hit::new("song", title, artist));
                hit.in_collection = true;
                hit.add_album(album);
                cover(hit, field(&r, "cover_url"));
                if !artist.trim().is_empty() {
                    artists.entry(normalize(artist))
                        .or_insert_with(|| Hit::new("artist", artist, ""))
                        .in_collection = true;
                }
            }
        }

        // Use yearly aggregates, not the lifetime counters in songs: a selected
        // year must only count plays from that year, including imported history.
        for r in plays {
            let (title, artist, album) = (field(&r, "title"), field(&r, "artist"), field(&r, "album"));
            let count = r["count"].as_i64().unwrap_or(0);
            let key = format!("{}\n{}", normalize(artist), canonical_title(title));
            let hit = songs.entry(key).or_insert_with(|| Hit::new("song", title, artist));
            hit.count += count;
            hit.add_album(album);
            cover(hit, field(&r, "cover_url"));
            let artist_hit = artists.entry(normalize(artist))
                .or_insert_with(|| Hit::new("artist", artist, ""));
            artist_hit.count += count;
        }

        for r in album_plays {
            let (title, artist) = (field(&r, "album"), field(&r, "artist"));
            let key = album_identity(artist, title);
            if key.is_empty() { continue; }
            let hit = albums.entry(key).or_insert_with(|| Hit::new("album", &canonical_album_name(title), artist));
            hit.count += r["count"].as_i64().unwrap_or(0);
            hit.add_album(title);
            cover(hit, field(&r, "cover_url"));
        }

        let mut hits = Vec::new();
        if kind == "all" || kind == "song" {
            hits.extend(songs.into_values().filter(|hit| hit.matches(&term)));
        }
        if kind == "all" || kind == "artist" {
            hits.extend(artists.into_values().filter(|hit| hit.matches(&term)));
        }
        if kind == "all" || kind == "album" {
            hits.extend(albums.into_values().filter(|hit| hit.matches(&term)));
        }
        hits.sort_by(|a,b| {
            a.relevance(&term).cmp(&b.relevance(&term))
                .then_with(|| b.count.cmp(&a.count))
                .then_with(|| a.title.to_lowercase().cmp(&b.title.to_lowercase()))
                .then_with(|| a.kind.cmp(b.kind))
                .then_with(|| a.artist.to_lowercase().cmp(&b.artist.to_lowercase()))
                .then_with(|| a.album.to_lowercase().cmp(&b.album.to_lowercase()))
        });
        let total = hits.len();
        let items = hits.into_iter().skip(offset).take(limit).collect::<Vec<_>>();
        Ok(json!({
            "items":items,"total":total,"offset":offset,"limit":limit,
            "album_count_unit":if scope=="vinyl" {"session"} else {"listen"}
        }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Mode, Track};
    use chrono::Datelike;

    #[test]
    fn collection_search_merges_play_counts_and_preserves_unplayed_entries() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("collection.sqlite")).unwrap();
        db.with(|c| {
            c.execute("INSERT INTO discogs_releases(release_id,title,artist,cover_url) VALUES(1,'Blue Album','The Group','https://example.org/blue.jpg')", [])?;
            c.execute("INSERT INTO discogs_releases(release_id,title,artist) VALUES(2,'Unheard Album','The Group')", [])?;
            for (index, (release, title)) in [(1, "Played Song"), (2, "Never Played")].into_iter().enumerate() {
                c.execute("INSERT INTO discogs_tracks(release_id,track_index,title,artist,normalized_title,normalized_artist) VALUES(?,?,?,?,?,?)",
                    params![release, index as i64 + 1, title, "The Group", normalize(title), "the group"])?;
            }
            Ok(())
        }).unwrap();
        let played = Track { artist: "The Group".into(), title: "Played Song".into(), album: Some("Blue Album".into()), ..Default::default() };
        db.record_play(Mode::Vinyl, &played, true).unwrap();
        db.record_play(Mode::Vinyl, &played, false).unwrap();

        let songs = search(&db, "play", "vinyl", None, "song", 0, 40).unwrap();
        let song = &songs["items"][0];
        assert_eq!(song["title"], "Played Song");
        assert_eq!(song["count"], 2);
        assert_eq!(song["in_collection"], true);
        let unheard = search(&db, "never", "vinyl", None, "song", 0, 40).unwrap();
        assert_eq!(unheard["items"][0]["count"], 0);
        assert_eq!(unheard["items"][0]["in_collection"], true);

        // The Discogs-only entries must not leak into Spotify results.
        assert_eq!(search(&db, "never", "spotify", None, "song", 0, 40).unwrap()["total"], 0);
        assert_eq!(search(&db, "unheard", "spotify", None, "album", 0, 40).unwrap()["total"], 0);

        let albums = search(&db, "album", "vinyl", None, "album", 0, 40).unwrap();
        assert_eq!(albums["total"], 2);
        let list = albums["items"].as_array().unwrap();
        assert_eq!(list.iter().find(|v| v["title"] == "Blue Album").unwrap()["count"], 1);
        assert_eq!(list.iter().find(|v| v["title"] == "Unheard Album").unwrap()["count"], 0);
        let artist = search(&db, "group", "vinyl", None, "artist", 0, 40).unwrap();
        assert_eq!(artist["items"][0]["count"], 2);
        assert_eq!(artist["items"][0]["in_collection"], true);
    }

    #[test]
    fn search_respects_source_year_filter_and_pagination() {
        let dir = tempfile::tempdir().unwrap();
        let db = Db::open(&dir.path().join("collection.sqlite")).unwrap();
        let track = Track { artist: "Same Artist".into(), title: "Same Song".into(), album: Some("Same Album".into()), track_id: Some("sp1".into()), ..Default::default() };
        db.record_play(Mode::Vinyl, &track, true).unwrap();
        db.record_play(Mode::Spotify, &track, false).unwrap();
        db.record_play(Mode::Spotify, &track, false).unwrap();
        let vinyl = search(&db, "same", "vinyl", None, "song", 0, 40).unwrap();
        let spotify = search(&db, "same", "spotify", None, "song", 0, 40).unwrap();
        let combined = search(&db, "same", "combined", None, "song", 0, 40).unwrap();
        assert_eq!(vinyl["items"][0]["count"], 1);
        assert_eq!(spotify["items"][0]["count"], 2);
        assert_eq!(combined["items"][0]["count"], 3);
        assert_eq!(search(&db, "same", "combined", None, "all", 0, 1).unwrap()["items"].as_array().unwrap().len(), 1);
        assert_eq!(search(&db, "same", "combined", None, "all", 1, 1).unwrap()["items"].as_array().unwrap().len(), 1);
        assert!(search(&db, "same", "spotify", Some(chrono::Local::now().year() - 1), "song", 0, 40).unwrap()["items"].as_array().unwrap().is_empty());
        assert!(search(&db, "same", "invalid", None, "all", 0, 10).is_err());
        assert!(search(&db, "same", "vinyl", None, "wrong", 0, 10).is_err());
        assert!(search(&db, "same", "vinyl", None, "all", 0, 200).is_err());
    }
}
