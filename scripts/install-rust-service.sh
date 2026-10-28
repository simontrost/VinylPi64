#!/usr/bin/env bash
# Optional one-time systemd setup for the experimental Rust instance (port 8081).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN="$ROOT/target/release/vinylpi64"
DATA_DIR="$ROOT/.rust-smoke-data"
SERVICE=vinylpi64-rust.service

if [[ "$(uname -m)" != aarch64 ]]; then
  echo 'This setup is intended for a 64-bit Raspberry Pi (aarch64).' >&2
  exit 1
fi
if [[ "$ROOT" =~ [[:space:]] ]]; then
  echo 'The project path must not contain whitespace for this service installer.' >&2
  exit 1
fi
if [[ ! -x "$BIN" ]]; then
  echo "Missing executable: $BIN. Run scripts/update.sh first." >&2
  exit 1
fi
if pgrep -u "$(id -u)" -x vinylpi64 >/dev/null; then
  echo 'Stop the manually started Rust instance (Ctrl+C) first.' >&2
  exit 1
fi
if systemctl cat "$SERVICE" >/dev/null 2>&1; then
  echo "A $SERVICE unit already exists. Refusing to overwrite it." >&2
  exit 1
fi
if [[ ! -d "$DATA_DIR" ]]; then
  echo "Missing $DATA_DIR. Create and configure it before enabling auto-start." >&2
  exit 1
fi
sudo -v
unit="$(mktemp)"
trap 'rm -f "$unit"' EXIT
cat > "$unit" <<EOF
[Unit]
Description=VinylPi64 Rust (experimental, port 8081)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$ROOT
ExecStart=$BIN --root $ROOT --data-dir $DATA_DIR --bind 0.0.0.0 --port 8081
Restart=on-failure
RestartSec=5
TimeoutStopSec=40
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$unit" "/etc/systemd/system/$SERVICE"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE"
echo "Installed $SERVICE. Status: sudo systemctl status $SERVICE"
echo 'The existing Python service is not stopped. Keep its recognizer inactive while testing Rust hardware.'
