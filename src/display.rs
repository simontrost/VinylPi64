use crate::{
    config::{Config, ConfigStore, local_ip},
    db::Db,
    model::Track,
    net,
};
use anyhow::{Context, Result, ensure};
use base64::Engine;
use image::{DynamicImage, Rgb, RgbImage};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, watch};

pub fn decode(data: &[u8]) -> Result<DynamicImage> {
    let mut r = image::ImageReader::new(std::io::Cursor::new(data)).with_guessed_format()?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(8192);
    limits.max_image_height = Some(8192);
    limits.max_alloc = Some(64 * 1024 * 1024);
    r.limits(limits);
    Ok(r.decode()?)
}
pub fn png(img: RgbImage) -> Result<Vec<u8>> {
    let mut out = std::io::Cursor::new(Vec::new());
    DynamicImage::ImageRgb8(img).write_to(&mut out, image::ImageFormat::Png)?;
    Ok(out.into_inner())
}
pub fn font(root: &Path, path: &str) -> Result<fontdue::Font> {
    let p = root.join(path);
    let canonical = p.canonicalize()?;
    ensure!(
        canonical.starts_with(root.join("assets").canonicalize()?),
        "Font outside asset directory"
    );
    let bytes = std::fs::read(canonical)?;
    fontdue::Font::from_bytes(bytes, fontdue::FontSettings::default())
        .map_err(|e| anyhow::anyhow!("Invalid font: {e}"))
}
pub fn text_sprite(
    font: &fontdue::Font,
    text: &str,
    height: f32,
    color: [u8; 3],
    bg: [u8; 3],
) -> RgbImage {
    let size = (1..=48)
        .min_by_key(|s| (font.metrics('A', *s as f32).height as i32 - height as i32).abs())
        .unwrap_or(8) as f32;
    let width = text
        .chars()
        .take(300)
        .map(|c| font.metrics(c, size).advance_width)
        .sum::<f32>()
        .ceil()
        .clamp(1., 2048.) as u32;
    let mut img = RgbImage::from_pixel(width, height as u32 + 6, Rgb(bg));
    let mut x = 0f32;
    for c in text.chars().take(300) {
        let (m, bitmap) = font.rasterize(c, size);
        let top = height as i32 - m.height as i32 - m.ymin;
        for gy in 0..m.height {
            for gx in 0..m.width {
                let px = x as i32 + m.xmin + gx as i32;
                let py = top + gy as i32;
                if px >= 0 && py >= 0 && px < width as i32 && py < img.height() as i32 {
                    let alpha = bitmap[gy * m.width + gx] as f32 / 255.;
                    let mut rgb = [0; 3];
                    for i in 0..3 {
                        rgb[i] = (bg[i] as f32 * (1. - alpha) + color[i] as f32 * alpha) as u8;
                    }
                    img.put_pixel(px as u32, py as u32, Rgb(rgb));
                }
            }
        }
        x += m.advance_width;
    }
    img
}
pub fn dominant(cover: &RgbImage) -> [u8; 3] {
    let mut bins = std::collections::BTreeMap::<[u8; 3], usize>::new();
    for p in cover.pixels() {
        let k = [
            p[0] / 32 * 32 + 16,
            p[1] / 32 * 32 + 16,
            p[2] / 32 * 32 + 16,
        ];
        *bins.entry(k).or_default() += 1;
    }
    bins.into_iter()
        .max_by_key(|(c, n)| {
            let max = *c.iter().max().unwrap() as usize;
            let min = *c.iter().min().unwrap() as usize;
            n * (32 + max - min)
        })
        .map(|(c, _)| c)
        .unwrap_or([40, 40, 40])
}
pub struct Composition {
    pub base: RgbImage,
    pub lines: Vec<(RgbImage, u32)>,
    pub background: [u8; 3],
}
impl Composition {
    pub fn new(root: &Path, cfg: &Config, t: &Track, cover: DynamicImage) -> Result<Self> {
        let c = &cfg.image;
        let cover = cover
            .resize_exact(64, 64, image::imageops::FilterType::Triangle)
            .to_rgb8();
        let mut bg = if c.use_dynamic_bg {
            dominant(&cover)
        } else {
            [
                c.manual_bg_color[0],
                c.manual_bg_color[1],
                c.manual_bg_color[2],
            ]
        };
        let mut fg = if c.use_dynamic_text_color {
            if 0.2126 * bg[0] as f64 + 0.7152 * bg[1] as f64 + 0.0722 * bg[2] as f64 > 128. {
                [0, 0, 0]
            } else {
                [255, 255, 255]
            }
        } else {
            [c.text_color[0], c.text_color[1], c.text_color[2]]
        };
        if c.invert_dynamic_colors {
            std::mem::swap(&mut fg, &mut bg)
        };
        let fields = [
            (c.show_artist, t.artist.as_str()),
            (c.show_title, t.title.as_str()),
            (c.show_album, t.album.as_deref().unwrap_or("")),
        ]
        .into_iter()
        .filter(|(show, _)| *show)
        .map(|(_, text)| {
            if c.uppercase {
                text.to_uppercase()
            } else {
                text.to_string()
            }
        })
        .collect::<Vec<_>>();
        let text_height = fields.len() as u32 * c.font_size as u32
            + fields.len().saturating_sub(1) as u32 * c.line_spacing_margin as u32;
        let mut y = c.top_margin as u32;
        let mut base = RgbImage::from_pixel(64, 64, Rgb(bg));
        if c.show_cover {
            let available = 64u32.saturating_sub(
                y + text_height
                    + if fields.is_empty() {
                        0
                    } else {
                        c.margin_image_text as u32
                    },
            );
            let size = (c.cover_size as u32).min(available).max(1);
            let resized =
                image::imageops::resize(&cover, size, size, image::imageops::FilterType::Triangle);
            image::imageops::overlay(&mut base, &resized, ((64 - size) / 2) as i64, y as i64);
            y += size + c.margin_image_text as u32;
        }
        let font = font(root, &c.font_path)?;
        let mut lines = vec![];
        for text in fields {
            lines.push((text_sprite(&font, &text, c.font_size as f32, fg, bg), y));
            y += c.font_size as u32 + c.line_spacing_margin as u32;
        }
        Ok(Self {
            base,
            lines,
            background: bg,
        })
    }
    pub fn frame(&self, offset: u32) -> RgbImage {
        let mut frame = self.base.clone();
        for (sprite, y) in &self.lines {
            if sprite.width() <= 64 {
                image::imageops::overlay(
                    &mut frame,
                    sprite,
                    ((64 - sprite.width()) / 2) as i64,
                    *y as i64,
                )
            } else {
                let cycle = sprite.width() + 20;
                let x = -((offset % cycle) as i64);
                image::imageops::overlay(&mut frame, sprite, x, *y as i64);
                image::imageops::overlay(&mut frame, sprite, x + cycle as i64, *y as i64);
            }
        }
        frame
    }
    pub fn animated(&self) -> bool {
        self.lines.iter().any(|(s, _)| s.width() > 64)
    }
}
/// Fill the single-letter badge of the configurable side-flip graphic.
/// The bundled image has the word SIDE and a blank badge for the target side.
fn side_flip_frame(root: &Path, mut image: RgbImage, next_side: &str) -> Result<RgbImage> {
    let side = next_side
        .chars()
        .next()
        .filter(char::is_ascii_alphabetic)
        .unwrap_or('?')
        .to_ascii_uppercase();
    // Use pixels from the adjacent badge and label, matching the reusable
    // original asset without hard-coding its palette.
    let mut background = [0, 0, 8];
    let mut background_score = u16::MAX;
    for y in 53..=59 {
        for x in 37..=43 {
            let pixel = image.get_pixel(x, y).0;
            let score = pixel.iter().map(|v| u16::from(*v)).sum::<u16>();
            if score < background_score {
                background = pixel;
                background_score = score;
            }
        }
    }
    let mut accent = [224, 151, 44];
    let mut accent_score = 0u16;
    for y in 54..=58 {
        for x in 21..=36 {
            let pixel = image.get_pixel(x, y).0;
            let max = *pixel.iter().max().unwrap_or(&0) as u16;
            let min = *pixel.iter().min().unwrap_or(&0) as u16;
            let score = (max - min) * 3 + pixel.iter().map(|v| u16::from(*v)).sum::<u16>();
            if score > accent_score {
                accent = pixel;
                accent_score = score;
            }
        }
    }
    for y in 54..=58 {
        for x in 38..=42 {
            image.put_pixel(x, y, Rgb(background));
        }
    }
    let font = font(root, "assets/fonts/vinylpixel.ttf")?;
    let sprite = text_sprite(&font, &side.to_string(), 5., accent, background);
    let width = sprite.width().min(5);
    // Keep all drawing inside the blank badge.
    for y in 0..5u32.min(sprite.height()) {
        for x in 0..width {
            image.put_pixel(38 + (5 - width) / 2 + x, 54 + y, *sprite.get_pixel(x, y));
        }
    }
    Ok(image)
}

