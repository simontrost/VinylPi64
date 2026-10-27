use crate::config::Audio;
use anyhow::{Result, bail};
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
            let desc = hint.desc.unwrap_or_else(|| name.clone()).replace('\n', " ");
            out.push(json!({"index":out.len(),"name":name,"label":desc,"max_input_channels":2,"default_samplerate":44100,"hostapi":"ALSA","is_default":name=="default"}));
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

#[cfg(target_os = "linux")]
pub fn capture(cfg: &Audio, seconds: f64, cancel: &CancellationToken) -> Result<Vec<i16>> {
    use alsa::{
        Direction, ValueOr,
        pcm::{Access, Format, HwParams, PCM},
    };
    let name = if cfg.device_name_contains.is_empty() {
        "default".to_owned()
    } else {
        let want = cfg.device_name_contains.to_lowercase();
        devices()?
            .iter()
            .find(|d| {
                d["name"]
                    .as_str()
                    .unwrap_or("")
                    .to_lowercase()
                    .contains(&want)
                    || d["label"]
                        .as_str()
                        .unwrap_or("")
                        .to_lowercase()
                        .contains(&want)
            })
            .and_then(|d| d["name"].as_str())
            .map(str::to_owned)
            .ok_or_else(|| anyhow::anyhow!("Configured USB input not found"))?
    };
    let pcm = PCM::new(&name, Direction::Capture, true)?;
    {
        let hw = HwParams::any(&pcm)?;
        hw.set_channels(cfg.channels as u32)?;
        hw.set_rate(cfg.sample_rate as u32, ValueOr::Nearest)?;
        hw.set_format(Format::s16())?;
        hw.set_access(Access::RWInterleaved)?;
        pcm.hw_params(&hw)?;
    }
    let rate = pcm.hw_params_current()?.get_rate()?;
    let channels = cfg.channels as usize;
    let count = (seconds * rate as f64) as usize * channels;
    let mut data = vec![0i16; count];
    let io = pcm.io_i16()?;
    pcm.start()?;
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
                pcm.try_recover(e, false)?;
            }
        }
    }
    Ok(mono_16k(&data, rate, channels))
}
#[cfg(not(target_os = "linux"))]
pub fn capture(_cfg: &Audio, _seconds: f64, _cancel: &CancellationToken) -> Result<Vec<i16>> {
    bail!("Audio capture is supported on Linux/ALSA only")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn silence_and_full_scale() {
        assert_eq!(dbfs(&[0; 50]), -120.);
        assert!(dbfs(&[32767; 50]) > -0.01);
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
