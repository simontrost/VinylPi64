//! Black-box contracts for the local server. No external accounts or hardware.
//! Assertions cover outcomes and data safety, not HTML text or CSS details.
use axum::{
    body::Body,
    http::{Request, StatusCode, header},
};
use http_body_util::BodyExt;
use serde_json::{Value, json};
use std::{path::PathBuf, sync::Arc};
use tower::ServiceExt;
use vinylpi64::{api::{App, router}, config::Config, model::{Mode, Track}};

async fn app() -> (tempfile::TempDir, Arc<App>) {
    let tmp = tempfile::tempdir().unwrap();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    // Tests must not probe local USB devices or accidentally trigger auto-wake.
    let mut config = Config::default();
    config.behavior.vinyl_auto_wake_enabled = false;
    std::fs::write(tmp.path().join("config.json"), serde_json::to_vec(&config).unwrap()).unwrap();
    let app = App::new(root, tmp.path().to_owned(), 5000).unwrap();
    (tmp, app)
}

async fn request(
    app: &Arc<App>,
    method: &str,
    uri: &str,
    value: Option<Value>,
    headers: &[(&str, &str)],
) -> (StatusCode, Value) {
    let mut builder = Request::builder().method(method).uri(uri);
    if !headers.iter().any(|(name, _)| name.eq_ignore_ascii_case("host")) {
        builder = builder.header(header::HOST, "localhost:5000");
    }
    for &(name, value) in headers {
        builder = builder.header(name, value);
    }
    let body = value.map(|v| v.to_string()).unwrap_or_default();
    let response = router(app.clone())
        .oneshot(builder.body(Body::from(body)).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({"body":String::from_utf8_lossy(&bytes)}));
    (status, value)
}

async fn get(app: &Arc<App>, uri: &str) -> (StatusCode, Value) {
    request(app, "GET", uri, None, &[]).await
}
async fn post(app: &Arc<App>, uri: &str, body: Value) -> (StatusCode, Value) {
    request(app, "POST", uri, Some(body), &[("content-type", "application/json")]).await
}

