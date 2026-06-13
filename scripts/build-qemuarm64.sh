#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PATH="$HOME/.local/bin:$PATH"

if ! command -v kas >/dev/null 2>&1; then
  echo "kas is required. Install with: python3 -m pip install --user kas" >&2
  exit 1
fi

kas build kas/anime-ai-qemuarm64.yml
