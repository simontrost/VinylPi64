use crate::{db::Db, model::Track, net};
use anyhow::{Context, Result, ensure};
use rusqlite::{OptionalExtension, params};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
struct OAuthState {
    created: Instant,
    return_path: String,
    auto_enable: bool,
}
pub struct Spotify {
    client: reqwest::Client,
    db: Db,
    token: Mutex<Option<(String, Instant)>>,
    states: Mutex<HashMap<String, OAuthState>>,
}
fn env(k: &str) -> String {
    std::env::var(k).unwrap_or_default().trim().to_owned()
}
impl Spotify {
    pub fn new(client: reqwest::Client, db: Db) -> Self {
        Self {
            client,
            db,
            token: Mutex::new(None),
            states: Mutex::new(HashMap::new()),
        }
    }
    pub fn status(&self) -> Result<Value> {
        let account=self.db.query("SELECT account_id,spotify_user_id,display_name,external_url,connected_at FROM spotify_account WHERE id=1",[])?.into_iter().next();
        let configured = !env("SPOTIFY_CLIENT_ID").is_empty()
            && !env("SPOTIFY_CLIENT_SECRET").is_empty()
            && !env("SPOTIFY_REDIRECT_URI").is_empty();
        Ok(
            json!({"ok":true,"configured":configured,"connected":account.is_some(),"account":account,"redirect_uri":env("SPOTIFY_REDIRECT_URI"),"missing": (["SPOTIFY_CLIENT_ID","SPOTIFY_CLIENT_SECRET","SPOTIFY_REDIRECT_URI"].iter().filter(|k|env(k).is_empty()).collect::<Vec<_>>())}),
        )
    }
    pub async fn auth_url(&self, settings: bool, force: bool) -> Result<Value> {
        ensure!(
            self.status()?["configured"] == true,
            "Set Spotify app credentials and SPOTIFY_REDIRECT_URI in vinylpi.env"
        );
        let state = format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        );
        let mut states = self.states.lock().await;
        states.retain(|_, s| s.created.elapsed() < Duration::from_secs(600));
        ensure!(states.len() < 32, "Too many pending authorizations");
        states.insert(
            state.clone(),
            OAuthState {
                created: Instant::now(),
                return_path: if settings { "/settings.html" } else { "/" }.into(),
                auto_enable: !settings,
            },
        );
        let redirect = env("SPOTIFY_REDIRECT_URI");
        let mut u = url::Url::parse("https://accounts.spotify.com/authorize")?;
        u.query_pairs_mut().extend_pairs([
            ("client_id", env("SPOTIFY_CLIENT_ID")),
            ("response_type", "code".into()),
            ("redirect_uri", redirect.clone()),
            (
                "scope",
                "user-read-currently-playing user-read-playback-state".into(),
            ),
            ("state", state),
            ("show_dialog", force.to_string()),
        ]);
        Ok(json!({"ok":true,"auth_url":u.to_string(),"redirect_uri":redirect}))
    }
    async fn exchange(&self, fields: &[(&str, &str)]) -> Result<Value> {
        net::json(
            self.client
                .post("https://accounts.spotify.com/api/token")
                .basic_auth(env("SPOTIFY_CLIENT_ID"), Some(env("SPOTIFY_CLIENT_SECRET")))
                .form(fields),
        )
        .await
        .context("Spotify authorization failed")
    }
    pub async fn callback(&self, state: &str, code: &str) -> Result<(String, bool)> {
        let s = self
            .states
            .lock()
            .await
            .remove(state)
            .context("Invalid OAuth state")?;
        ensure!(
            s.created.elapsed() < Duration::from_secs(600),
            "Expired OAuth state"
        );
        let redirect = env("SPOTIFY_REDIRECT_URI");
        let v = self
            .exchange(&[
                ("grant_type", "authorization_code"),
                ("code", code),
                ("redirect_uri", &redirect),
            ])
            .await?;
        let refresh = v["refresh_token"]
            .as_str()
            .context("Spotify did not return refresh token")?;
        let access = v["access_token"]
            .as_str()
            .context("Spotify did not return access token")?;
        let user = net::json(
            self.client
                .get("https://api.spotify.com/v1/me")
                .bearer_auth(access),
        )
        .await?;
        self.db.with(|c|{c.execute("INSERT INTO spotify_account(id,refresh_token,account_id,spotify_user_id,display_name,external_url) VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET refresh_token=excluded.refresh_token,account_id=excluded.account_id,spotify_user_id=excluded.spotify_user_id,display_name=excluded.display_name,external_url=excluded.external_url,updated_at=strftime('%s','now')",params![refresh,user["id"].as_str(),user["id"].as_str(),user["display_name"].as_str(),user["external_urls"]["spotify"].as_str()])?;Ok(())})?;
        *self.token.lock().await = Some((
            access.to_owned(),
            Instant::now()
                + Duration::from_secs(v["expires_in"].as_u64().unwrap_or(3600).saturating_sub(60)),
        ));
        Ok((s.return_path, s.auto_enable))
    }
    async fn access(&self) -> Result<String> {
        let mut guard = self.token.lock().await;
        if let Some((token, until)) = &*guard
            && *until > Instant::now()
        {
            return Ok(token.clone());
        };
        let refresh = self
            .db
            .with(|c| {
                Ok(c.query_row(
                    "SELECT refresh_token FROM spotify_account WHERE id=1",
                    [],
                    |r| r.get::<_, String>(0),
                )
                .optional()?)
            })?
            .context("Spotify is not connected")?;
        let v = self
            .exchange(&[("grant_type", "refresh_token"), ("refresh_token", &refresh)])
            .await?;
        let access = v["access_token"]
            .as_str()
            .context("Missing access token")?
            .to_owned();
        if let Some(refresh) = v["refresh_token"].as_str() {
            self.db.with(|c|{c.execute("UPDATE spotify_account SET refresh_token=?,updated_at=strftime('%s','now') WHERE id=1",[refresh])?;Ok(())})?;
        }
        *guard = Some((
            access.clone(),
            Instant::now()
                + Duration::from_secs(v["expires_in"].as_u64().unwrap_or(3600).saturating_sub(60)),
        ));
        Ok(access)
    }
    pub async fn disconnect(&self) -> Result<()> {
        let mut guard = self.token.lock().await;
        self.db.with(|c| {
            c.execute("DELETE FROM spotify_account", [])?;
            Ok(())
        })?;
        *guard = None;
        self.states.lock().await.clear();
        Ok(())
    }
    pub async fn current(&self) -> Result<Option<Track>> {
        let access = self.access().await?;
        let response = self
            .client
            .get("https://api.spotify.com/v1/me/player/currently-playing")
            .bearer_auth(&access)
            .send()
            .await?;
        if response.status() == 204 {
            return Ok(None);
        };
        if response.status() == 401 {
            *self.token.lock().await = None;
            anyhow::bail!("Spotify authorization expired; retrying refresh")
        };
        if response.status() == 429 {
            let retry = response
                .headers()
                .get("retry-after")
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.parse::<u64>().ok())
                .unwrap_or(30)
                .clamp(1, 300);
            anyhow::bail!("Spotify rate limited; retry after {retry} seconds")
        };
        let v: Value = serde_json::from_slice(&net::bytes(response, 1024 * 1024).await?)?;
        if v["is_playing"] != true || v["item"].is_null() {
            return Ok(None);
        };
        let t = &v["item"];
        let text = |p: &str| t.pointer(p).and_then(Value::as_str).map(str::to_owned);
        Ok(Some(Track {
            artist: t["artists"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|a| a["name"].as_str())
                .collect::<Vec<_>>()
                .join(", "),
            title: text("/name").context("Spotify track missing name")?,
            album: text("/album/name"),
            cover_url: text("/album/images/0/url"),
            track_id: text("/id"),
            artist_id: text("/artists/0/id"),
            duration_ms: t["duration_ms"].as_i64(),
            progress_ms: v["progress_ms"].as_i64(),
            spotify_url: text("/external_urls/spotify"),
            ..Default::default()
        }))
    }
}
