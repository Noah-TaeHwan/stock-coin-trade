#!/usr/bin/env bash
# frontend/css/tw.css를 다시 만든다(Tailwind v3 standalone CLI, 체크섬 확인 뒤 컨테이너 안에서 실행).
# 화면에 새 Tailwind 클래스를 쓰면 이 스크립트를 돌리고 tw.css를 함께 커밋한다.
# 사용법: scripts/build-css.sh   (필요: docker, curl, shasum)
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=v3.4.19
ARCH=$(uname -m); [ "$ARCH" = x86_64 ] && ARCH=x64; [ "$ARCH" = aarch64 ] && ARCH=arm64
BIN="tailwindcss-linux-${ARCH}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/stockdesk-tailwind/${VERSION}"
mkdir -p "$CACHE"
if [ ! -x "$CACHE/$BIN" ]; then
  base="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}"
  curl -fsSL -o "$CACHE/$BIN" "$base/$BIN"
  curl -fsSL -o "$CACHE/sha256sums.txt" "$base/sha256sums.txt"
  (cd "$CACHE" && grep " ${BIN}\$" sha256sums.txt | shasum -a 256 -c -)
  chmod +x "$CACHE/$BIN"
fi
docker run --rm -v "$PWD":/repo -v "$CACHE":/tw:ro -w /repo debian:bookworm-slim \
  /tw/"$BIN" -c frontend/css/src/tailwind.config.js -i frontend/css/src/tailwind.css -o frontend/css/tw.css --minify
echo "build-css: ok $(wc -c < frontend/css/tw.css) bytes"
