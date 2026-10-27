use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use serde_json::{Value, json};
use std::{path::PathBuf, sync::Arc};
use tower::ServiceExt;
use vinylpi64::api::{App, router};

async fn app() -> (tempfile::TempDir, Arc<App>) {
    let d = tempfile::tempdir().unwrap();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let app = App::new(root, d.path().to_owned(), 5000).unwrap();
    (d, app)
}
async fn call(a: Arc<App>, method: &str, url: &str, body: Value) -> (StatusCode, Value) {
    let body = if body.is_null() {
        String::new()
    } else {
        body.to_string()
    };
    let response = router(a)
        .oneshot(
            Request::builder()
                .method(method)
                .uri(url)
                .header("host", "localhost:5000")
                .header("content-type", "application/json")
                .body(Body::from(body))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let v = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({"body":String::from_utf8_lossy(&bytes)}));
    (status, v)
}

#[tokio::test]
async fn all_six_pages_render_and_profiles_are_removed() {
    let (_d, a) = app().await;
    for path in [
        "/",
        "/settings.html",
        "/stats.html",
        "/logs.html",
        "/pixoo.html",
        "/about.html",
    ] {
        let (status, v) = call(a.clone(), "GET", path, Value::Null).await;
        assert_eq!(status, StatusCode::OK, "{path}: {v}");
        let html = v["body"].as_str().unwrap();
        assert!(html.contains("<html"));
        assert!(!html.contains("{%"));
        assert!(!html.contains("js/profile.js"));
        assert!(!html.contains("profile-dialog"));
    }
    assert_eq!(
        call(a.clone(), "GET", "/api/profiles", Value::Null).await.0,
        StatusCode::NOT_FOUND
    );
    a.shutdown().await.unwrap();
}
#[tokio::test]
async fn local_api_contracts_have_expected_shapes() {
    let (_d, a) = app().await;
    for (path, field) in [
        ("/api/config", "audio"),
        ("/api/source", "mode"),
        ("/api/status", "title"),
        ("/api/recognizer/status", "running"),
        ("/api/spotify/status", "configured"),
        ("/api/stats", "top_songs"),
        ("/api/stats?scope=combined&year=2026", "metadata_coverage"),
        ("/api/stats/years", "years"),
        ("/api/stats/events", "events"),
        ("/api/discogs/status", "status"),
        ("/api/discogs/random", "release"),
        ("/api/fonts", "fonts"),
        ("/api/fallback-images?kind=turn", "images"),
        ("/api/logs", "entries"),
        ("/api/logs/summary", "unread"),
    ] {
        let (status, v) = call(a.clone(), "GET", path, Value::Null).await;
        assert_eq!(status, StatusCode::OK, "{path}: {v}");
        assert!(v.get(field).is_some(), "{path}: {v}");
    }
    a.shutdown().await.unwrap();
}
#[tokio::test]
async fn invalid_configuration_never_replaces_valid_file() {
    let (d, a) = app().await;
    assert_eq!(
        call(
            a.clone(),
            "POST",
            "/api/config",
            json!({"audio":{"sample_seconds":8}})
        )
        .await
        .0,
        StatusCode::OK
    );
    let before = std::fs::read(d.path().join("config.json")).unwrap();
    assert_eq!(
        call(
            a.clone(),
            "POST",
            "/api/config",
            json!({"audio":{"sample_seconds":0}})
        )
        .await
        .0,
        StatusCode::BAD_REQUEST
    );
    assert_eq!(std::fs::read(d.path().join("config.json")).unwrap(), before);
    a.shutdown().await.unwrap();
}
#[tokio::test]
async fn cross_origin_and_rebinding_requests_are_rejected() {
    let (_d, a) = app().await;
    for (host, origin) in [
        ("localhost:5000", "https://attacker.example"),
        ("attacker.example", "http://attacker.example"),
    ] {
        let response = router(a.clone())
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/config")
                    .header("host", host)
                    .header("origin", origin)
                    .header("content-type", "application/json")
                    .body(Body::from("{}"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
    }
    assert_eq!(
        call(a.clone(), "POST", "/api/ha/music_mode/off", json!({}))
            .await
            .0,
        StatusCode::UNAUTHORIZED
    );
    a.shutdown().await.unwrap();
}
#[tokio::test]
async fn state_and_filter_errors_do_not_modify_source() {
    let (_d, a) = app().await;
    assert_eq!(
        call(a.clone(), "POST", "/api/source", json!({"mode":"invalid"}))
            .await
            .0,
        StatusCode::BAD_REQUEST
    );
    assert_eq!(
        call(a.clone(), "GET", "/api/source", Value::Null).await.1["mode"],
        "off"
    );
    for path in [
        "/api/stats?scope=nope",
        "/api/stats?year=1999",
        "/api/stats?year=2e03",
        "/api/discogs/random?folder_id=-1",
        "/api/fallback-images?kind=invalid",
    ] {
        assert_eq!(
            call(a.clone(), "GET", path, Value::Null).await.0,
            StatusCode::BAD_REQUEST,
            "{path}"
        );
    }
    a.shutdown().await.unwrap();
}
#[tokio::test]
async fn sse_emits_initial_status_and_shutdown_terminates_tasks() {
    let (_d, a) = app().await;
    let response = router(a.clone())
        .oneshot(
            Request::builder()
                .uri("/api/events")
                .header("host", "localhost")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.headers()["content-type"], "text/event-stream");
    let mut body = response.into_body();
    let frame = tokio::time::timeout(std::time::Duration::from_secs(2), body.frame())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let data = String::from_utf8_lossy(frame.data_ref().unwrap());
    assert!(data.contains("event: status"));
    drop(body);
    a.shutdown().await.unwrap();
    assert!(a.tasks.is_empty());
}
#[tokio::test]
async fn generated_font_preview_and_share_card_are_pngs() {
    let (_d, a) = app().await;
    for path in ["/api/font-preview/vinylpixel.ttf", "/api/stats/share-card"] {
        let response = router(a.clone())
            .oneshot(
                Request::builder()
                    .uri(path)
                    .header("host", "localhost")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = response.into_body().collect().await.unwrap().to_bytes();
        assert!(bytes.starts_with(b"\x89PNG\r\n\x1a\n"));
    }
    a.shutdown().await.unwrap();
}
