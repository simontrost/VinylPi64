use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand};
use std::path::PathBuf;
use vinylpi64::{
    api::{App, router},
    migration,
    model::Mode,
};
#[derive(Parser)]
#[command(version, about = "VinylPi64 native Rust server")]
struct Args {
    #[arg(long, default_value = ".", global = true)]
    root: PathBuf,
    #[arg(long, env = "VINYLPI_DATA_DIR", global = true)]
    data_dir: Option<PathBuf>,
    #[arg(long, env = "VINYLPI_BIND", default_value = "0.0.0.0")]
    bind: std::net::IpAddr,
    #[arg(long, env = "VINYLPI_PORT", default_value_t = 8080)]
    port: u16,
    #[command(subcommand)]
    command: Option<Command>,
}
#[derive(Subcommand)]
enum Command {
    /// List legacy data sources without changing any files.
    MigrationSources,
    /// Back up and import exactly one data source into a new global directory.
    Migrate {
        #[arg(long)]
        source: String,
    },
    /// Validate the selected global config and compatible database.
    Check,
    /// Recognize a PCM WAV file through the native fingerprinting pipeline.
    RecognizeFile {
        path: PathBuf,
        #[arg(long)]
        fingerprint_only: bool,
    },
}
fn main() -> Result<()> {
    dotenvy::from_filename("vinylpi.env").ok();
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "vinylpi64=info,tower_http=warn".into()),
        )
        .init();
    let args = Args::parse();
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .max_blocking_threads(4)
        .enable_all()
        .build()?
        .block_on(run(args))
}
async fn run(args: Args) -> Result<()> {
    let root = args
        .root
        .canonicalize()
        .context("Project root does not exist")?;
    let data = args.data_dir.unwrap_or_else(|| root.join("data/global"));
    if let Some(Command::MigrationSources) = args.command {
        println!(
            "{}",
            serde_json::to_string_pretty(&migration::candidates(&root)?)?
        );
        return Ok(());
    }
    if let Some(Command::Migrate { source }) = args.command {
        let backup = migration::migrate(&root, &source, &data)?;
        println!("Migrated {source}; backup: {}", backup.display());
        return Ok(());
    }
    if let Some(Command::RecognizeFile {
        path,
        fingerprint_only,
    }) = args.command
    {
        ensure!(
            path.metadata()?.len() <= 32 * 1024 * 1024,
            "WAV exceeds 32 MiB"
        );
        let mut reader = hound::WavReader::open(path)?;
        let spec = reader.spec();
        ensure!(
            spec.bits_per_sample == 16
                && spec.sample_format == hound::SampleFormat::Int
                && (1..=2).contains(&spec.channels),
            "Expected 16-bit mono/stereo PCM WAV"
        );
        let pcm = reader
            .samples::<i16>()
            .take(spec.sample_rate as usize * spec.channels as usize * 30)
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let pcm = vinylpi64::audio::mono_16k(&pcm, spec.sample_rate, spec.channels as usize);
        if fingerprint_only {
            let sig =
                shazam_fingerprint::algorithm::SignatureGenerator::make_signature_from_buffer(pcm);
            println!(
                "{}",
                sig.encode_to_uri().map_err(|e| anyhow::anyhow!("{e}"))?
            );
        } else {
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &vinylpi64::net::recognize(&vinylpi64::net::client()?, pcm, 30.).await?
                )?
            );
        }
        return Ok(());
    }
    if !data.exists() {
        let choices = migration::candidates(&root)?;
        ensure!(
            choices.is_empty(),
            "Existing data detected. Run migration-sources, then migrate --source <selection>. Use --data-dir with an existing empty directory only to intentionally start fresh. Sources: {}",
            choices.join(", ")
        );
        std::fs::create_dir_all(&data)?;
    }
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(data.join(".instance.lock"))?;
    fs2::FileExt::try_lock_exclusive(&lock)
        .context("Another VinylPi64 instance is using this data directory")?;
    let app = App::new(root, data, args.port)?;
    if matches!(args.command, Some(Command::Check)) {
        app.config.get().validate()?;
        println!(
            "Configuration and SQLite schema valid; hardware and external accounts require live testing."
        );
        app.shutdown().await?;
        return Ok(());
    }
    let listener = tokio::net::TcpListener::bind((args.bind, args.port)).await?;
    tracing::info!(address=%listener.local_addr()?,"Dashboard listening");
    let cancel = app.cancel.clone();
    let signal = async move {
        #[cfg(unix)]
        {
            let mut term =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                    .expect("SIGTERM handler");
            tokio::select! {_ = tokio::signal::ctrl_c()=>{},_ = term.recv()=>{},_ = cancel.cancelled()=>{}}
        }
        #[cfg(not(unix))]
        tokio::select! {_ = tokio::signal::ctrl_c()=>{},_ = cancel.cancelled()=>{}}
    };
    let result = axum::serve(listener, router(app.clone()))
        .with_graceful_shutdown(signal)
        .await;
    app.engine.mode.send_replace(Mode::Off);
    app.shutdown().await?;
    result?;
    Ok(())
}
