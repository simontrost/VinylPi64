#!/usr/bin/env bash
set -euo pipefail

target="${1:-aarch64-unknown-linux-gnu}"
case "$target" in
  aarch64-unknown-linux-gnu)
    triplet=aarch64-linux-gnu
    export CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc
    export AR_aarch64_unknown_linux_gnu=aarch64-linux-gnu-ar
    ;;
  armv7-unknown-linux-gnueabihf)
    triplet=arm-linux-gnueabihf
    export CC_armv7_unknown_linux_gnueabihf=arm-linux-gnueabihf-gcc
    export AR_armv7_unknown_linux_gnueabihf=arm-linux-gnueabihf-ar
    ;;
  *) printf 'Unsupported Pi OS target: %s\n' "$target" >&2; exit 2 ;;
esac

# Detect missing target libc development headers before Cargo starts.
printf '#include <stdint.h>\nint main(void) { return 0; }\n' \
  | "${triplet}-gcc" -x c -fsyntax-only - \
  || { echo "Cross C headers for ${triplet} are missing" >&2; exit 1; }

export PKG_CONFIG_ALLOW_CROSS=1
export PKG_CONFIG_LIBDIR="/usr/lib/${triplet}/pkgconfig:/usr/share/pkgconfig"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-target/cross}"

cargo build --release --locked --target "$target" -j 2
