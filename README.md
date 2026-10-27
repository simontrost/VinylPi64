# VinylPi64

<p align="center">
  <img src="https://img.shields.io/badge/platform-Raspberry%20Pi%20Zero%202%20W-red" alt="Platform: Raspberry Pi Zero 2 W">
  <img src="https://img.shields.io/badge/backend-Rust-orange" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-CC--BY--NC%204.0-blue" alt="License: CC BY-NC 4.0">
  <a href="https://github.com/simontrost/VinylPi64/stargazers"><img src="https://img.shields.io/github/stars/simontrost/VinylPi64?style=flat&logo=github&label=stars" alt="GitHub stars"></a>
</p>

VinylPi64 identifies music from a USB turntable using a native Rust fingerprinting client or from **Spotify**, builds a custom **64×64 pixel frame**, and displays it on a **Divoom Pixoo-64**. A local web app provides controls, settings, lyrics, device management, and listening statistics.

<p align="left">
  <img src="assets/readme/Logo.png" width="400" alt="VinylPi64 logo">
</p>

## Features

- Vinyl recognition from USB audio using native Rust audio fingerprinting and Spotify playback recognition
- Album artwork, artist, title, album, genre, and track metadata
- Low-power audio standby with configurable wake-on-audio and audio-level auto-standby
- Optional failure-based auto-standby for Vinyl and Spotify
- Pickup usage tracking based on configurable input-level thresholds
- Custom Pixoo renderer with:
  - dynamic or manual background and text colors
  - configurable cover size, typography, spacing, and marquee text
  - fallback images
- Local web app with:
  - live dashboard updates and Vinyl / Spotify / Off modes
  - lyrics and track information
  - Pixoo brightness, channels, discovery, reboot, and community GIFs
  - statistics for listening time, pickup usage, songs, artists, albums, genres, and covers
- SQLite storage for songs, statistics, caches, and runtime state
- Configurable adaptive sample duration after failed recognitions
- Optional Home Assistant color-sync integration

## Hardware

This project was built and tested with:

- Raspberry Pi Zero 2 W
- Audio-Technica AT-LP120XUSB
- Divoom Pixoo-64

Other hardware can work as well, but may require adjustments. A turntable without USB output needs a compatible USB audio interface, and another display type requires a different display integration.

## Screenshots

### Generated Pixoo frame

<p align="left">
  <img src="assets/readme/preview.png" width="600" alt="Generated Pixoo frame">
</p>

### Hardware setup

<p align="left">
  <img src="assets/readme/example.jpeg" height="600" alt="VinylPi64 hardware setup">
</p>

### Web app
| Pixoo | Settings |
|---|---|
| <img src="assets/readme/mobile_pixoo.jpg" height="600" alt="Pixoo on mobile"> | <img src="assets/readme/mobile_settings.jpg" height="600" alt="Settings on mobile"> |

| Dashboard | Statistics |
|---|---|
| <img src="assets/readme/desktop_dashboard.png" width="600" alt="Dashboard page"> | <img src="assets/readme/desktop_statistics.png" width="600" alt="Statistics page"> |

## Experimental Rust branch

This branch replaces the Python backend with a Rust/Axum application. The HTML/CSS/JavaScript frontend remains. Its Windows build and automated tests have passed; operation with ALSA audio and Divoom hardware on Raspberry Pi still requires live validation.

### Build requirements (Linux)

- Rust stable (1.88+)
- `pkg-config` and `libasound2-dev`
- Optional: `alsa-utils` for `arecord -l`

```bash
sudo apt update
sudo apt install -y pkg-config libasound2-dev alsa-utils
cargo test --locked --workspace
cargo build --release --locked
```

A Pi Zero 2 W only has 512 MB RAM; compiling this application directly on that device may exceed its memory and disk capacity. Prefer a cross build or build on a stronger ARM Linux computer with the same target architecture. See `scripts/cross-build.sh` and `Dockerfile.cross` (cross-build path must be validated on your build host).

### Safe first run (separate from the existing Python installation)

Clone this branch into a separate directory. Never point the experimental Rust process at the old Python data directory:

```bash
git clone --branch refactor/rust https://github.com/simontrost/VinylPi64.git ~/VinylPi64-rust
cd ~/VinylPi64-rust
mkdir -p .rust-smoke-data
./target/release/vinylpi64 --root . --data-dir .rust-smoke-data --port 8081 check
./target/release/vinylpi64 --root . --data-dir .rust-smoke-data --bind 0.0.0.0 --port 8081
```

