use crate::config::Audio;
use anyhow::{Context, Result, bail};
use serde_json::Value;
use tokio_util::sync::CancellationToken;

pub fn dbfs(samples: &[i16]) -> f64 {
    if samples.is_empty() {
        return -120.;
    };
    let rms = (samples
        .iter()
        .map(|s| (*s as f64 / 32768.).powi(2))
        .sum::<f64>()
        / samples.len() as f64)
        .sqrt();
    (20. * rms.max(1e-6).log10()).max(-120.)
}
/// Windowed sinc low-pass resampling; bounded to at most 30 seconds by config.
pub fn mono_16k(interleaved: &[i16], rate: u32, channels: usize) -> Vec<i16> {
    let mono = interleaved
        .chunks_exact(channels)
        .map(|s| s.iter().map(|n| *n as f64).sum::<f64>() / channels as f64)
        .collect::<Vec<_>>();
    if rate == 16000 {
        return mono.iter().map(|v| *v as i16).collect();
    };
    let ratio = rate as f64 / 16000.;
    let cutoff = (16000. / rate as f64).min(1.) * 0.94;
    (0..(mono.len() as f64 / ratio) as usize)
        .map(|i| {
            let at = i as f64 * ratio;
            let center = at.floor() as i64;
            let mut sum = 0.;
            let mut weight = 0.;
            for j in -24..=24 {
                let idx = center + j;
                if idx < 0 || idx >= mono.len() as i64 {
                    continue;
                };
                let distance = at - idx as f64;
                let x = std::f64::consts::PI * distance * cutoff;
                let sinc = if x.abs() < 1e-10 { 1. } else { x.sin() / x };
                let window = 0.5 + 0.5 * (std::f64::consts::PI * distance / 25.).cos();
                let w = sinc * window;
                sum += mono[idx as usize] * w;
                weight += w;
            }
            (sum / weight.max(1e-9)).round().clamp(-32768., 32767.) as i16
        })
        .collect()
}

#[cfg(target_os = "linux")]
pub fn devices() -> Result<Vec<Value>> {
    use alsa::{Direction, device_name::HintIter};
    use serde_json::json;
    use std::ffi::CString;
    let mut out = vec![];
    for hint in HintIter::new(None, &CString::new("pcm")?)? {
        if hint.direction == Some(Direction::Playback) {
            continue;
        };
        if let Some(name) = hint.name {
            // "null" is a sink/source of zeroes, never an actual turntable input.
            if name.eq_ignore_ascii_case("null") { continue; }
            let desc = hint.desc.unwrap_or_else(|| name.clone()).replace('\n', " ");
            out.push(json!({"index":out.len(),"name":name,"label":desc,"display_name":desc,"max_input_channels":2,"default_samplerate":44100,"hostapi":"ALSA","is_default":name=="default"}));
        }
    }
    Ok(out)
}
#[cfg(not(target_os = "linux"))]
pub fn devices() -> Result<Vec<Value>> {
    bail!(
        "Native USB capture requires Linux/ALSA; dashboard and integrations are available on this host"
    )
}

/// ALSA exposes both plugin names and human-readable hardware descriptions.
/// A legacy substring ("USB AUDIO") must match the description too, while a
/// value selected in Settings ("plughw:CARD=…") should be matched exactly.
fn select_input(configured: &str, list: &[Value]) -> Result<String> {
    let entries = list.iter().filter_map(|d| {
        Some((d["name"].as_str()?, d["label"].as_str().unwrap_or("")))
    }).collect::<Vec<_>>();
    let normalize = |v: &str| v.chars().filter(|c| c.is_alphanumeric()).flat_map(char::to_lowercase).collect::<String>();
    // Python/PortAudio used labels such as "USB AUDIO  CODEC: Audio (hw:0,0)".
    // ALSA exposes the same input under a PCM name like plughw:CARD=CODEC,DEV=0.
    let legacy_name = configured.split(": Audio (hw:").next().unwrap_or(configured);
    let needle = normalize(legacy_name);
    let matches = entries.iter().filter(|(name, label)| {
        // "null" captures silence and must never win automatic discovery.
        !name.eq_ignore_ascii_case("null")
            && (needle.is_empty()
                || normalize(name).contains(&needle)
                || normalize(label).contains(&needle))
    });
    let rank = |(name, label): &(&str, &str)| -> i32 {
        let n = name.to_ascii_lowercase();
        let l = label.to_ascii_lowercase();
        let mut score = 0;
        if !configured.is_empty() && n.eq_ignore_ascii_case(configured) {
            score += 2000;
        }
        if n.starts_with("plughw:") {
            score += 500;
        } else if n.starts_with("sysdefault:") {
            score += 300;
        } else if n.starts_with("hw:") {
            score += 150;
        }
        if l.contains("usb") { score += 100; }
        if n == "default" { score -= 200; }
        score
    };
    if let Some((name, _)) = matches.max_by_key(|entry| rank(entry)) {
        return Ok((*name).to_owned());
    }
    let available = entries.iter().take(12).map(|(name, label)| format!("{name} ({label})")).collect::<Vec<_>>().join(", ");
    anyhow::bail!("Configured USB input not found: '{configured}'. ALSA inputs: [{}]. Select an available device in Settings > Audio or disable auto-wake when no turntable is attached.", available)
}

