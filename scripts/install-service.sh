#!/usr/bin/env bash
# Optional one-time systemd setup for VinylPi64 (port 8080).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN="$ROOT/target/release/vinylpi64"
DATA_DIR="$ROOT/data/global"
SERVICE=vinylpi64.service

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
if systemctl is-active --quiet vinylpi64-rust.service; then
  echo 'The old vinylpi64-rust.service is still running. Stop and disable it before installing the new service.' >&2
  exit 1
fi
if pgrep -u "$(id -u)" -x vinylpi64 >/dev/null; then
  echo 'Stop the running VinylPi64 instance (Ctrl+C) first.' >&2
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
Description=VinylPi64
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$ROOT
ExecStart=$BIN --root $ROOT --data-dir $DATA_DIR --bind 0.0.0.0 --port 8080
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
echo 'Any legacy Python service must remain stopped while VinylPi64 uses the same port or hardware.'
