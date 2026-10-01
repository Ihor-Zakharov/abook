#!/usr/bin/env bash
# Сборка «Аудиотека.exe» из WSL: кросс-компиляция в x86_64-pc-windows-msvc через cargo-xwin (без Visual Studio).
# Результат копируется в D:\VideoDownloader\Аудиотека\.
set -euo pipefail
cd "$(dirname "$0")"
CACHE=${ABOOK_BUILD_CACHE:-/mnt/d/VideoDownloader/.build-cache}
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$CACHE/audioteka-target}
export XWIN_CACHE_DIR=${XWIN_CACHE_DIR:-$CACHE/xwin}
export XWIN_ACCEPT_LICENSE=1
OUT=${ABOOK_DESKTOP_OUT:-/mnt/d/VideoDownloader/Аудиотека}
rustup target add x86_64-pc-windows-msvc >/dev/null
command -v cargo-xwin >/dev/null || cargo install --locked cargo-xwin
cargo xwin build --release --target x86_64-pc-windows-msvc
mkdir -p "$OUT"
cp "$CARGO_TARGET_DIR/x86_64-pc-windows-msvc/release/audioteka.exe" "$OUT/Аудиотека.exe"
ls -la "$OUT/Аудиотека.exe"