// Do not open a second ALSA capture endpoint while an interrupted blocking
// operation still owns the first one. Dropping a Tokio JoinHandle does NOT
// stop the synchronous ALSA call behind it.
#[cfg(target_os = "linux")]
fn capture_lock() -> Result<std::sync::MutexGuard<'static, ()>> {
    use std::sync::{Mutex, OnceLock};
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
        .try_lock()
        .map_err(|_| anyhow::anyhow!("Audio device still in use by an earlier capture; waiting for release"))
}

#[cfg(target_os = "linux")]
fn start_capture_pcm(pcm: &alsa::pcm::PCM) -> Result<()> {
    // ALSA can report an XRUN already at snd_pcm_start(), rather than readi().
    // Recover it here as well; persistent USB timeouts are intentionally not
    // masked by an unlimited recovery loop.
    match pcm.start() {
        Ok(()) => Ok(()),
        Err(e) if e.errno() == 32 || e.errno() == 86 => {
            pcm.try_recover(e, false).context("Recovering ALSA capture at start")?;
            pcm.start().context("Restarting ALSA capture after recovery")?;
            Ok(())
        }
        Err(e) => Err(e).context("Starting ALSA capture"),
    }
}

/// Continuous, single-stream wake monitor, equivalent to Python's
/// sounddevice.RawInputStream. Never reconfigure USB alternate interfaces
/// between the 0.5s wake windows. This runs in one blocking worker and ends
/// when the source changes or its cancellation token is set.
#[cfg(target_os = "linux")]
pub fn monitor(
    cfg: &Audio,
    cancel: &CancellationToken,
    output: tokio::sync::mpsc::Sender<Result<f64, String>>,
) -> Result<()> {
    use alsa::{Direction, ValueOr, pcm::{Access, Format, HwParams, PCM}};
    use tokio::sync::mpsc::error::TrySendError;

    let _lock = capture_lock()?;
    if cancel.is_cancelled() { return Ok(()); }
    let name = select_input(&cfg.device_name_contains, &devices()?)?;
    let pcm = PCM::new(&name, Direction::Capture, true)
        .with_context(|| format!("Opening ALSA auto-wake input '{name}'"))?;
    {
        let hw = HwParams::any(&pcm).context("Querying ALSA wake hardware params")?;
        hw.set_channels(cfg.channels as u32)?;
        hw.set_rate(cfg.sample_rate as u32, ValueOr::Nearest)?;
        hw.set_format(Format::s16())?;
        hw.set_access(Access::RWInterleaved)?;
        pcm.hw_params(&hw).context("Configuring ALSA wake input")?;
    }
    let rate = pcm.hw_params_current()?.get_rate()?;
    let channels = cfg.channels as usize;
    let frames = (rate / 2).max(256) as usize;
    let mut data = vec![0i16; frames * channels];
    let io = pcm.io_i16()?;
    start_capture_pcm(&pcm)?;
    tracing::debug!(device=%name, rate, channels, "Continuous Vinyl auto-wake stream started");

    loop {
        if cancel.is_cancelled() || output.is_closed() { break; }
        let mut offset = 0usize;
        // Only bound the reading phase. USB control calls while opening the
        // device may block in the kernel; the exclusive lock prevents overlap.
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while offset < data.len() {
            if cancel.is_cancelled() || output.is_closed() { return Ok(()); }
            if std::time::Instant::now() > deadline {
                bail!("Continuous ALSA wake read timed out");
            }
            match io.readi(&mut data[offset..]) {
                Ok(n) => {
                    offset += n * channels;
                    if n == 0 { std::thread::sleep(std::time::Duration::from_millis(10)); }
                }
                Err(e) if e.errno() == 11 => {
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
                Err(e) => { pcm.try_recover(e, false).context("Recovering wake stream read")?; }
            }
        }
        match output.try_send(Ok(dbfs(&data))) {
            Ok(()) => (),
            Err(TrySendError::Full(_)) => (), // No buffering buildup during transitions.
            Err(TrySendError::Closed(_)) => break,
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
pub fn capture(cfg: &Audio, seconds: f64, cancel: &CancellationToken, wav_path: &str) -> Result<Vec<i16>> {
    use alsa::{
        Direction, ValueOr,
        pcm::{Access, Format, HwParams, PCM},
    };
    let _lock = capture_lock()?;
    if cancel.is_cancelled() { bail!("Audio capture cancelled"); }
    let name = select_input(&cfg.device_name_contains, &devices()?)?;
    let pcm = PCM::new(&name, Direction::Capture, true)
        .with_context(|| format!("Opening ALSA input '{name}'"))?;
    {
        let hw = HwParams::any(&pcm)?;
        hw.set_channels(cfg.channels as u32)?;
        hw.set_rate(cfg.sample_rate as u32, ValueOr::Nearest)?;
        hw.set_format(Format::s16())?;
        hw.set_access(Access::RWInterleaved)?;
        pcm.hw_params(&hw).context("Configuring ALSA capture hardware parameters")?;
    }
    let rate = pcm.hw_params_current()?.get_rate()?;
    let channels = cfg.channels as usize;
    let count = (seconds * rate as f64) as usize * channels;
    let mut data = vec![0i16; count];
    let io = pcm.io_i16()?;
    start_capture_pcm(&pcm)?;
    let mut offset = 0;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs_f64(seconds + 5.);
    while offset < count {
        if cancel.is_cancelled() {
            bail!("Audio capture cancelled")
        };
        if std::time::Instant::now() > deadline {
            bail!("USB capture timed out")
        };
        match io.readi(&mut data[offset..]) {
            Ok(n) => {
                offset += n * channels;
                if n == 0 {
                    std::thread::sleep(std::time::Duration::from_millis(10));
                }
            }
            Err(e) if e.errno() == 11 => std::thread::sleep(std::time::Duration::from_millis(10)),
            Err(e) => {
                pcm.try_recover(e, false).context("Recovering ALSA capture read")?;
            }
        }
    }
    if !wav_path.is_empty()
        && let Err(error) = write_debug_wav(wav_path, &data, rate, channels as u16)
    {
        tracing::warn!(%error, "Unable to write debug WAV");
    }
    Ok(mono_16k(&data, rate, channels))
}
#[cfg(not(target_os = "linux"))]
pub fn capture(_cfg: &Audio, _seconds: f64, _cancel: &CancellationToken, _wav_path: &str) -> Result<Vec<i16>> {
    bail!("Audio capture is supported on Linux/ALSA only")
}

fn write_debug_wav(path: &str, samples: &[i16], rate: u32, channels: u16) -> Result<()> {
    let path = std::path::Path::new(path);
    if let Some(parent) = path.parent() && !parent.as_os_str().is_empty() {
        std::fs::create_dir_all(parent)?;
    }
    let mut writer = hound::WavWriter::create(path, hound::WavSpec {
        channels,
        sample_rate: rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    })?;
    for &sample in samples { writer.write_sample(sample)?; }
    writer.finalize()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(target_os = "linux")]
    #[test]
    fn capture_endpoint_cannot_be_opened_twice() {
        let first = capture_lock().expect("first capture owns the USB input");
        assert!(capture_lock().is_err(), "another worker must not open the same input");
        drop(first);
        assert!(capture_lock().is_ok(), "the USB input must become available again");
    }

    #[test]
    fn silence_and_full_scale() {
        assert_eq!(dbfs(&[0; 50]), -120.);
        assert!(dbfs(&[32767; 50]) > -0.01);
    }
    #[test]
    fn alsa_device_names_and_legacy_filter() {
        let list = vec![
            serde_json::json!({"name":"default","label":"Default PCM"}),
            serde_json::json!({"name":"plughw:CARD=CODEC,DEV=0","label":"USB Audio CODEC, USB Audio"}),
        ];
        assert_eq!(select_input("USB AUDIO", &list).unwrap(), "plughw:CARD=CODEC,DEV=0");
        assert_eq!(select_input("USB AUDIO  CODEC: Audio (hw:0,0)", &list).unwrap(), "plughw:CARD=CODEC,DEV=0");
        assert_eq!(select_input("", &list).unwrap(), "plughw:CARD=CODEC,DEV=0");
        assert!(select_input("not-a-device", &list).unwrap_err().to_string().contains("ALSA inputs"));
    }
    #[test]
    fn resampler_duration_and_antialias() {
        for rate in [44100, 48000] {
            let sine = |hz: f64| {
                (0..rate)
                    .map(|i| {
                        (10000. * (2. * std::f64::consts::PI * i as f64 * hz / rate as f64).sin())
                            as i16
                    })
                    .collect::<Vec<_>>()
            };
            let low = mono_16k(&sine(1000.), rate, 1);
            let high = mono_16k(&sine(12000.), rate, 1);
            assert_eq!(low.len(), 16000);
            assert!(dbfs(&low) > -15.);
            assert!(dbfs(&high) < dbfs(&low) - 25.);
        }
    }
}
