use anyhow::{Result, ensure};
use serde_json::Value;
use std::time::Duration;
pub fn client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .user_agent("VinylPi64/0.1 (https://github.com/simontrost/VinylPi64)")
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(20))
        .redirect(reqwest::redirect::Policy::limited(3))
        .build()?)
}
pub async fn bytes(response: reqwest::Response, limit: usize) -> Result<Vec<u8>> {
    use futures_util::StreamExt;
    let response = response.error_for_status()?;
    ensure!(
        response.content_length().unwrap_or(0) <= limit as u64,
        "Remote response too large"
    );
    let mut stream = response.bytes_stream();
    let mut data = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk?;
        ensure!(
            data.len() + chunk.len() <= limit,
            "Remote response too large"
        );
        data.extend_from_slice(&chunk);
    }
    Ok(data)
}
pub async fn json(request: reqwest::RequestBuilder) -> Result<Value> {
    Ok(serde_json::from_slice(
        &bytes(request.send().await?, 8 * 1024 * 1024).await?,
    )?)
}
pub async fn recognize(
    client: &reqwest::Client,
    pcm: Vec<i16>,
    timeout: f64,
) -> Result<Option<crate::model::Track>> {
    let (uri, millis) = tokio::task::spawn_blocking(move || {
        let duration = pcm.len() * 1000 / 16000;
        let sig =
            shazam_fingerprint::algorithm::SignatureGenerator::make_signature_from_buffer(pcm);
        let uri = sig.encode_to_uri().map_err(|e| anyhow::anyhow!("{e}"))?;
        Ok::<_, anyhow::Error>((uri, duration))
    })
    .await??;
    let timestamp = chrono::Utc::now().timestamp_millis();
    let endpoint = format!(
        "https://amp.shazam.com/discovery/v5/en/US/iphone/-/tag/{}/{}?sync=true&webv3=true&sampling=true&connected=&shazamapiversion=v3&sharehub=true&hubv5minorversion=v5.1&hidelb=true&video=v3",
        uuid::Uuid::new_v4().to_string().to_uppercase(),
        uuid::Uuid::new_v4().to_string().to_uppercase()
    );
    let payload = serde_json::json!({"timezone":std::env::var("TZ").unwrap_or_else(|_|"Europe/Berlin".into()),"signature":{"uri":uri,"samplems":millis},"timestamp":timestamp,"context":{},"geolocation":{}});
    let result = json(
        client
            .post(endpoint)
            .header("X-Shazam-Platform", "IPHONE")
            .header("X-Shazam-AppVersion", "14.1.0")
            .header("Accept-Language", "en")
            .header("User-Agent", "Shazam/14.1.0 (iPhone; iOS 17.0; Scale/2.00)")
            .timeout(Duration::from_secs_f64(timeout))
            .json(&payload),
    )
    .await?;
    Ok(crate::model::Track::from_shazam(&result))
}
