use crate::{
    config::{Config, atomic_write},
    db::{Db, snapshot},
    model::Mode,
};
use anyhow::{Context, Result, ensure};
use std::{
    fs,
    path::{Path, PathBuf},
};

pub fn candidates(root: &Path) -> Result<Vec<String>> {
    let mut out = Vec::new();
    if root.join("data/config.json").exists() || root.join("data/vinylpi.db").exists() {
        out.push("legacy".into());
    }
    if root.join("data/profiles").is_dir() {
        for e in fs::read_dir(root.join("data/profiles"))? {
            let e = e?;
            if e.file_type()?.is_dir() {
                out.push(format!("profile:{}", e.file_name().to_string_lossy()));
            }
        }
    }
    out.sort();
    Ok(out)
}
pub fn migrate(root: &Path, selection: &str, destination: &Path) -> Result<PathBuf> {
    ensure!(
        !destination.exists(),
        "Destination already exists; migration never overwrites or merges data"
    );
    let source = if selection == "legacy" {
        root.join("data")
    } else {
        let key = selection
            .strip_prefix("profile:")
            .context("Select legacy or profile:<storage-key>")?;
        ensure!(
            !key.is_empty() && !key.contains(['/', '\\', ':']) && key != "." && key != "..",
            "Invalid profile storage key"
        );
        root.join("data/profiles").join(key)
    };
    ensure!(source.is_dir(), "Source does not exist");
    let cfg = if source.join("config.json").exists() {
        Config::from_value(serde_json::from_slice(&fs::read(
            source.join("config.json"),
        )?)?)?
    } else {
        Config::default()
    };
    // A separate directory is the commit boundary. Interrupted migrations never
    // expose half of a selected profile as the global configuration/database.
    let backup = root.join("data/migration-backups").join(format!(
        "{}-{}",
        chrono::Utc::now().format("%Y%m%dT%H%M%SZ"),
        uuid::Uuid::new_v4()
    ));
    fs::create_dir_all(&backup)?;
    for name in ["config.json", "stats.json", "status.json"] {
        let p = source.join(name);
        if p.is_file() {
            fs::copy(&p, backup.join(name))?;
        }
    }
    if source.join("vinylpi.db").exists() {
        snapshot(&source.join("vinylpi.db"), &backup.join("vinylpi.db"))?;
    }
    atomic_write(
        &backup.join("selection.json"),
        &serde_json::to_vec_pretty(
            &serde_json::json!({"source":selection,"path":source,"strategy":"explicit selection; other profiles remain untouched","utc":chrono::Utc::now()}),
        )?,
    )?;
    let parent = destination.parent().context("Destination needs a parent")?;
    fs::create_dir_all(parent)?;
    let stage = tempfile::Builder::new()
        .prefix(".migration-")
        .tempdir_in(parent)?;
    if backup.join("vinylpi.db").exists() {
        fs::copy(backup.join("vinylpi.db"), stage.path().join("vinylpi.db"))?;
    }
    if source.join("stats.json").exists() && !source.join("vinylpi.db").exists() {
        let raw = fs::read_to_string(backup.join("stats.json"))?;
        let db = Db::open(&stage.path().join("vinylpi.db"))?;
        crate::legacy::import(&db, &raw)?;
    }
    atomic_write(
        &stage.path().join("config.json"),
        &serde_json::to_vec_pretty(&cfg)?,
    )?;
    {
        let db = Db::open(&stage.path().join("vinylpi.db"))?;
        // The Python dashboard stored its last recognized vinyl song in
        // status.json. Import it once into the per-source status cache.
        if backup.join("status.json").is_file() && db.last_status(Mode::Vinyl)?.is_none() {
            let mut status: serde_json::Value = serde_json::from_slice(&fs::read(backup.join("status.json"))?)?;
            if status["artist"].as_str().is_some_and(|s| !s.is_empty())
                && status["title"].as_str().is_some_and(|s| !s.is_empty()) {
                    status["source"] = serde_json::json!("vinyl");
                    status["is_playing"] = serde_json::json!(false);
                    db.save_status(Mode::Vinyl, &status)?;
                }
        }
        db.with(|c| {
            c.execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")?;
            Ok(())
        })?;
    }
    atomic_write(
        &stage.path().join("migration.json"),
        &serde_json::to_vec(&serde_json::json!({"source":selection,"backup":backup}))?,
    )?;
    fs::rename(stage.path(), destination)?;
    Ok(backup)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selection_preserves_others_and_refuses_overwrite() {
        let r = tempfile::tempdir().unwrap();
        for key in ["a", "b"] {
            let p = r.path().join("data/profiles").join(key);
            fs::create_dir_all(&p).unwrap();
            fs::write(p.join("config.json"), "{}").unwrap();
            let db = Db::open(&p.join("vinylpi.db")).unwrap();
            db.with(|c| {
                c.execute(
                    "INSERT INTO songs(song_key,artist,title,play_count) VALUES(?,?,?,?)",
                    rusqlite::params![key, key, key, if key == "a" { 4 } else { 8 }],
                )?;
                Ok(())
            })
            .unwrap();
        }
        let dest = r.path().join("data/global");
        let backup = migrate(r.path(), "profile:a", &dest).unwrap();
        assert!(backup.join("vinylpi.db").exists());
        let db = Db::open(&dest.join("vinylpi.db")).unwrap();
        assert_eq!(
            db.query("SELECT artist FROM songs", []).unwrap()[0]["artist"],
            "a"
        );
        assert!(r.path().join("data/profiles/b/vinylpi.db").exists());
        assert!(migrate(r.path(), "profile:b", &dest).is_err());
    }
}
