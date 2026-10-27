#!/usr/bin/env bash
set -euo pipefail
target="${1:-aarch64-unknown-linux-gnu}"
case "$target" in
  aarch64-unknown-linux-gnu) triplet=aarch64-linux-gnu ;;
  armv7-unknown-linux-gnueabihf) triplet=arm-linux-gnueabihf ;;
  *) printf 'Unsupported Pi OS target: %s\n' "$target" >&2; exit 2 ;;
esac
export PKG_CONFIG_ALLOW_CROSS=1
export PKG_CONFIG_LIBDIR="/usr/lib/$triplet/pkgconfig"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-target/cross}"
cargo build --release --locked --target "$target" -j 2
