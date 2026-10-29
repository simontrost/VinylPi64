#!/usr/bin/env bash
# Pi Zero 2 W (64-bit): install the tested ARM64 build for the current refactor/rust head.
# Requires public GitHub releases. Does not compile anything or require Docker.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
BRANCH=refactor/rust
SERVICE=vinylpi64-rust.service
BIN="$ROOT/target/release/vinylpi64"
DATA_DIR="${VINYLPI_UPDATE_DATA_DIR:-$ROOT/.rust-smoke-data}"
BACKUP_ROOT="$ROOT/data/rust-update-backups"
PORT="${VINYLPI_UPDATE_PORT:-8081}"

fail() { echo "ERROR: $*" >&2; exit 1; }
command -v git >/dev/null && command -v curl >/dev/null && command -v sha256sum >/dev/null && command -v tar >/dev/null || fail 'git, curl, sha256sum and tar are required'
[[ "$(uname -m)" == aarch64 ]] || fail 'Only the 64-bit ARM64 Pi is supported by this updater'
[[ "$(git symbolic-ref --quiet --short HEAD)" == "$BRANCH" ]] || fail "Checkout branch $BRANCH first"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail 'Tracked files are modified. Commit or stash them first'
[[ "$(git remote get-url origin)" =~ (^git@github\.com:|^https://github\.com/|^ssh://git@github\.com/)simontrost/VinylPi64(\.git)?$ ]] || fail 'The origin remote must point to simontrost/VinylPi64'

before="$(git rev-parse HEAD)"
echo "Fetching $BRANCH..."
git fetch origin "$BRANCH"
wanted="$(git rev-parse FETCH_HEAD)"
git merge-base --is-ancestor "$before" "$wanted" || fail 'Remote is not a fast-forward; refusing to update'
echo "Requested commit: $wanted"
# Every commit uses its own immutable release filename. The rolling asset URL
# previously served stale archives from GitHub/CDN caches after --clobber.
URL="https://github.com/simontrost/VinylPi64/releases/download/rust-dev/vinylpi64-aarch64-${wanted}.tar.gz"

stage="$(mktemp -d)"
updating=false
backup=""
had_binary=false
new_binary_installed=false
rollback() {
  echo 'Update failed; restoring the previous binary and source checkout...' >&2
  if $was_running; then sudo systemctl stop "$SERVICE" || true; fi
  if [[ -n "$backup" && -f "$backup/vinylpi64.previous" ]]; then
    install -m 755 "$backup/vinylpi64.previous" "$BIN.restore" && mv -f "$BIN.restore" "$BIN" || true
  elif $new_binary_installed && ! $had_binary; then
    rm -f "$BIN"
  fi
  git reset --hard "$before" || true
  if $was_running; then sudo systemctl start "$SERVICE" || true; fi
  echo "Preserved backup folder: $backup" >&2
  echo 'Database state is not automatically reverted. A pre-update data archive is kept if available.' >&2
}
cleanup() {
  result=$?
  trap - EXIT
  if (( result != 0 )) && $updating; then rollback; fi
  rm -rf "$stage"
  exit "$result"
}
trap cleanup EXIT
# 404 means GitHub Actions has not yet finished publishing this push.
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  --connect-timeout 10 --max-time 120 \
  --output "$stage/build.tar.gz" "$URL" \
  || fail 'ARM64 release for this commit is not available; check the latest GitHub Actions run'

# Prevent an archive with unexpected entries or paths from being installed.
contents="$(tar -tzf "$stage/build.tar.gz")" || fail 'Invalid release archive'
expected="$(printf 'vinylpi64\ncommit.txt\nsha256.txt')"
[[ "$contents" == "$expected" ]] || fail 'Unexpected contents in release archive'
tar -xzf "$stage/build.tar.gz" -C "$stage" \
  vinylpi64 commit.txt sha256.txt
[[ "$(cat "$stage/commit.txt")" == "$wanted" ]] || fail "Release archive commit does not match $wanted; refusing to install"
[[ "$(cat "$stage/sha256.txt")" =~ ^[a-f0-9]{64}[[:space:]][[:space:]]vinylpi64$ ]] || fail 'Unexpected checksum manifest'
(cd "$stage" && sha256sum --check --status sha256.txt) || fail 'Release checksum verification failed'
chmod 755 "$stage/vinylpi64"
"$stage/vinylpi64" --version >/dev/null || fail 'Downloaded ARM64 binary cannot run on this Pi'

installed_service=false
was_running=false
if systemctl cat "$SERVICE" >/dev/null 2>&1; then
  installed_service=true
  if systemctl is-active --quiet "$SERVICE"; then
    was_running=true
  fi
fi
if ! $was_running && pgrep -u "$(id -u)" -x vinylpi64 >/dev/null; then
  fail 'A manually started Rust process is still running. Stop it with Ctrl+C first.'
fi

if $was_running; then
  sudo -v || fail 'sudo access is required to restart the Rust service'
fi

# Source and binary must have the same commit. Backups are saved outside Git.
echo 'Fast-forwarding source checkout...'
git merge --ff-only "$wanted" || fail 'Git fast-forward failed; binary was not changed'
updating=true
mkdir -p "$(dirname "$BIN")" "$BACKUP_ROOT"
backup="$(mktemp -d "$BACKUP_ROOT/update-XXXXXXXX")"
if $was_running; then
  echo "Stopping $SERVICE for safe replacement..."
  sudo systemctl stop "$SERVICE"
fi
if [[ -f "$BIN" ]]; then
  had_binary=true
  cp -p "$BIN" "$backup/vinylpi64.previous"
fi
# Snapshot config and SQLite only while the Rust service is stopped.
if [[ -d "$DATA_DIR" ]]; then
  tar -czf "$backup/data.tar.gz" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")" || fail 'Data backup failed'
fi
install -m 755 "$stage/vinylpi64" "$BIN.new"
mv -f "$BIN.new" "$BIN"
new_binary_installed=true

if $was_running; then
  echo "Starting $SERVICE..."
  sudo systemctl start "$SERVICE" || fail 'New service failed to start'
  healthy=false
  for (( attempt=0; attempt<20; attempt++ )); do
    if ! systemctl is-active --quiet "$SERVICE"; then break; fi
    if curl --silent --fail --max-time 2 "http://127.0.0.1:${PORT}/api/health" | grep -q '"ok":true'; then
      healthy=true
      break
    fi
    sleep 1
  done
  $healthy || fail 'Updated service did not pass health check; see journalctl -u vinylpi64-rust'
  echo "Updated and verified $SERVICE."
else
  echo 'Binary updated. No running Rust systemd service detected.'
  if $installed_service; then
    echo "Start when ready: sudo systemctl start $SERVICE"
  else
    echo "For manual testing: $BIN --root $ROOT --data-dir $DATA_DIR --port $PORT"
    echo 'Optional one-time auto-start: bash scripts/install-rust-service.sh'
  fi
fi
updating=false
printf 'Installed commit: %s\nBackup: %s\n' "$wanted" "$backup"
