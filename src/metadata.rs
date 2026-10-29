use crate::{
    db::Db,
    model::{Track, normalize},
    net,
};
use anyhow::{Context, Result, ensure};
use scraper::{ElementRef, Html, Selector};
use serde_json::{Value, json};
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::time::Instant;

const MUSICBRAINZ_BACKOFF: Duration = Duration::from_secs(10 * 60);

struct MusicBrainzPacing {
    next_request: Instant,
    unavailable_until: Option<Instant>,
}

impl MusicBrainzPacing {
    fn new() -> Self {
        Self {
            next_request: Instant::now(),
            unavailable_until: None,
        }
    }

    fn unavailable(&self, now: Instant) -> bool {
        self.unavailable_until.is_some_and(|until| now < until)
    }
}

pub struct Metadata {
    pub client: reqwest::Client,
    db: Db,
    rate: Mutex<MusicBrainzPacing>,
}
pub fn escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}
fn safe_html(e: ElementRef<'_>) -> String {
    let tag = e.value().name();
    if ["script", "style", "noscript"].contains(&tag)
        || e.value().attr("data-exclude-from-selection") == Some("true")
    {
        return String::new();
    };
    if tag == "br" {
        return "<br>".into();
    };
    let mut content = String::new();
    for child in e.children() {
        if let Some(text) = child.value().as_text() {
            content.push_str(&escape(text));
        } else if let Some(el) = ElementRef::wrap(child) {
            content.push_str(&safe_html(el));
        }
    }
    let format = if ["i", "em"].contains(&tag)
        || e.value()
            .attr("style")
            .is_some_and(|s| s.contains("font-style") && s.contains("italic"))
    {
        Some("em")
    } else if ["b", "strong"].contains(&tag) {
        Some("strong")
    } else {
        None
    };
    if let Some(t) = format {
        format!("<{t}>{content}</{t}>")
    } else {
        content
    }
}
pub fn lyrics_payload(html: &str) -> Option<Value> {
    let doc = Html::parse_document(html);
    let selector = Selector::parse("div[data-lyrics-container='true']").ok()?;
    let parts = doc
        .select(&selector)
        .map(safe_html)
        .filter(|s| !s.trim().is_empty())
        .collect::<Vec<_>>();
    if parts.is_empty() {
        return None;
    };
    let html = parts.join("<br><br>");
    let plain_html = html.replace("<br>", "\n");
    let plain = Html::parse_fragment(&plain_html)
        .root_element()
        .text()
        .collect::<String>();
    Some(json!({"lyrics":plain.trim(),"lyrics_html":html}))
}
impl Metadata {
    pub fn new(client: reqwest::Client, db: Db) -> Self {
        Self {
            client,
            db,
            rate: Mutex::new(MusicBrainzPacing::new()),
        }
    }
    pub async fn enrich(&self, t: &mut Track) -> Result<()> {
        if t.duration_ms.is_some() && t.genre.is_some() {
            return Ok(());
        };
        let key = format!("mb:{}", t.identity());
        let value = if let Some(v) = self.db.cache(&key)? {
            v
        } else {
            // A 503 response may indicate MusicBrainz is overloaded or rate-limiting.
            // Skip optional lookups during cooldown instead of delaying recognition.
            let mut rate = self.rate.lock().await;
            if rate.unavailable(Instant::now()) {
                return Ok(());
            }
            tokio::time::sleep_until(rate.next_request).await;
            rate.next_request = Instant::now() + Duration::from_millis(1100);
            let escape_query = |s: &str| s.replace(['"', '\\'], " ");
            let query = format!(
                "artist:\"{}\" AND recording:\"{}\"",
                escape_query(&t.artist),
                escape_query(&t.title)
            );
            let response = self.client
                .get("https://musicbrainz.org/ws/2/recording")
                .query(&[
                    ("query", query),
                    ("fmt", "json".into()),
                    ("limit", "5".into()),
                ])
                .send()
                .await?;
            let status = response.status();
            if status == reqwest::StatusCode::SERVICE_UNAVAILABLE
                || status == reqwest::StatusCode::TOO_MANY_REQUESTS
            {
                rate.unavailable_until = Some(Instant::now() + MUSICBRAINZ_BACKOFF);
                self.db.log("INFO", &format!(
                    "MusicBrainz temporarily unavailable (HTTP {status}); optional metadata lookups paused for 10 minutes"
                ));
                return Ok(());
            }
            let bytes = net::bytes(response, 8 * 1024 * 1024).await?;
            let v: Value = serde_json::from_slice(&bytes)?;
            self.db.put_cache(&key, &v, 30 * 86400)?;
            v
        };
        if let Some(r) = value["recordings"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|r| {
                r["score"].as_i64().unwrap_or(0) >= 95
                    && normalize(r["title"].as_str().unwrap_or("")) == normalize(&t.title)
            })
        {
            if t.duration_ms.is_none() {
                t.duration_ms = r["length"]
                    .as_i64()
                    .filter(|n| (30_000..=1_800_000).contains(n));
            }
            if t.genre.is_none() {
                t.genre = r["tags"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .max_by_key(|v| v["count"].as_i64().unwrap_or(0))
                    .and_then(|v| v["name"].as_str())
                    .map(str::to_owned);
            }
        }
        Ok(())
    }
    pub async fn lyrics(&self, artist: &str, title: &str) -> Result<Value> {
        ensure!(
            !artist.is_empty() && !title.is_empty() && artist.len() < 300 && title.len() < 300,
            "Invalid artist/title"
        );
        let key = format!("lyrics:{}:{}", normalize(artist), normalize(title));
        if let Some(v) = self.db.cache(&key)? {
            return Ok(v);
        };
        let v = net::json(
            self.client
                .get("https://genius.com/api/search/multi")
                .query(&[("q", format!("{artist} {title}"))]),
        )
        .await?;
        let tokens = |s: &str| {
            normalize(s)
                .split(|c: char| !c.is_alphanumeric())
                .filter(|s| !s.is_empty())
                .map(str::to_owned)
                .collect::<std::collections::BTreeSet<_>>()
        };
        let a = tokens(artist);
        let t = tokens(title);
        let result = v["response"]["sections"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|s| s["hits"].as_array())
            .flatten()
            .filter_map(|h| {
                let r = &h["result"];
                let u = r["url"].as_str()?;
                if !u.starts_with("https://genius.com/") || !u.ends_with("-lyrics") {
                    return None;
                };
                let ra = tokens(r["primary_artist"]["name"].as_str().unwrap_or(""));
                let rt = tokens(r["title"].as_str().unwrap_or(""));
                let score = a.intersection(&ra).count() + t.intersection(&rt).count();
                if a.intersection(&ra).count() == 0 || t.intersection(&rt).count() == 0 {
                    return None;
                };
                Some((u, score))
            })
            .max_by_key(|(_, s)| *s);
        let Some((url, _)) = result else {
            return Ok(json!({"ok":false,"error":"not_found"}));
        };
        let data = net::bytes(self.client.get(url).send().await?, 4 * 1024 * 1024).await?;
        let Some(mut payload) = lyrics_payload(&String::from_utf8_lossy(&data)) else {
            return Ok(json!({"ok":false,"error":"no_lyrics","url":url}));
        };
        payload["ok"] = json!(true);
        payload["source"] = json!("genius");
        payload["url"] = json!(url);
        self.db.put_cache(&key, &payload, 365 * 86400)?;
        Ok(payload)
    }
    pub async fn shazam_info(&self, track: Option<&str>, artist: Option<&str>) -> Result<Value> {
        ensure!(track.is_some() || artist.is_some(), "missing_ids");
        for id in [track, artist].into_iter().flatten() {
            ensure!(
                !id.is_empty() && id.len() < 100 && id.chars().all(|c| c.is_ascii_digit()),
                "Invalid Shazam ID"
            );
        }
        let key = format!("shazam:{track:?}:{artist:?}");
        if let Some(v) = self.db.cache(&key)? {
            return Ok(v);
        };
        let mut out = json!({"ok":true,"track":null,"artist":null});
        if let Some(id) = track {
            out["track"]=net::json(self.client.get(format!("https://www.shazam.com/discovery/v5/en/US/web/-/track/{id}?shazamapiversion=v3&video=v3"))).await.context("Shazam track details unavailable")?;
        }
        if let Some(id) = artist {
            out["artist"] = net::json(self.client.get(format!(
                "https://www.shazam.com/services/amapi/v1/catalog/us/artists/{id}?extend=artistBio"
            )))
            .await
            .context("Shazam artist details unavailable")?;
        }
        self.db.put_cache(&key, &out, 86400)?;
        Ok(out)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lyrics_sanitizes_source_preserving_emphasis() {
        let p=lyrics_payload(r#"<div data-lyrics-container="true"><a href="evil">one</a><br><i onclick="evil()">two</i><script>evil()</script><span data-exclude-from-selection="true">ad</span></div>"#).unwrap();
        assert_eq!(p["lyrics"], "one\ntwo");
        assert_eq!(p["lyrics_html"], "one<br><em>two</em>");
    }
    #[test]
    fn musicbrainz_backoff_expires_without_blocking_recognition() {
        let now = Instant::now();
        let mut pacing = MusicBrainzPacing {
            next_request: now,
            unavailable_until: None,
        };
        assert!(!pacing.unavailable(now));
        pacing.unavailable_until = Some(now + MUSICBRAINZ_BACKOFF);
        assert!(pacing.unavailable(now));
        assert!(pacing.unavailable(now + MUSICBRAINZ_BACKOFF - Duration::from_secs(1)));
        assert!(!pacing.unavailable(now + MUSICBRAINZ_BACKOFF));
    }
}