#[tokio::test]
async fn server_exposes_core_api_contracts() {
    let (_tmp, server) = app().await;
    let (status, health) = get(&server, "/api/health").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(health["backend"], "rust");
    for (uri, field) in [
        ("/api/status", "title"),
        ("/api/source", "mode"),
        ("/api/config", "audio"),
        ("/api/stats", "top_songs"),
        ("/api/discogs/status", "status"),
        ("/api/spotify/status", "configured"),
        ("/api/logs", "entries"),
    ] {
        let (status, response) = get(&server, uri).await;
        assert_eq!(status, StatusCode::OK, "{uri}: {response}");
        assert!(response.get(field).is_some(), "{uri}: {response}");
    }
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn config_updates_are_validated_atomic_persistent_and_resettable() {
    let (tmp, server) = app().await;
    let (_, original) = get(&server, "/api/config").await;
    assert_eq!(post(&server, "/api/config", json!({"audio":{"sample_seconds":7}})).await.0, StatusCode::OK);
    assert_eq!(post(&server, "/api/config", json!({"behavior":{"loop_delay_seconds":2}})).await.0, StatusCode::OK);
    let (_, configured) = get(&server, "/api/config").await;
    assert_eq!(configured["audio"]["sample_seconds"].as_f64(), Some(7.0));
    assert_eq!(configured["behavior"]["loop_delay_seconds"].as_f64(), Some(2.0));
    let persisted = std::fs::read(tmp.path().join("config.json")).unwrap();
    // Bad type, out-of-range value and path traversal must not modify the file.
    for invalid in [
        json!({"audio":{"sample_seconds":0}}),
        json!({"audio":{"channels":"two"}}),
        json!({"fallback":{"image_path":"../../outside.png"}}),
    ] {
        assert_eq!(post(&server, "/api/config", invalid).await.0, StatusCode::BAD_REQUEST);
        assert_eq!(std::fs::read(tmp.path().join("config.json")).unwrap(), persisted);
    }
    assert_eq!(post(&server, "/api/config/reset", json!({})).await.0, StatusCode::OK);
    let (_, reset) = get(&server, "/api/config").await;
    assert_eq!(reset["audio"]["sample_seconds"], original["audio"]["sample_seconds"]);
    assert_eq!(reset["behavior"]["loop_delay_seconds"], original["behavior"]["loop_delay_seconds"]);
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn source_switch_rejects_unavailable_spotify_without_changing_runtime_state() {
    let (_tmp, server) = app().await;
    assert_eq!(get(&server, "/api/source").await.1["mode"], "off");
    assert_eq!(post(&server, "/api/source", json!({"mode":"invalid"})).await.0, StatusCode::BAD_REQUEST);
    // No Spotify credentials are configured: the API must not report a successful switch.
    assert_eq!(post(&server, "/api/source", json!({"mode":"spotify"})).await.0, StatusCode::BAD_REQUEST);
    assert_eq!(get(&server, "/api/source").await.1["mode"], "off");
    assert_eq!(post(&server, "/api/source", json!({"mode":"off"})).await.0, StatusCode::OK);
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn stats_api_filters_real_persisted_plays_by_source_and_year() {
    let (_tmp, server) = app().await;
    let vinyl = Track {
        artist: "Vinyl group".into(), title: "Track one".into(), album: Some("Record".into()),
        genre: Some("Rock".into()), ..Default::default()
    };
    let spotify = Track {
        artist: "Streaming group".into(), title: "Track two".into(), album: Some("Stream".into()),
        track_id: Some("spotify:unique-track".into()), ..Default::default()
    };
    server.db.record_play(Mode::Vinyl, &vinyl, true).unwrap();
    server.db.record_play(Mode::Spotify, &spotify, false).unwrap();
    let (_, v) = get(&server, "/api/stats?scope=vinyl").await;
    let (_, s) = get(&server, "/api/stats?scope=spotify").await;
    let (_, combined) = get(&server, "/api/stats?scope=combined").await;
    assert_eq!(v["top_songs"].as_array().unwrap().len(), 1);
    assert_eq!(v["top_songs"][0]["title"], "Track one");
    assert_eq!(s["top_songs"][0]["title"], "Track two");
    assert_eq!(combined["top_songs"].as_array().unwrap().len(), 2);
    let (_, events) = get(&server, "/api/stats/events?scope=combined").await;
    assert!(events["events"].as_array().unwrap().len() >= 2);
    assert_eq!(get(&server, "/api/stats?year=2000").await.1["top_songs"], json!([]));
    for uri in ["/api/stats?scope=invalid", "/api/stats?year=20x6", "/api/stats?year=1999"] {
        assert_eq!(get(&server, uri).await.0, StatusCode::BAD_REQUEST);
    }
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn logs_are_filterable_incremental_and_clearable_without_deleting_history() {
    let (_tmp, server) = app().await;
    let baseline = get(&server, "/api/logs/summary").await.1["unread"].as_i64().unwrap();
    server.db.log("WARNING", "unique diagnostic warning");
    server.db.log("ERROR", "unique diagnostic error");
    let (_, issues) = get(&server, "/api/logs?level=issues&limit=100&search=unique").await;
    assert_eq!(issues["entries"].as_array().unwrap().len(), 2);
    let first_id = issues["entries"][0]["id"].as_i64().unwrap();
    let (_, errors) = get(&server, "/api/logs?level=errors&search=unique").await;
    assert_eq!(errors["entries"].as_array().unwrap().len(), 1);
    assert_eq!(errors["entries"][0]["message"], "unique diagnostic error");
    let (_, next) = get(&server, &format!("/api/logs?level=issues&after={first_id}&search=unique")).await;
    assert_eq!(next["entries"].as_array().unwrap().len(), 1);
    assert_eq!(get(&server, "/api/logs?level=invalid").await.0, StatusCode::BAD_REQUEST);
    assert!(get(&server, "/api/logs/summary").await.1["unread"].as_i64().unwrap() >= baseline + 2);
    assert_eq!(post(&server, "/api/logs/clear", json!({})).await.0, StatusCode::OK);
    assert_eq!(get(&server, "/api/logs/summary").await.1["unread"], 0);
    assert_eq!(get(&server, "/api/logs?level=issues&search=unique").await.1["entries"], json!([]));
    assert_eq!(get(&server, "/api/logs?level=issues&history=1&search=unique").await.1["entries"].as_array().unwrap().len(), 2);
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn unsafe_requests_are_rejected_before_mutation() {
    let (_tmp, server) = app().await;
    for headers in [
        [("host", "attacker.example")],
        [("origin", "https://attacker.example")],
        [("sec-fetch-site", "cross-site")],
    ] {
        let (status, _) = request(&server, "POST", "/api/config", Some(json!({"audio":{"sample_seconds":8}})), &headers).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
    }
    assert_eq!(request(&server, "POST", "/api/config", Some(json!({})), &[("content-type", "text/plain")]).await.0, StatusCode::UNSUPPORTED_MEDIA_TYPE);
    assert_eq!(post(&server, "/api/ha/music_mode/on", json!({})).await.0, StatusCode::UNAUTHORIZED);
    assert_ne!(get(&server, "/api/config").await.1["audio"]["sample_seconds"].as_f64(), Some(8.0));
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn sse_starts_with_status_and_background_tasks_stop_cleanly() {
    let (_tmp, server) = app().await;
    let response = router(server.clone()).oneshot(
        Request::builder().uri("/api/events").header("host", "localhost:5000")
            .body(Body::empty()).unwrap(),
    ).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(response.headers()[header::CONTENT_TYPE], "text/event-stream");
    let mut body = response.into_body();
    let frame = tokio::time::timeout(std::time::Duration::from_secs(3), body.frame())
        .await.unwrap().unwrap().unwrap();
    assert!(String::from_utf8_lossy(frame.data_ref().unwrap()).contains("event: status"));
    drop(body);
    server.shutdown().await.unwrap();
    assert!(server.tasks.is_empty());
}
