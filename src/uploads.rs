use crate::{
    config::{ConfigStore, atomic_write, safe_relative},
    display,
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
pub fn child(root: &Path, relative: &str) -> Result<PathBuf> {
    ensure!(safe_relative(relative), "Invalid asset path");
    let path = root.join(relative).canonicalize()?;
    ensure!(
        path.starts_with(root.canonicalize()?) && path.is_file(),
        "Asset outside permitted directory"
    );
    Ok(path)
}
pub fn kind(s: &str) -> Result<&str> {
    ensure!(["normal", "turn"].contains(&s), "Invalid fallback kind");
    Ok(s)
}
pub fn images(root: &Path, cfg: &ConfigStore, k: &str) -> Result<Value> {
    kind(k)?;
    let dir = root.join("assets/fallback");
    let c = cfg.get();
    let selected = if k == "turn" {
        c.fallback.side_flip_image_path
    } else {
        c.fallback.image_path
    };
    let mut result = vec![];
    for folder in [dir.join(k), dir.clone()] {
        if !folder.is_dir() {
            continue;
        };
        for item in std::fs::read_dir(&folder)? {
            let item = item?;
            if !item.file_type()?.is_file() {
                continue;
            };
            let path = item.path();
            if !path
                .extension()
                .and_then(|s| s.to_str())
                .is_some_and(|e| ["png", "jpg", "jpeg"].contains(&e.to_lowercase().as_str()))
            {
                continue;
            };
            let filename = item.file_name().to_string_lossy().to_string();
            if folder == dir && filename.to_lowercase().starts_with("turn") != (k == "turn") {
                continue;
            };
            let relative = path
                .strip_prefix(root)?
                .to_string_lossy()
                .replace('\\', "/");
            let delete = path
                .strip_prefix(&dir)?
                .to_string_lossy()
                .replace('\\', "/");
            result.push(json!({"filename":filename,"delete_ref":delete,"path":relative,"url":format!("/uploads/{delete}"),"kind":k,"is_current":relative==selected}));
        }
    }
    result.sort_by_key(|v| v["filename"].as_str().unwrap_or("").to_owned());
    Ok(json!({"ok":true,"kind":k,"images":result}))
}
pub fn fonts(root: &Path, cfg: &ConfigStore) -> Result<Value> {
    let mut result = vec![];
    for item in std::fs::read_dir(root.join("assets/fonts"))? {
        let item = item?;
        if !item.file_type()?.is_file() {
            continue;
        };
        let filename = item.file_name().to_string_lossy().to_string();
        if !["ttf", "otf"]
            .iter()
            .any(|e| filename.to_lowercase().ends_with(e))
        {
            continue;
        };
        let path = format!("assets/fonts/{filename}");
        let encoded = url::form_urlencoded::byte_serialize(filename.as_bytes())
            .collect::<String>()
            .replace('+', "%20");
        result.push(json!({"filename":filename,"name":item.path().file_stem().unwrap_or_default().to_string_lossy(),"path":path,"is_current":cfg.get().image.font_path==path,"preview_url":format!("/api/font-preview/{encoded}"),"url":format!("/api/font-file/{encoded}")}));
    }
    result.sort_by_key(|v| v["filename"].as_str().unwrap_or("").to_owned());
    Ok(json!({"ok":true,"fonts":result}))
}
pub fn upload(root: &Path, bytes: &[u8], filename: &str, font: bool, k: &str) -> Result<Value> {
    ensure!(bytes.len() <= 4 * 1024 * 1024, "Upload exceeds 4 MiB");
    let id = uuid::Uuid::new_v4().simple();
    let (relative, data) = if font {
        let ext = Path::new(filename)
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase();
        ensure!(
            ["ttf", "otf"].contains(&ext.as_str()),
            "Expected a TTF or OTF font"
        );
        fontdue::Font::from_bytes(bytes, fontdue::FontSettings::default())
            .map_err(|e| anyhow::anyhow!("Invalid font: {e}"))?;
        (format!("assets/fonts/font_{id}.{ext}"), bytes.to_vec())
    } else {
        kind(k)?;
        let img = display::decode(bytes)?;
        ensure!(
            img.width() <= 4096 && img.height() <= 4096,
            "Image is too large"
        );
        let data = display::png(
            img.resize_exact(64, 64, image::imageops::FilterType::Lanczos3)
                .to_rgb8(),
        )?;
        (format!("assets/fallback/{k}/fallback_{id}.png"), data)
    };
    atomic_write(&root.join(&relative), &data)?;
    Ok(if font {
        json!({"ok":true,"font_path":relative,"path":relative,"filename":relative.rsplit('/').next()})
    } else {
        json!({"ok":true,"image_path":relative,"path":relative,"filename":relative.rsplit('/').next(),"url":relative.replacen("assets/fallback","/uploads",1),"kind":k})
    })
}
pub fn delete(root: &Path, cfg: &ConfigStore, name: &str, font: bool) -> Result<()> {
    let base = if font {
        "assets/fonts"
    } else {
        "assets/fallback"
    };
    ensure!(!font || !name.contains('/'), "Invalid font filename");
    let p = child(&root.join(base), name)?;
    let relative = p
        .strip_prefix(root.canonicalize()?)?
        .to_string_lossy()
        .replace('\\', "/");
    let c = cfg.get();
    let defaults = crate::config::Config::default();
    ensure!(
        ![
            defaults.image.font_path,
            defaults.fallback.image_path,
            defaults.fallback.side_flip_image_path
        ]
        .contains(&relative),
        "Bundled default assets cannot be deleted"
    );
    let update = if font && c.image.font_path == relative {
        json!({"image":{"font_path":"assets/fonts/vinylpixel.ttf"}})
    } else if c.fallback.image_path == relative {
        json!({"fallback":{"image_path":"assets/fallback/normal/Fallback.png"}})
    } else if c.fallback.side_flip_image_path == relative {
        json!({"fallback":{"side_flip_image_path":"assets/fallback/turn/turn_record.png"}})
    } else {
        json!({})
    };
    cfg.update(update, false)?;
    std::fs::remove_file(p)?;
    Ok(())
}
// Render directly to the preview canvas instead of reusing the 64px Pixoo
// text sprite. The gallery needs a different baseline, font size and aspect
// ratio; reusing the sprite made glyphs tiny and cut off after CSS scaling.
fn draw_preview_text(
    image: &mut image::RgbImage,
    font: &fontdue::Font,
    text: &str,
    size: f32,
    left: i32,
    top: i32,
    color: [u8; 3],
) {
    let ascent = font
        .horizontal_line_metrics(size)
        .map_or(size, |metrics| metrics.ascent);
    let baseline = top + ascent.round() as i32;
    let mut pen_x = left as f32;

    for ch in text.chars().take(120) {
        let (metrics, bitmap) = font.rasterize(ch, size);
        let glyph_x = pen_x.round() as i32 + metrics.xmin;
        let glyph_y = baseline - metrics.height as i32 - metrics.ymin;
        for y in 0..metrics.height {
            let dy = glyph_y + y as i32;
            if dy < 0 || dy >= image.height() as i32 {
                continue;
            }
            for x in 0..metrics.width {
                let dx = glyph_x + x as i32;
                if dx < 0 || dx >= image.width() as i32 {
                    continue;
                }
                // Hard edges are intentional: these previews represent fonts
                // used on a 64x64 pixel display, not smoothed vector text.
                if bitmap[y * metrics.width + x] >= 128 {
                    image.put_pixel(dx as u32, dy as u32, image::Rgb(color));
                }
            }
        }
        pen_x += metrics.advance_width;
    }
}

pub fn font_preview(root: &Path, name: &str) -> Result<Vec<u8>> {
    ensure!(!name.contains(['/', '\\']), "Invalid font name");
    let path = child(&root.join("assets/fonts"), name)?;
    let font = fontdue::Font::from_bytes(std::fs::read(&path)?, fontdue::FontSettings::default())
        .map_err(|e| anyhow::anyhow!("Invalid preview font: {e}"))?;

    // Match the original Python gallery's 540x132 preview. The CSS already
    // uses this aspect ratio, so the browser no longer zooms and crops it.
    const WIDTH: u32 = 540;
    const HEIGHT: u32 = 132;
    let mut image = image::RgbImage::from_pixel(WIDTH, HEIGHT, image::Rgb([18, 18, 25]));
    draw_preview_text(&mut image, &font, "VINYLPI64", 30., 22, 20, [248, 246, 250]);
    draw_preview_text(
        &mut image,
        &font,
        "NOW PLAYING  •  SIDE B  •  01:23",
        18.,
        22,
        76,
        [245, 197, 66],
    );
    for x in 22..(WIDTH - 22) {
        image.put_pixel(x, 112, image::Rgb([58, 54, 68]));
    }

    // The small label intentionally uses a fixed UI font rather than the
    // previewed font, which may not contain all filename characters.
    if let Ok(ui_font) = display::font(root, "assets/fonts/VCR_OSD_MONO_1.001.ttf") {
        let label = path
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .chars()
            .take(22)
            .collect::<String>();
        let label_width = label
            .chars()
            .map(|ch| ui_font.metrics(ch, 9.).advance_width)
            .sum::<f32>()
            .ceil() as i32;
        draw_preview_text(
            &mut image,
            &ui_font,
            &label,
            9.,
            (WIDTH as i32 - 22 - label_width).max(22),
            114,
            [177, 171, 187],
        );
    }
    display::png(image)
}
pub fn read(root: &Path, name: &str) -> Result<Vec<u8>> {
    let p = child(root, name)?;
    ensure!(p.metadata()?.len() <= 8 * 1024 * 1024, "Asset too large");
    std::fs::read(p).context("Read asset")
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_traversal() {
        let d = tempfile::tempdir().unwrap();
        for p in ["../secret", "/etc/passwd", "a\\b", "C:/x"] {
            assert!(child(d.path(), p).is_err());
        }
    }

    #[test]
    fn preview_matches_gallery_dimensions() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"));
        let bytes = font_preview(root, "vinylpixel.ttf").unwrap();
        let image = image::load_from_memory_with_format(&bytes, image::ImageFormat::Png).unwrap();
        assert_eq!((image.width(), image.height()), (540, 132));
    }
}
