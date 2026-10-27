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
pub fn font_preview(root: &Path, name: &str) -> Result<Vec<u8>> {
    ensure!(!name.contains('/'), "Invalid font name");
    let path = child(&root.join("assets/fonts"), name)?;
    let f = fontdue::Font::from_bytes(std::fs::read(path)?, fontdue::FontSettings::default())
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    let sprite = display::text_sprite(
        &f,
        "VINYLPI 64 Aa Bb 0123",
        12.,
        [255, 255, 255],
        [21, 21, 25],
    );
    let mut img = image::RgbImage::from_pixel(320, 40, image::Rgb([21, 21, 25]));
    image::imageops::overlay(&mut img, &sprite, 8, 10);
    display::png(img)
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
}
