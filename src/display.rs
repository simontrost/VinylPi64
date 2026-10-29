use crate::{
    config::{Config, ConfigStore, local_ip},
    db::Db,
    model::{Mode, Track},
    net,
};
use anyhow::{Context, Result, ensure};
use base64::Engine;
use image::{DynamicImage, Rgb, RgbImage};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashMap},
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
/// A marquee position is measured in pixels from the start of playback,
/// rather than in frames sent to the Pixoo. HTTP latency can be substantial,
/// so a fixed one-pixel step per request makes scroll speed ineffective.
fn marquee_offset(elapsed: Duration, pixels_per_second: f64) -> u32 {
    (elapsed.as_secs_f64() * pixels_per_second)
        .floor()
        .clamp(0.0, u32::MAX as f64) as u32
}

/// Wait only until the next distinct pixel. This avoids repeatedly sending
/// identical frames at slow speeds, while allowing fast speeds to use all
/// throughput available from the Pixoo's HTTP endpoint.
fn time_to_next_pixel(elapsed: Duration, pixels_per_second: f64) -> Duration {
    let current = marquee_offset(elapsed, pixels_per_second);
    let seconds =
        ((current as f64 + 1.0) / pixels_per_second - elapsed.as_secs_f64()).clamp(0.001, 0.250);
    Duration::from_secs_f64(seconds)
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
    fn scroll_cycle(&self) -> u32 {
        self.lines.iter().filter(|(s, _)| s.width() > 64)
            .map(|(s, _)| s.width() + 20).max().unwrap_or(64)
    }
    pub fn frame(&self, offset: u32) -> RgbImage {
        let mut frame = self.base.clone();
        let cycle = self.scroll_cycle();
        for (sprite, y) in &self.lines {
            if sprite.width() <= 64 {
                image::imageops::overlay(
                    &mut frame,
                    sprite,
                    ((64 - sprite.width()) / 2) as i64,
                    *y as i64,
                )
            } else {
                // Every overflowing line shares the same period. A shorter
                // artist waits for the longer title instead of drifting.
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
/// Build one adaptive palette for the *entire* Pixoo GIF. The generic GIF
/// encoder derives a new palette for each frame: even unchanged artwork then
/// acquires slightly different colors, causing visible flicker.
fn shared_gif_palette(composition: &Composition) -> Vec<u8> {
    let mut histogram = BTreeMap::<[u8; 3], (u64, [u64; 3])>::new();
    for (img, weight) in std::iter::once((&composition.base, 4_u64))
        .chain(composition.lines.iter().map(|(sprite, _)| (sprite, 1_u64)))
    {
        for pixel in img.pixels() {
            let rgb = pixel.0;
            let bucket = [rgb[0] >> 3, rgb[1] >> 3, rgb[2] >> 3];
            let entry = histogram.entry(bucket).or_default();
            entry.0 += weight;
            for (sum, value) in entry.1.iter_mut().zip(rgb) {
                *sum += u64::from(value) * weight;
            }
        }
    }
    let mut groups = histogram.into_iter().collect::<Vec<_>>();
    groups.sort_by(|a, b| b.1.0.cmp(&a.1.0).then_with(|| a.0.cmp(&b.0)));
    let mut palette = vec![composition.background];
    for (_, (count, sums)) in groups {
        if palette.len() == 256 { break; }
        let color = sums.map(|sum| (sum / count) as u8);
        if !palette.contains(&color) { palette.push(color); }
    }
    // A 256-color global table eliminates palette changes between frames.
    let mut bytes = palette.into_iter().flatten().collect::<Vec<_>>();
    bytes.resize(256 * 3, 0);
    bytes
}

fn gif_indices(frame: &RgbImage, palette: &[u8], cache: &mut HashMap<[u8; 3], u8>) -> Vec<u8> {
    frame.pixels().map(|p| {
        let rgb = p.0;
        *cache.entry(rgb).or_insert_with(|| {
            (0..256usize)
                .min_by_key(|i| {
                    let idx = *i * 3;
                    (0..3).map(|channel| {
                        let distance = i32::from(rgb[channel]) - i32::from(palette[idx + channel]);
                        distance * distance
                    }).sum::<i32>()
                }).unwrap_or(0) as u8
        })
    }).collect()
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
fn save_debug_images(root: &std::path::Path, cfg: &Config, frame: &RgbImage) -> anyhow::Result<()> {
    for (name, scale) in [
        (cfg.debug.pixoo_frame_path.as_str(), 1u32),
        (cfg.debug.preview_path.as_str(), cfg.image.preview_scale as u32),
    ] {
        if name.is_empty() { continue; }
        anyhow::ensure!(crate::config::safe_relative(name) && name.starts_with("data/"),
            "Debug PNG must be a relative data/ path");
        let path = root.join(name);
        if let Some(parent) = path.parent() { std::fs::create_dir_all(parent)?; }
        let preview = if scale <= 1 { frame.clone() } else {
            image::imageops::resize(frame, 64*scale, 64*scale, image::imageops::FilterType::Nearest)
        };
        preview.save(path)?;
    }
    Ok(())
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
                        let path = root
                            .join(&cfg.fallback.side_flip_image_path)
                            .canonicalize()?;
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
                                ensure!(
                                    ["https", "http"].contains(&u.scheme()),
                                    "Invalid cover URL"
                                );
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
                                    db.log(
                                        "WARNING",
                                        &format!(
                                            "Album artwork unavailable; using blank cover: {e}"
                                        ),
                                    );
                                    DynamicImage::new_rgb8(64, 64)
                                }
                            }
                        } else {
                            DynamicImage::new_rgb8(64, 64)
                        };
                        let c = Composition::new(&root, &cfg, &t, cover)?;
                        let mut persisted_status: Option<(Mode, Value)> = None;
                        status.send_if_modified(|v| {
                            if v["artist"] == t.artist && v["title"] == t.title {
                                v["bg_color"] = json!(c.background);
                                v["updated_at"] = json!(chrono::Utc::now().timestamp_millis());
                                let mode = match v["source"].as_str() {
                                    Some("vinyl") => Some(Mode::Vinyl),
                                    Some("spotify") => Some(Mode::Spotify),
                                    _ => None,
                                };
                                if let Some(mode) = mode {
                                    persisted_status = Some((mode, v.clone()));
                                }
                                true
                            } else {
                                false
                            }
                        });
                        if let Some((mode, value)) = persisted_status
                            && let Err(e) = db.save_status(mode, &value)
                        {
                            db.log("ERROR", &format!("Saving tinted dashboard status failed: {e}"));
                        }
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
                // Preserve the legacy debug export options. One diagnostic PNG
                // per content revision, never one file per scrolling frame.
                if !cfg.debug.pixoo_frame_path.is_empty() || !cfg.debug.preview_path.is_empty() {
                    let diagnostic = composition.as_ref().map(|c| c.frame(0)).or_else(|| still.clone());
                    if let Some(frame) = diagnostic
                        && let Err(e) = save_debug_images(&root, &cfg, &frame) {
                            db.log("WARNING", &format!("Debug image export failed: {e}"));
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
                    let palette = shared_gif_palette(c);
                    let mut encoder = gif::Encoder::new(file, 64, 64, &palette)?;
                    encoder.set_repeat(gif::Repeat::Infinite)?;
                    let cycle = c.scroll_cycle();
                    // Render the full shared cycle (never cut it off at 512px).
                    // Bound the frame count instead, so long titles remain
                    // seamless without exhausting the Pi Zero's memory.
                    let step = cycle.div_ceil(512).max(1) as usize;
                    let mut colors = HashMap::new();
                    for offset in (0..cycle).step_by(step) {
                        let rgb = c.frame(offset);
                        // GIF delay is in 1/100 sec; clamp ultra-fast settings.
                        let frame = gif::Frame {
                            width: 64,
                            height: 64,
                            delay: ((step as f64 * 100. / cfg.image.marquee_speed)
                                .round() as u16)
                                .max(2),
                            buffer: std::borrow::Cow::Owned(gif_indices(
                                &rgb,
                                &palette,
                                &mut colors,
                            )),
                            ..Default::default()
                        };
                        encoder.write_frame(&frame)?;
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
                let animated = composition.as_ref().is_some_and(Composition::animated);
                let scroll_started = Instant::now();
                let mut last_sent_offset = None;
                // Optional, low-overhead diagnostics. Enable on the Pi using
                // VINYLPI_PERF_LOG=1 to report *actual* successful Pixoo FPS.
                let perf_enabled = std::env::var_os("VINYLPI_PERF_LOG").is_some();
                let mut perf_started = Instant::now();
                let mut perf_frames = 0u64;
                let mut perf_send_duration = Duration::ZERO;
                loop {
                    if self.generation.load(Ordering::SeqCst) != revision || cancel.is_cancelled() {
                        break;
                    };
                    let elapsed = scroll_started.elapsed();
                    let offset = marquee_offset(elapsed, cfg.image.marquee_speed);
                    if animated && last_sent_offset == Some(offset) {
                        tokio::time::sleep(time_to_next_pixel(elapsed, cfg.image.marquee_speed))
                            .await;
                        continue;
                    }
                    let frame = if let Some(c) = &composition {
                        c.frame(offset)
                    } else {
                        still.as_ref().context("No frame")?.clone()
                    };
                    let send_started = Instant::now();
                    self.pixoo.frame(&frame, revision, &self.generation).await?;
                    last_sent_offset = Some(offset);
                    if perf_enabled && animated {
                        perf_frames += 1;
                        perf_send_duration += send_started.elapsed();
                        if perf_started.elapsed() >= Duration::from_secs(10) {
                            tracing::info!(
                                fps = perf_frames as f64 / perf_started.elapsed().as_secs_f64(),
                                avg_send_ms =
                                    perf_send_duration.as_secs_f64() * 1000.0 / perf_frames as f64,
                                requested_px_s = cfg.image.marquee_speed,
                                "Pixoo live-frame performance"
                            );
                            perf_started = Instant::now();
                            perf_frames = 0;
                            perf_send_duration = Duration::ZERO;
                        }
                    }
                    if !animated {
                        break;
                    };
                    tokio::time::sleep(Duration::from_secs_f64(cfg.image.sleep_seconds)).await;
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
    #[test]
    fn marquee_speed_is_elapsed_time_based_and_supports_200_px_s() {
        let elapsed = Duration::from_millis(125);
        assert_eq!(marquee_offset(elapsed, 20.0), 2);
        assert_eq!(marquee_offset(elapsed, 40.0), 5);
        assert_eq!(marquee_offset(elapsed, 200.0), 25);
        // Sending a frame must not increment the offset by a fixed one pixel.
        assert_eq!(marquee_offset(Duration::from_millis(260), 40.0), 10);
    }

    #[test]
    fn both_long_lines_share_a_cycle_and_restart_in_sync() {
        let short = RgbImage::from_pixel(90, 8, Rgb([255, 0, 0]));
        let long = RgbImage::from_pixel(150, 8, Rgb([0, 255, 0]));
        let c = Composition {
            base: RgbImage::from_pixel(64, 64, Rgb([0, 0, 0])),
            lines: vec![(short, 2), (long, 24)],
            background: [0, 0, 0],
        };
        assert_eq!(c.scroll_cycle(), 170);
        assert_eq!(c.frame(0), c.frame(170));
        assert_eq!(c.frame(30), c.frame(200));
        // The short line stays blank after leaving the left edge,
        // instead of restarting before the longer title finishes.
        assert_eq!(c.frame(115).get_pixel(3, 3).0, [0, 0, 0]);
    }

    #[test]
    fn global_gif_palette_keeps_stationary_cover_pixels_identical() {
        let mut base = RgbImage::from_pixel(64, 64, Rgb([12, 34, 56]));
        base.put_pixel(12, 12, Rgb([211, 48, 122]));
        let c = Composition { base, lines: vec![
            (RgbImage::from_pixel(90, 6, Rgb([255, 255, 255])), 50)
        ], background: [12, 34, 56] };
        let palette = shared_gif_palette(&c);
        let mut cache = HashMap::new();
        let a = gif_indices(&c.frame(0), &palette, &mut cache);
        let b = gif_indices(&c.frame(10), &palette, &mut cache);
        assert_eq!(palette.len(), 768);
        assert_eq!(a[12 * 64 + 12], b[12 * 64 + 12]);
    }

    #[test]
    fn marquee_waits_until_an_actual_pixel_change() {
        assert_eq!(
            time_to_next_pixel(Duration::from_millis(125), 20.0),
            Duration::from_millis(25)
        );
        assert!(time_to_next_pixel(Duration::ZERO, 200.0) <= Duration::from_millis(5));
        assert!(time_to_next_pixel(Duration::ZERO, 1.0) <= Duration::from_millis(250));
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