The application uses the supplied directory for isolated runtime state; it does not need a profile login. The server root is required for templates, fonts, and image assets. Browse to `http://<pi-ip>:8081/` on the home network. Leave music playback stopped in the Rust instance while the original Python service controls the same Pixoo and USB input.

### Existing data migration

The default Rust data directory is `data/global`. Migrating legacy Python data should be performed explicitly and only after backup, using `migration-sources` and `migrate --source ...`; do not merge or overwrite multiple existing profiles without reviewing their contents. For a fresh smoke test use a dedicated empty `--data-dir` instead.

### Deployment

For a first hardware trial run the binary manually, not via systemd. Once the Raspberry Pi hardware functions are tested, a dedicated systemd unit may be created using `WorkingDirectory=<clone>` and `ExecStart=<clone>/target/release/vinylpi64 --root <clone> --data-dir <persistent-data-dir> --port 8080`. Disable or stop the old Python service before enabling production auto-start for the Rust version.

## Configuration

Most options can be changed from the **Settings** page. This includes:

- audio device, sample rate, channels, and recording duration
- adaptive recording durations after failed recognitions
- wake-on-audio, pickup thresholds, and Vinyl/Spotify standby behavior
- Spotify polling interval
- Pixoo layout, colors, text, cover size, and scrolling
- fallback images and Pixoo discovery
- Home Assistant integration and debug settings

The configuration is stored in:

```text
data/global/config.json
```

Runtime data is stored in:

```text
data/global/vinylpi.db
```

This database contains song history, play counts, listening statistics, caches, and the current dashboard state.

## Start on boot (after hardware validation)

Do not enable the Rust service until USB audio, Pixoo recovery and data migration have been tested and the old Python service is disabled. For an initial test run the Rust binary manually on port 8081. Once stable, create a dedicated systemd service pointing to the actual checkout and data directory; never reuse the old Python `ExecStart`.

## Optional: API token

Local API endpoints can be protected with an environment variable:

```bash
VINYLPI_API_TOKEN=replace_with_a_long_random_value
```

Store it in `vinylpi.env` and keep that file private.

## Optional: Home Assistant

VinylPi64 can send the dominant album-cover color to a Home Assistant webhook whenever a new song is recognized.

Enable the integration in the Settings page and provide:

- Home Assistant base URL
- webhook ID

Example Home Assistant automation:

```yaml
alias: VinylPi Color Sync
triggers:
  - trigger: webhook
    webhook_id: vinylpi_cover_color
    allowed_methods:
      - POST
      - PUT
    local_only: true
conditions:
  - condition: state
    entity_id: input_boolean.vinylpi_color_sync
    state: "on"
actions:
  - action: light.turn_on
    target:
      entity_id:
        - light.lamp1
        - light.lamp2
    data:
      rgb_color:
        - "{{ trigger.json.r | int }}"
        - "{{ trigger.json.g | int }}"
        - "{{ trigger.json.b | int }}"
mode: restart
```

Additional local API endpoints can be used for Pixoo power, music mode, and remote GIF playback.

## Recognition notes

Vinyl recognition uses recorded audio samples. Adaptive sampling can automatically use longer recordings after failed attempts and return to the base duration after a successful recognition.

With **Wake on Audio** enabled, the Off state keeps only a lightweight RMS level monitor active. Vinyl recognition starts when the configured wake threshold is reached and can return to standby after sustained low input. Pickup usage is measured from the same audio data, so it does not require a second audio stream.

Recognition quality depends on the audio level, selected passage, background noise, and Shazam's result. Quiet intros, live versions, heavy surface noise, or very short samples can reduce accuracy.

## Troubleshooting

### Audio device not found

```bash
arecord -l
```

Verify that the configured device-name filter matches the listed USB device.

### Web app starts, but recognition does not

Check the service logs or run the recognizer manually:

```bash
./target/release/vinylpi64 --help
```

### Pixoo does not respond

- confirm that the Pixoo and VinylPi are on the same network
- use device discovery in the Pixoo page
- verify the saved IP address
- reboot the Pixoo from the web app

### Service fails after an update

```bash
git pull
cargo build --release --locked
# Restart only the Rust service after validating the binary and backing up data.
```

## License

VinylPi64 is licensed under the Creative Commons Attribution–NonCommercial 4.0 International license.

See [LICENSE](LICENSE) for the full license text.