pub struct Pixoo {
    client: reqwest::Client,
    pub cfg: Arc<ConfigStore>,
    gate: Mutex<()>,
    last_scan: Mutex<Option<Instant>>,
}
impl Pixoo {
    pub fn new(client: reqwest::Client, cfg: Arc<ConfigStore>) -> Self {
        Self {
            client,
            cfg,
            gate: Mutex::new(()),
            last_scan: Mutex::new(None),
        }
    }
    async fn post_at(&self, ip: &str, cmd: &Value, seconds: f64) -> Result<Value> {
        local_ip(ip)?;
        let v = net::json(
            self.client
                .post(format!("http://{ip}/post"))
                .timeout(Duration::from_secs_f64(seconds))
                .json(cmd),
        )
        .await?;
        ensure!(
            v["error_code"].as_i64().unwrap_or(0) == 0,
            "Pixoo rejected command"
        );
        Ok(v)
    }
    pub async fn scan(&self, prefix: &str) -> Result<Vec<Value>> {
        use futures_util::{StreamExt, stream};
        local_ip(&format!("{prefix}1"))?;
        let c = self.cfg.get();
        let start = c.divoom.discovery.ip_range_start as u32;
        let end = c.divoom.discovery.ip_range_end as u32;
        let results=stream::iter(start..=end).map(|n|async move{let ip=format!("{prefix}{n}");let v=self.post_at(&ip,&json!({"Command":"Channel/GetAllConf"}),0.4).await.ok()?;if v.get("Brightness").is_none() && v.get("SelectIndex").is_none(){return None};Some(json!({"ip":ip,"name":v["DeviceName"].as_str().unwrap_or("Pixoo 64"),"device_name":v["DeviceName"]}))}).buffer_unordered(8).filter_map(|v|async{v}).collect().await;
        Ok(results)
    }
    async fn post(&self, cmd: &Value) -> Result<Value> {
        let c = self.cfg.get();
        if !c.divoom.ip.is_empty() {
            match self.post_at(&c.divoom.ip, cmd, c.divoom.timeout).await {
                Ok(v) => return Ok(v),
                Err(e) if !c.divoom.discovery.enabled => return Err(e),
                Err(_) => {}
            }
        }
        ensure!(c.divoom.discovery.enabled, "Pixoo address not configured");
        let mut last = self.last_scan.lock().await;
        ensure!(
            last.is_none_or(|t| t.elapsed() > Duration::from_secs(60)),
            "Pixoo unavailable; discovery cooldown active"
        );
        *last = Some(Instant::now());
        let devices = self.scan(&c.divoom.discovery.subnet_prefix).await?;
        let found = devices
            .iter()
            .find(|d| d["name"] == c.divoom.device_name)
            .or_else(|| {
                if devices.len() == 1 {
                    devices.first()
                } else {
                    None
                }
            })
            .context("No unique Pixoo found; select a device in Settings")?;
        let ip = found["ip"].as_str().context("Pixoo IP")?;
        self.cfg.update(json!({"divoom":{"ip":ip}}), false)?;
        self.post_at(ip, cmd, c.divoom.timeout).await
    }
    pub async fn command(&self, cmd: Value) -> Result<Value> {
        let _guard = self.gate.lock().await;
        self.post(&cmd).await
    }
    async fn frame(&self, frame: &RgbImage, revision: u64, current: &AtomicU64) -> Result<()> {
        let _guard = self.gate.lock().await;
        if current.load(Ordering::SeqCst) != revision {
            return Ok(());
        };
        let data = base64::engine::general_purpose::STANDARD.encode(frame.as_raw());
        if self.cfg.get().divoom.auto_reset_gif_id {
            self.post(&json!({"Command":"Draw/ResetHttpGifId"})).await?;
        }
        let id = self.post(&json!({"Command":"Draw/GetHttpGifId"})).await?;
        let id = id["PicId"].as_i64().or(id["PicID"].as_i64()).unwrap_or(1);
        self.post(&json!({"Command":"Draw/SendHttpGif","PicNum":1,"PicWidth":64,"PicOffset":0,"PicID":id,"PicSpeed":100,"PicSpped":100,"PicData":data})).await?;
        Ok(())
    }
    pub async fn cloud(&self, path: &str, payload: Option<Value>) -> Result<Value> {
        let u = format!("https://app.divoom-gz.com{path}");
        let req = if let Some(v) = payload {
            self.client.post(u).json(&v)
        } else {
            self.client.get(u)
        };
        let v = net::json(req).await?;
        ensure!(
            v["ReturnCode"].as_i64().unwrap_or(0) == 0,
            "Divoom cloud returned an error"
        );
        Ok(v)
    }
}
#[derive(Clone)]
pub enum Content {
    Hold,
    Fallback(bool),
    SideFlip(String),
    Track(Box<Track>),
}
pub struct DisplayRuntime {
    pub root: PathBuf,
    pub data: PathBuf,
    pub port: u16,
    pub db: Db,
    pub status: watch::Sender<Value>,
    pub cancel: tokio_util::sync::CancellationToken,
}
pub struct Display {
    pub pixoo: Arc<Pixoo>,
    tx: watch::Sender<(u64, Content)>,
    generation: Arc<AtomicU64>,
}
impl Display {
    pub fn new(pixoo: Arc<Pixoo>) -> (Self, watch::Receiver<(u64, Content)>) {
        let (tx, rx) = watch::channel((0, Content::Hold));
        (
            Self {
                pixoo,
                tx,
                generation: Arc::new(AtomicU64::new(0)),
            },
            rx,
        )
    }
    pub fn show(&self, content: Content) {
        let n = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        self.tx.send_replace((n, content));
    }
    pub fn refresh(&self) {
        let content = self.tx.borrow().1.clone();
        self.show(content);
    }
    pub async fn run(
        self: Arc<Self>,
        mut rx: watch::Receiver<(u64, Content)>,
        runtime: DisplayRuntime,
    ) {
        let DisplayRuntime {
            root,
            data,
            port,
            db,
            status,
            cancel,
        } = runtime;
        // Retry transient Pixoo failures quickly, while backing off if the
        // device stays offline. A new display command resets the backoff.
        let mut retry_delay = Duration::from_secs(2);
        loop {
            let (revision, content) = rx.borrow_and_update().clone();
            let cfg = self.pixoo.cfg.get();
            let result = async {
                let mut composition = None;
                let mut still = None;
                match content {
                    Content::Hold => return Ok::<(), anyhow::Error>(()),
                    Content::Fallback(turn) => {
                        let p = if turn {
                            &cfg.fallback.side_flip_image_path
                        } else {
                            &cfg.fallback.image_path
                        };
                        if p.is_empty() {
                            return Ok(());
                        };
                        let path = root.join(p).canonicalize()?;
                        ensure!(
                            path.starts_with(root.join("assets").canonicalize()?),
                            "Fallback outside assets"
                        );
                        still = Some(
                            decode(&std::fs::read(path)?)?
                                .resize_exact(64, 64, image::imageops::FilterType::Triangle)
                                .to_rgb8(),
                        );
                    }
                    Content::SideFlip(next_side) => {
                        let path = root.join(&cfg.fallback.side_flip_image_path).canonicalize()?;
                        ensure!(
                            path.starts_with(root.join("assets").canonicalize()?),
                            "Side-flip prompt outside assets"
                        );
                        let image = decode(&std::fs::read(path)?)?
                            .resize_exact(64, 64, image::imageops::FilterType::Nearest)
                            .to_rgb8();
                        still = Some(side_flip_frame(&root, image, &next_side)?);
                    }
                    Content::Track(t) => {
                        // Artwork is optional. A CDN outage or a broken URL must not
                        // suppress the Pixoo update for an otherwise valid song.
                        let cover = if let Some(url) = &t.cover_url {
                            let downloaded = async {
                                let u = url::Url::parse(url)?;
                                ensure!(["https", "http"].contains(&u.scheme()), "Invalid cover URL");
                                let bytes = net::bytes(
                                    self.pixoo.client.get(u).send().await?,
                                    8 * 1024 * 1024,
                                )
                                .await?;
                                decode(&bytes)
                            }
                            .await;
                            match downloaded {
                                Ok(image) => image,
                                Err(e) => {
                                    db.log("WARNING", &format!("Album artwork unavailable; using blank cover: {e}"));
                                    DynamicImage::new_rgb8(64, 64)
                                }
                            }
                        } else {
                            DynamicImage::new_rgb8(64, 64)
                        };
                        let c = Composition::new(&root, &cfg, &t, cover)?;
                        status.send_if_modified(|v| {
                            if v["artist"] == t.artist && v["title"] == t.title {
                                v["bg_color"] = json!(c.background);
                                v["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
                                true
                            } else {
                                false
                            }
                        });
                        composition = Some(c);
                    }
                }
                if let Some(c) = &composition
                    && cfg.homeassistant.use_ha
                    && !cfg.homeassistant.base_url.is_empty()
                {
                    let [r, g, b] = c.background;
                    let url = format!(
                        "{}/api/webhook/{}",
                        cfg.homeassistant.base_url.trim_end_matches('/'),
                        cfg.homeassistant.webhook_id
                    );
                    if let Err(e) = self
                        .pixoo
                        .client
                        .post(url)
                        .timeout(Duration::from_secs(3))
                        .json(&json!({"r":r,"g":g,"b":b}))
                        .send()
                        .await
                        .and_then(reqwest::Response::error_for_status)
                    {
                        db.log(
                            "WARNING",
                            &format!("Home Assistant color sync failed: {}", e.without_url()),
                        );
                    }
                }
                if cfg.divoom.animation_mode == "gif_url"
                    && let Some(c) = &composition
                    && c.animated()
                {
                    let token = uuid::Uuid::new_v4().simple().to_string();
                    let dir = data.join("animations");
                    std::fs::create_dir_all(&dir)?;
                    let file = std::fs::File::create(dir.join(format!("{token}.gif")))?;
                    let mut encoder = image::codecs::gif::GifEncoder::new(file);
                    encoder.set_repeat(image::codecs::gif::Repeat::Infinite)?;
                    for offset in (0..c
                        .lines
                        .iter()
                        .map(|(s, _)| s.width() + 20)
                        .max()
                        .unwrap_or(64)
                        .min(512))
                        .step_by(2)
                    {
                        let rgba = DynamicImage::ImageRgb8(c.frame(offset)).into_rgba8();
                        encoder.encode_frame(image::Frame::from_parts(
                            rgba,
                            0,
                            0,
                            image::Delay::from_numer_denom_ms(
                                (2000. / cfg.image.marquee_speed) as u32,
                                1,
                            ),
                        ))?;
                    }
                    drop(encoder);
                    // Keep disk use bounded; a previously served GIF may remain cached by Pixoo.
                    let mut files = std::fs::read_dir(&dir)?
                        .filter_map(Result::ok)
                        .filter(|e| e.path().extension().is_some_and(|x| x == "gif"))
                        .collect::<Vec<_>>();
                    files.sort_by_key(|e| e.metadata().and_then(|m| m.modified()).ok());
                    let remove = files.len().saturating_sub(8);
                    for e in files.into_iter().take(remove) {
                        std::fs::remove_file(e.path())?;
                    }
                    let base = if let Ok(u) = std::env::var("VINYLPI_PUBLIC_URL") {
                        u
                    } else {
                        let sock = std::net::UdpSocket::bind("0.0.0.0:0")?;
                        sock.connect(format!("{}:80", self.pixoo.cfg.get().divoom.ip))?;
                        format!("http://{}:{port}", sock.local_addr()?.ip())
                    };
                    let url = format!(
                        "{}/api/pixoo/animation/{token}.gif",
                        base.trim_end_matches('/')
                    );
                    ensure!(url.len() <= 255, "Pixoo GIF URL too long");
                    if self.generation.load(Ordering::SeqCst) == revision {
                        self.pixoo
                            .command(
                                json!({"Command":"Device/PlayTFGif","FileType":2,"FileName":url}),
                            )
                            .await?;
                    }
                    return Ok(());
                }
                let mut offset = 0;
                loop {
                    if self.generation.load(Ordering::SeqCst) != revision || cancel.is_cancelled() {
                        break;
                    };
                    let frame = if let Some(c) = &composition {
                        c.frame(offset)
                    } else {
                        still.as_ref().context("No frame")?.clone()
                    };
                    self.pixoo.frame(&frame, revision, &self.generation).await?;
                    if !composition.as_ref().is_some_and(Composition::animated) {
                        break;
                    };
                    offset += 1;
                    tokio::time::sleep(Duration::from_secs_f64(
                        (1. / cfg.image.marquee_speed).max(0.05),
                    ))
                    .await;
                }
                Ok(())
            };
            let mut wait = Duration::from_secs(30);
            tokio::select! {
                biased;
                _ = cancel.cancelled() => break,
                changed = rx.changed() => {
                    if changed.is_err() { break; }
                    retry_delay = Duration::from_secs(2);
                    continue;
                }
                result = result => {
                    if let Err(e) = result {
                        db.log("WARNING", &format!("Display update failed; retrying: {e}"));
                        wait = retry_delay;
                        retry_delay = (retry_delay * 2).min(Duration::from_secs(30));
                    } else {
                        retry_delay = Duration::from_secs(2);
                    }
                }
            }
            tokio::select! {
                _ = cancel.cancelled() => break,
                changed = rx.changed() => {
                    if changed.is_err() { break; }
                    retry_delay = Duration::from_secs(2);
                }
                _ = tokio::time::sleep(wait) => {
                    if !matches!(rx.borrow().1, Content::Hold) { continue; }
                }
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn blank_image_has_exact_rgb_frame_size() {
        let c = Composition {
            base: RgbImage::from_pixel(64, 64, Rgb([12, 34, 56])),
            lines: vec![],
            background: [12, 34, 56],
        };
        assert_eq!(c.frame(0).as_raw().len(), 12288);
        assert_eq!(c.frame(20).get_pixel(0, 0).0, [12, 34, 56]);
    }
    #[test]
    fn rejects_invalid_image() {
        assert!(decode(b"not an image").is_err());
    }
}

#[cfg(test)]
mod side_flip_tests {
    use super::*;
    #[test]
    fn side_flip_badge_has_valid_frame_dimensions() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let image = RgbImage::from_pixel(64, 64, Rgb([20, 20, 20]));
        let frame = side_flip_frame(&root, image, "D").unwrap();
        assert_eq!(frame.as_raw().len(), 64 * 64 * 3);
    }
}
