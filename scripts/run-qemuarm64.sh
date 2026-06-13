#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PATH="$HOME/.local/bin:$PATH"

if [ ! -f "build/tmp/deploy/images/qemuarm64/anime-ai-image-qemuarm64.rootfs.ext4" ]; then
  echo "Image not found. Build first with ./scripts/build-qemuarm64.sh" >&2
  exit 1
fi

kas shell kas/anime-ai-qemuarm64.yml -c "runqemu qemuarm64 nographic"
