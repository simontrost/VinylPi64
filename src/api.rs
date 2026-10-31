use crate::{
    config::ConfigStore,
    db::Db,
    discogs::Discogs,
    display::{Content, Display, Pixoo},
    engine::{Engine, Services},
    metadata::Metadata,
    model::Mode,
    net,
    spotify::Spotify,
    uploads,
};
use anyhow::{Context, Result, ensure};
use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, Multipart, Path, Query, Request, State},
    http::{Method, StatusCode, header},
    middleware::{self, Next},
    response::{
        Html, IntoResponse, Redirect, Response, Sse,
        sse::{Event, KeepAlive},
    },
    routing::{any, get, post},
};
use serde_json::{Value, json};
use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Duration};
use tokio_stream::{StreamExt, wrappers::WatchStream};
use tokio_util::{sync::CancellationToken, task::TaskTracker};
use tower_http::services::ServeDir;

pub struct App {
    pub root: PathBuf,
    pub data: PathBuf,
    pub config: Arc<ConfigStore>,
    pub db: Db,
    pub engine: Arc<Engine>,
    pub display: Arc<Display>,
    pub spotify: Arc<Spotify>,
    pub discogs: Arc<Discogs>,
    pub metadata: Arc<Metadata>,
    pub cancel: CancellationToken,
    pub tasks: TaskTracker,
    templates: minijinja::Environment<'static>,
}
impl App {
    pub fn new(root: PathBuf, data: PathBuf, port: u16) -> Result<Arc<Self>> {
        let client = net::client()?;
        let config = Arc::new(ConfigStore::open(data.join("config.json"))?);
        let db = Db::open(&data.join("vinylpi.db"))?;
        let spotify = Arc::new(Spotify::new(client.clone(), db.clone()));
        let discogs = Arc::new(Discogs::new(client.clone(), db.clone()));
        let metadata = Arc::new(Metadata::new(client.clone(), db.clone()));
        let pixoo = Arc::new(Pixoo::new(client.clone(), config.clone()));
        let (display, display_rx) = Display::new(pixoo);
        let display = Arc::new(display);
        let (engine, engine_rx) = Engine::new();
        let tasks = TaskTracker::new();
        let cancel = CancellationToken::new();
        let mut templates = minijinja::Environment::new();
        templates.set_loader(minijinja::path_loader(root.join("web/templates")));
        templates.add_function(
            "url_for",
            |endpoint: String,
             kwargs: minijinja::value::Kwargs|
             -> std::result::Result<String, minijinja::Error> {
                if endpoint == "static" {
                    return Ok(format!("/static/{}", kwargs.get::<String>("filename")?));
                };
                Ok(match endpoint.as_str() {
                    "pages.index" => "/".to_owned(),
                    s if s.starts_with("pages.") => format!(
                        "/{}.html",
                        s.trim_start_matches("pages.").trim_end_matches("_page")
                    ),
                    _ => String::new(),
                })
            },
        );
        let app = Arc::new(Self {
            root,
            data,
            config,
            db,
            engine,
            display,
            spotify,
            discogs,
            metadata,
            cancel,
            tasks,
            templates,
        });
        app.tasks.spawn(app.engine.clone().run(
            engine_rx,
            Services {
                config: app.config.clone(),
                db: app.db.clone(),
                display: app.display.clone(),
                spotify: app.spotify.clone(),
                discogs: app.discogs.clone(),
                metadata: app.metadata.clone(),
                client,
            },
            app.cancel.clone(),
        ));
        app.tasks.spawn(app.display.clone().run(
            display_rx,
            crate::display::DisplayRuntime {
                root: app.root.clone(),
                data: app.data.clone(),
                port,
                db: app.db.clone(),
                status: app.engine.status.clone(),
                cancel: app.cancel.clone(),
            },
        ));
        app.db.log("INFO", "VinylPi64 Rust started");
        Ok(app)
    }
    pub async fn shutdown(&self) -> Result<()> {
        self.cancel.cancel();
        self.tasks.close();
        tokio::time::timeout(Duration::from_secs(30), self.tasks.wait())
            .await
            .context("Background tasks did not stop within 30 seconds")?;
        self.db.with(|c| {
            c.execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")?;
            Ok(())
        })
    }
    pub fn source(&self) -> Result<Value> {
        let mode = self.engine.get_mode();
        let spotify = self.spotify.status().unwrap_or_else(|error| {
            tracing::warn!(%error, "Unable to read Spotify connection status");
            json!({"ok":false,"configured":false,"connected":false})
        });
        Ok(json!({"ok":true,"mode":mode,"vinyl_running":mode==Mode::Vinyl,"spotify_running":mode==Mode::Spotify,"spotify":spotify}))
    }
}
pub struct ApiError(StatusCode, String);
impl From<anyhow::Error> for ApiError {
    fn from(e: anyhow::Error) -> Self {
        Self(StatusCode::BAD_REQUEST, e.to_string())
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"ok":false,"error":self.1}))).into_response()
    }
}
type ApiResult = std::result::Result<Response, ApiError>;
fn ok(v: Value) -> ApiResult {
    Ok(Json(v).into_response())
}
fn gateway(e: anyhow::Error) -> ApiError {
    ApiError(StatusCode::BAD_GATEWAY, e.to_string())
}
fn binary(data: Vec<u8>, mime: &'static str) -> ApiResult {
    Ok((
        [
            (header::CONTENT_TYPE, mime),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        data,
    )
        .into_response())
}

pub fn router(app: Arc<App>) -> Router {
    Router::new()
        .route("/", get(page))
        .route("/index.html", get(page))
        .route("/settings.html", get(page))
        .route("/stats.html", get(page))
        .route("/pixoo.html", get(page))
        .route("/logs.html", get(page))
        .route("/about.html", get(page))
        .route("/api/events", get(events))
        .route("/api/font", post(upload_font))
        .route("/api/fallback-image", post(upload_image))
        .route("/api/{*path}", any(api))
        .route("/uploads/{*path}", get(upload_file))
        .nest_service("/static", ServeDir::new(app.root.join("web/static")))
        .nest_service(
            "/assets/readme",
            ServeDir::new(app.root.join("assets/readme")),
        )
        .layer(DefaultBodyLimit::max(4 * 1024 * 1024 + 64 * 1024))
        .layer(middleware::from_fn(security))
        .with_state(app)
}
async fn security(request: Request, next: Next) -> Response {
    let headers = request.headers();
    let host = headers
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");
    let name = host.split(':').next().unwrap_or("");
    let configured = std::env::var("VINYLPI_ALLOWED_HOSTS").unwrap_or_default();
    let host_allowed = name == "localhost"
        || name.ends_with(".local")
        || (!name.contains('.') && !name.is_empty())
        || name
            .parse::<std::net::Ipv4Addr>()
            .is_ok_and(|ip| ip.is_private() || ip.is_loopback() || ip.is_link_local())
        || configured.split(',').any(|s| s.trim() == host);
    if !host_allowed {
        return ApiError(
            StatusCode::FORBIDDEN,
            "Untrusted Host header; configure VINYLPI_ALLOWED_HOSTS for a reverse proxy".into(),
        )
        .into_response();
    };
    if request.method() != Method::GET && request.method() != Method::HEAD {
        let origin_ok = headers
            .get(header::ORIGIN)
            .and_then(|h| h.to_str().ok())
            .is_none_or(|o| {
                url::Url::parse(o)
                    .is_ok_and(|u| u[url::Position::BeforeHost..url::Position::AfterPort] == *host)
            });
        if !origin_ok
            || headers
                .get("sec-fetch-site")
                .is_some_and(|v| v == "cross-site")
        {
            return ApiError(StatusCode::FORBIDDEN, "Cross-origin mutation denied".into())
                .into_response();
        };
        let upload = ["/api/font", "/api/fallback-image"].contains(&request.uri().path());
        let content = headers
            .get(header::CONTENT_TYPE)
            .and_then(|h| h.to_str().ok())
            .unwrap_or("");
        if !content.is_empty()
            && !(content.starts_with("application/json")
                || upload && content.starts_with("multipart/form-data"))
        {
            return ApiError(
                StatusCode::UNSUPPORTED_MEDIA_TYPE,
                "Expected application/json".into(),
            )
            .into_response();
        };
    }
    let mut response = next.run(request).await;
    response.headers_mut().insert(
        header::X_CONTENT_TYPE_OPTIONS,
        header::HeaderValue::from_static("nosniff"),
    );
    response.headers_mut().insert(
        header::X_FRAME_OPTIONS,
        header::HeaderValue::from_static("SAMEORIGIN"),
    );
    response
}
async fn page(State(app): State<Arc<App>>, request: Request) -> ApiResult {
    let p = request
        .uri()
        .path()
        .trim_start_matches('/')
        .trim_end_matches(".html");
    let name = if p.is_empty() || p == "index" {
        "dashboard"
    } else {
        p
    };
    let template = app
        .templates
        .get_template(&format!("pages/{name}.html"))
        .map_err(anyhow::Error::from)?;
    let html=template.render(minijinja::context!(active_page=>name,version_info=>json!({"display":format!("{} · Rust",env!("CARGO_PKG_VERSION"))}))).map_err(anyhow::Error::from)?;
    Ok(Html(html).into_response())
}
async fn events(State(app): State<Arc<App>>) -> Response {
    let stream = WatchStream::new(app.engine.status.subscribe()).map(|v| {
        Ok::<_, std::convert::Infallible>(
            Event::default()
                .event("status")
                .data(v.to_string())
                .retry(Duration::from_secs(2)),
        )
    });
    Sse::new(stream)
        .keep_alive(KeepAlive::default().interval(Duration::from_secs(15)))
        .into_response()
}
async fn upload_file(State(app): State<Arc<App>>, Path(path): Path<String>) -> ApiResult {
    let bytes = uploads::read(&app.root.join("assets/fallback"), &path)?;
    let mime = if path.to_lowercase().ends_with(".png") {
        "image/png"
    } else {
        "image/jpeg"
    };
    binary(bytes, mime)
}
async fn multipart(app: Arc<App>, mut m: Multipart, font: bool, k: &str) -> ApiResult {
    while let Some(field) = m.next_field().await.map_err(anyhow::Error::from)? {
        if field.name() != Some("file") {
            continue;
        };
        let filename = field.file_name().unwrap_or("").to_owned();
        let bytes = field.bytes().await.map_err(anyhow::Error::from)?;
        let root = app.root.clone();
        let k = k.to_owned();
        let v = tokio::task::spawn_blocking(move || {
            uploads::upload(&root, &bytes, &filename, font, &k)
        })
        .await
        .map_err(anyhow::Error::from)??;
        return ok(v);
    }
    Err(ApiError(StatusCode::BAD_REQUEST, "No file field".into()))
}
async fn upload_font(State(app): State<Arc<App>>, m: Multipart) -> ApiResult {
    multipart(app, m, true, "normal").await
}
async fn upload_image(
    State(app): State<Arc<App>>,
    Query(q): Query<HashMap<String, String>>,
    m: Multipart,
) -> ApiResult {
    multipart(
        app,
        m,
        false,
        q.get("kind").map(String::as_str).unwrap_or("normal"),
    )
    .await
}
fn integer(v: &Value, key: &str, min: i64, max: i64) -> Result<i64> {
    let n = v[key]
        .as_i64()
        .context(format!("Missing or invalid {key}"))?;
    ensure!((min..=max).contains(&n), "{key} outside permitted range");
    Ok(n)
}
fn filter(q: &HashMap<String, String>) -> Result<(String, Option<i32>)> {
    let scope = q.get("scope").cloned().unwrap_or_else(|| "vinyl".into());
    ensure!(
        ["vinyl", "spotify", "combined"].contains(&scope.as_str()),
        "invalid_scope"
    );
    let year = match q.get("year").map(String::as_str) {
        None | Some("") | Some("all") => None,
        Some(s) => {
            ensure!(
                s.len() == 4 && s.chars().all(|c| c.is_ascii_digit()),
                "invalid_year"
            );
            let y = s.parse()?;
            ensure!((2000..=2100).contains(&y), "invalid_year");
            Some(y)
        }
    };
    Ok((scope, year))
}
async fn api(
    State(app): State<Arc<App>>,
    Path(path): Path<String>,
    Query(q): Query<HashMap<String, String>>,
    request: Request,
) -> ApiResult {
    let method = request.method().clone();
    let headers = request.headers().clone();
    let bytes = axum::body::to_bytes(request.into_body(), 1024 * 1024)
        .await
        .map_err(anyhow::Error::from)?;
    let body: Value = if bytes.is_empty() {
        json!({})
    } else {
        serde_json::from_slice(&bytes).map_err(anyhow::Error::from)?
    };
    let get = method == Method::GET;
    let post = method == Method::POST;
    let delete = method == Method::DELETE;
    match (path.as_str(), get, post, delete) {
        ("health", true, _, _) => {
            ok(json!({"ok":true,"version":env!("CARGO_PKG_VERSION"),"backend":"rust"}))
        }
        ("config", true, _, _) => ok(app.config.get().public()),
        ("config", _, true, _) | ("config/reset", _, true, _) => {
            app.config.update(body, path.ends_with("reset"))?;
            app.display.refresh();
            ok(json!({"ok":true,"display_refresh_requested":true}))
        }
        ("audio-devices", true, _, _) => ok(
            json!({"ok":true,"devices":crate::audio::devices().map_err(|e|ApiError(StatusCode::SERVICE_UNAVAILABLE,e.to_string()))?}),
        ),
        ("status", true, _, _) => ok(app.engine.status.borrow().clone()),
        ("source", true, _, _) => ok(app.source()?),
        ("source", _, true, _) => {
            let mode: Mode =
                serde_json::from_value(body["mode"].clone()).map_err(anyhow::Error::from)?;
            app.engine.set_mode(mode).await?;
            ok(app.source()?)
        }
        ("recognizer/status", true, _, _) => {
            ok(json!({"running":app.engine.get_mode()==Mode::Vinyl}))
        }
        ("recognizer/start", _, true, _) | ("recognizer/stop", _, true, _) => {
            let start = path.ends_with("start");
            let before = app.engine.get_mode();
            app.engine
                .set_mode(if start { Mode::Vinyl } else { Mode::Off })
                .await?;
            ok(
                json!({"ok":true,"started":start&&before!=Mode::Vinyl,"stopped":!start&&before==Mode::Vinyl,"running":app.engine.get_mode()==Mode::Vinyl}),
            )
        }
        ("spotify/status", true, _, _) => ok(app.spotify.status()?),
        ("spotify/auth-url", true, _, _) => ok(app
            .spotify
            .auth_url(
                q.get("return_to").is_some_and(|v| v == "settings"),
                q.get("force").is_some_and(|v| v == "1" || v == "true"),
            )
            .await?),
        ("spotify/callback", true, _, _) => {
            let state = q.get("state").context("Missing OAuth state")?;
            let code = q.get("code").context("Spotify authorization cancelled")?;
            let (path, enable) = app.spotify.callback(state, code).await.map_err(gateway)?;
            if enable {
                app.engine.set_mode(Mode::Spotify).await?;
            }
            Ok(Redirect::to(&format!("{path}?spotify=connected")).into_response())
        }
        ("spotify/disconnect", _, true, _) => {
            if app.engine.get_mode() == Mode::Spotify {
                app.engine.set_mode(Mode::Off).await?;
            }
            app.spotify.disconnect().await?;
            ok(app.spotify.status()?)
        }
        ("discogs/status", true, _, _) => ok(app.discogs.status(&app.config.get())?),
        ("discogs/connect", _, true, _) => {
            let v = app.discogs.get("/oauth/identity").await.map_err(gateway)?;
            let name = v["username"]
                .as_str()
                .context("Discogs account name missing")?;
            app.config
                .update(json!({"discogs":{"enabled":true,"username":name}}), false)?;
            ok(json!({"ok":true,"username":name}))
        }
        ("discogs/sync", _, true, _) => {
            ensure_api(
                !std::env::var("DISCOGS_API_TOKEN")
                    .unwrap_or_default()
                    .is_empty(),
                "Set DISCOGS_API_TOKEN in vinylpi.env",
            )?;
            let cfg = app
                .config
                .update(json!({"discogs":{"enabled":true}}), false)?;
            if app.discogs.status(&cfg)?["syncing"] == true {
                return ok(json!({"ok":true,"started":false}));
            };
            let d = app.discogs.clone();
            let db = app.db.clone();
            let cancel = app.cancel.clone();
            app.tasks.spawn(async move {
                if let Err(e) = d.sync(cfg, cancel).await {
                    db.log("ERROR", &format!("Discogs sync failed: {e}"));
                }
            });
            Ok((
                StatusCode::ACCEPTED,
                Json(json!({"ok":true,"started":true})),
            )
                .into_response())
        }
        ("discogs/folders", true, _, _) => {
            ensure_api(
                app.engine.get_mode() != Mode::Spotify,
                "Switch to Vinyl or Off to choose a record",
            )?;
            ok(app
                .discogs
                .folders(&app.config.get().discogs.username)
                .await
                .map_err(gateway)?)
        }
        ("discogs/random", true, _, _) => {
            ensure_api(
                app.engine.get_mode() != Mode::Spotify,
                "Switch to Vinyl or Off to choose a record",
            )?;
            let parse = |key: &str| -> Result<Option<i64>> {
                q.get(key)
                    .map(|s| {
                        let n = s.parse::<i64>()?;
                        ensure!(n >= if key == "folder_id" { 0 } else { 1 }, "Invalid ID");
                        Ok(n)
                    })
                    .transpose()
            };
            ok(app.discogs.random(
                parse("exclude_release_id")?,
                parse("folder_id")?.filter(|n| *n != 0),
            )?)
        }
        (p, true, _, _) if p.starts_with("discogs/releases/") && p.ends_with("/tracklist") => {
            let id = p
                .trim_start_matches("discogs/releases/")
                .trim_end_matches("/tracklist")
                .parse::<i64>()
                .map_err(anyhow::Error::from)?;
            ok(app.discogs.tracklist_with_durations(id).await?)
        }
        ("pixoo/status", true, _, _) => {
            let v = app
                .display
                .pixoo
                .command(json!({"Command":"Channel/GetAllConf"}))
                .await
                .map_err(gateway)?;
            ok(
                json!({"ok":true,"online":true,"brightness":v["Brightness"],"channel":v["SelectIndex"],"device_name":v["DeviceName"].as_str().unwrap_or("Pixoo"),"raw":v}),
            )
        }
        ("pixoo/brightness", _, true, _) => {
            let n = integer(&body, "brightness", 0, 100)?;
            app.display
                .pixoo
                .command(json!({"Command":"Channel/SetBrightness","Brightness":n}))
                .await
                .map_err(gateway)?;
            ok(json!({"ok":true}))
        }
        ("pixoo/channel", _, true, _) => {
            let n = integer(&body, "channel", 0, 4)?;
            app.display.show(Content::Hold);
            app.display
                .pixoo
                .command(json!({"Command":"Channel/SetIndex","SelectIndex":n}))
                .await
                .map_err(gateway)?;
            ok(json!({"ok":true}))
        }
        ("pixoo/reboot", _, true, _) => {
            app.display.show(Content::Hold);
            app.display
                .pixoo
                .command(json!({"Command":"Device/SysReboot"}))
                .await
                .map_err(gateway)?;
            ok(json!({"ok":true}))
        }
        ("pixoo/play-remote", _, true, _) => {
            let id = body["file_id"].as_str().context("Missing file_id")?;
            ensure_api(!id.is_empty() && id.len() <= 255, "Invalid GIF ID")?;
            app.display.show(Content::Hold);
            app.display
                .pixoo
                .command(json!({"Command":"Draw/SendRemote","FileId":id}))
                .await
                .map_err(gateway)?;
            ok(json!({"ok":true}))
        }
        ("pixoo/selected-gif", _, true, _) => {
            let id = body["file_id"]
                .as_str()
                .context("file_id must be a string")?
                .trim();
            ensure_api(id.len() <= 255, "GIF ID too long")?;
            app.config
                .update(json!({"pixoo_automations":{"stop_gif_file_id":id}}), false)?;
            ok(json!({"ok":true,"selected_file_id":id}))
        }
        ("pixoo/liked-gifs", true, _, _) => {
            let c = app.config.get();
            let d = &c.divoom;
            let selected = &c.pixoo_automations.stop_gif_file_id;
            let setup = d.device_id == 0. || d.device_mac.is_empty();
            if setup {
                return ok(
                    json!({"ok":true,"gifs":[],"cached":false,"needs_setup":true,"selected_file_id":selected}),
                );
            };
            let key = format!("pixoo-likes:{}:{}", d.device_id, d.device_mac);
            if q.get("refresh").is_none_or(|v| v != "1" && v != "true")
                && let Some(v) = app.db.cache(&key)?
            {
                return ok(
                    json!({"ok":true,"gifs":v,"cached":true,"needs_setup":false,"selected_file_id":selected}),
                );
            };
            let v = app
                .display
                .pixoo
                .cloud(
                    "/Device/GetImgLikeList",
                    Some(json!({"DeviceId":d.device_id as i64,"DeviceMac":d.device_mac,"Page":1})),
                )
                .await
                .map_err(gateway)?;
            let gifs = v["ImgList"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|v| json!({"file_id":v["FileId"],"file_name":v["FileName"]}))
                .collect::<Vec<_>>();
            app.db.put_cache(&key, &json!(gifs), 30 * 86400)?;
            ok(
                json!({"ok":true,"gifs":gifs,"cached":false,"needs_setup":false,"selected_file_id":selected}),
            )
        }
        ("pixoo/discover-and-save", _, true, _) => {
            let v = app
                .display
                .pixoo
                .cloud("/Device/ReturnSameLANDevice", None)
                .await
                .map_err(gateway)?;
            let devices = v["DeviceList"]
                .as_array()
                .context("No Divoom devices found")?;
            ensure_api(
                devices.len() == 1,
                "Multiple or no devices found; select an IP using LAN scan",
            )?;
            let d = &devices[0];
            let ip = d["DevicePrivateIP"]
                .as_str()
                .context("Device has no private IP")?;
            let cfg=app.config.update(json!({"divoom":{"ip":ip,"device_id":d["DeviceId"].as_i64().or(d["DeviceID"].as_i64()).unwrap_or(0),"device_mac":d["DeviceMac"].as_str().or(d["MacAddress"].as_str()).unwrap_or("")}}),false)?;
            ok(
                json!({"ok":true,"device":{"device_private_ip":ip,"device_name":d["DeviceName"],"device_id":cfg.divoom.device_id,"device_mac":cfg.divoom.device_mac},"divoom":cfg.divoom}),
            )
        }
        ("pixoo/scan", _, true, _) => {
            let c = app.config.get();
            let p = body["subnet_prefix"]
                .as_str()
                .unwrap_or(&c.divoom.discovery.subnet_prefix);
            ok(json!({"ok":true,"devices":app.display.pixoo.scan(p).await?}))
        }
        ("pixoo/select", _, true, _) => {
            let ip = body["ip"].as_str().context("ip must be a string")?.trim();
            if !ip.is_empty() {
                crate::config::local_ip(ip)?;
                let v = net::json(
                    app.metadata
                        .client
                        .post(format!("http://{ip}/post"))
                        .timeout(Duration::from_secs(3))
                        .json(&json!({"Command":"Channel/GetAllConf"})),
                )
                .await
                .map_err(gateway)?;
                ensure_api(
                    v.get("Brightness").is_some() && v["error_code"].as_i64().unwrap_or(0) == 0,
                    "Selected IP did not respond as a Pixoo",
                )?;
            }
            app.config.update(json!({"divoom":{"ip":ip}}), false)?;
            app.display.refresh();
            ok(json!({"ok":true,"ip":ip}))
        }
        (p, true, _, _) if p.starts_with("pixoo/animation/") && p.ends_with(".gif") => binary(
            uploads::read(
                &app.data.join("animations"),
                p.trim_start_matches("pixoo/animation/"),
            )?,
            "image/gif",
        ),
        ("stats", true, _, _) => {
            let (scope, year) = filter(&q)?;
            let db = app.db.clone();
            let v = tokio::task::spawn_blocking(move || db.stats(&scope, year))
                .await
                .map_err(anyhow::Error::from)??;
            ok(v)
        }
        ("stats/search", true, _, _) => {
            let (scope, year) = filter(&q)?;
            let term = q.get("q").cloned().unwrap_or_default();
            let kind = q.get("type").cloned().unwrap_or_else(|| "all".into());
            let offset = q
                .get("offset")
                .map_or(Ok(0), |v| v.parse::<usize>())
                .context("Invalid offset")?;
            let limit = q
                .get("limit")
                .map_or(Ok(30), |v| v.parse::<usize>())
                .context("Invalid limit")?;
            let db = app.db.clone();
            let result = tokio::task::spawn_blocking(move || {
                crate::stats_search::search(&db, &term, &scope, year, &kind, offset, limit)
            }).await.map_err(anyhow::Error::from)??;
            ok(result)
        }
        ("stats/years", true, _, _) => {
            use chrono::Datelike;
            let years=app.db.query("SELECT year FROM yearly_plays UNION SELECT year FROM yearly_albums UNION SELECT year FROM yearly_usage UNION SELECT ? ORDER BY year DESC",[chrono::Local::now().year()])?;
            ok(json!({"years":years.iter().map(|v|v["year"].clone()).collect::<Vec<_>>()}))
        }
        ("stats/events", true, _, _) => {
            let (scope, year) = filter(&q)?;
            let events=app.db.query("SELECT source,event_type,occurred_at,artist,title,album FROM playback_events WHERE (?='combined' OR source=?) AND (? IS NULL OR CAST(strftime('%Y',occurred_at,'unixepoch','localtime') AS INTEGER)=?) ORDER BY occurred_at DESC LIMIT 200",rusqlite::params![scope,scope,year,year])?;
            ok(
                json!({"events":events,"legacy_year":2026,"note":"Pre-migration aggregates were assigned to 2026 without individual timestamps."}),
            )
        }
        ("stats/share-card", true, _, _) => {
            let (scope, year) = filter(&q)?;
            binary(crate::share::render(&app, &scope, year).await?, "image/png")
        }
        ("fallback-images", true, _, _) => ok(uploads::images(
            &app.root,
            &app.config,
            q.get("kind").map(String::as_str).unwrap_or("normal"),
        )?),
        ("fonts", true, _, _) => ok(uploads::fonts(&app.root, &app.config)?),
        (p, true, _, _) if p.starts_with("font-preview/") => binary(
            uploads::font_preview(&app.root, p.trim_start_matches("font-preview/"))?,
            "image/png",
        ),
        (p, true, _, _) if p.starts_with("font-file/") => binary(
            uploads::read(
                &app.root.join("assets/fonts"),
                p.trim_start_matches("font-file/"),
            )?,
            "font/ttf",
        ),
        (p, _, _, true) if p.starts_with("font/") || p.starts_with("fallback-image/") => {
            let font = p.starts_with("font/");
            let name = p.split_once('/').context("Missing asset name")?.1;
            uploads::delete(&app.root, &app.config, name, font)?;
            app.display.refresh();
            ok(json!({"ok":true}))
        }
        ("lyrics", true, _, _) => ok(app
            .metadata
            .lyrics(
                q.get("artist").map(String::as_str).unwrap_or(""),
                q.get("title").map(String::as_str).unwrap_or(""),
            )
            .await
            .map_err(gateway)?),
        ("shazam/info", true, _, _) => ok(app
            .metadata
            .shazam_info(
                q.get("track_id").map(String::as_str),
                q.get("artist_id").map(String::as_str),
            )
            .await
            .map_err(gateway)?),
        (p, _, true, _) if p.starts_with("ha/") => {
            use subtle::ConstantTimeEq;
            let expected = std::env::var("VINYLPI_API_TOKEN").unwrap_or_default();
            let supplied = headers
                .get("X-Api-Token")
                .and_then(|h| h.to_str().ok())
                .unwrap_or("");
            if expected.is_empty() || !bool::from(expected.as_bytes().ct_eq(supplied.as_bytes())) {
                return Err(ApiError(
                    StatusCode::UNAUTHORIZED,
                    "Invalid API token".into(),
                ));
            };
            match p {
                "ha/music_mode/on" => app.engine.set_mode(Mode::Vinyl).await?,
                "ha/music_mode/off" => app.engine.set_mode(Mode::Off).await?,
                "ha/on" | "ha/off" => {
                    app.display.pixoo.command(json!({"Command":"Channel/SetBrightness","Brightness":if p=="ha/on"{100}else{0}})).await.map_err(gateway)?;
                }
                _ => return Err(ApiError(StatusCode::NOT_FOUND, "Unknown webhook".into())),
            };
            ok(json!({"ok":true,"started":p.ends_with("/on"),"stopped":p.ends_with("/off")}))
        }
        ("logs", true, _, _) => {
            let after = q
                .get("after")
                .and_then(|s| s.parse::<i64>().ok())
                .unwrap_or(0)
                .max(0);
            let limit = q
                .get("limit")
                .and_then(|s| s.parse::<i64>().ok())
                .unwrap_or(150)
                .clamp(1, 300);
            let search = q.get("search").cloned().unwrap_or_default();
            let level = q.get("level").map(String::as_str).unwrap_or("issues");
            let levels = match level {
                "issues" => "'WARNING','ERROR'",
                "errors" => "'ERROR'",
                "warnings" => "'WARNING'",
                "info" => "'INFO'",
                "debug" => "'DEBUG'",
                "trace" => "'TRACE'",
                "all" => "'WARNING','ERROR','INFO','DEBUG','TRACE'",
                _ => {
                    return Err(ApiError(
                        StatusCode::BAD_REQUEST,
                        "Invalid log level".into(),
                    ));
                }
            };
            let history = q.get("history").is_some_and(|v| v == "1");
            let entries=app.db.query(&format!("SELECT id,timestamp,level,logger AS source,message FROM runtime_logs WHERE id>? AND (? OR id>COALESCE((SELECT CAST(value AS INTEGER) FROM meta WHERE key='logs_cleared'),0)) AND level IN({levels}) AND message LIKE ? ORDER BY id {} LIMIT ?",if after==0{"DESC"}else{"ASC"}),rusqlite::params![after,history,format!("%{search}%"),limit])?;
            let entries = if after == 0 {
                entries.into_iter().rev().collect::<Vec<_>>()
            } else {
                entries
            };
            ok(json!({"ok":true,"entries":entries}))
        }
        ("logs/summary", true, _, _) => {
            let since = q
                .get("since")
                .and_then(|s| s.parse::<i64>().ok())
                .unwrap_or(0);
            let v=app.db.query("SELECT (SELECT COALESCE(MAX(id),0) FROM runtime_logs) latest_id,COALESCE(SUM(level='WARNING'),0) warnings,COALESCE(SUM(level='ERROR'),0) errors FROM runtime_logs WHERE id>MAX(?,COALESCE((SELECT CAST(value AS INTEGER) FROM meta WHERE key='logs_cleared'),0))",[since])?;
            let mut v = v[0].clone();
            v["ok"] = json!(true);
            v["unread"] =
                json!(v["warnings"].as_i64().unwrap_or(0) + v["errors"].as_i64().unwrap_or(0));
            ok(v)
        }
        ("logs/clear", _, true, _) => {
            let cutoff = app.db.with(|c| {
                let tx = c.transaction()?;
                let id: i64 =
                    tx.query_row("SELECT COALESCE(MAX(id),0) FROM runtime_logs", [], |r| {
                        r.get(0)
                    })?;
                tx.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES('logs_cleared',?)",
                    [id.to_string()],
                )?;
                tx.commit()?;
                Ok(id)
            })?;
            ok(json!({"ok":true,"cleared_through":cutoff}))
        }
        _ => Err(ApiError(
            StatusCode::NOT_FOUND,
            "Unknown endpoint or method".into(),
        )),
    }
}
fn ensure_api(condition: bool, message: &str) -> std::result::Result<(), ApiError> {
    if condition {
        Ok(())
    } else {
        Err(ApiError(StatusCode::BAD_REQUEST, message.into()))
    }
}
