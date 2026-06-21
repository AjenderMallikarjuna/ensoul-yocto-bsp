#!/bin/bash
# Build the Ensoul AI Yocto image.
# Run from the repo root: bash scripts/build.sh
#
# Secrets are passed as environment variables so they never touch git.
# Add to ~/.bashrc (or export before running):
#   export ENSOUL_GROQ_KEY="gsk_..."

set -e

if [ -z "$ENSOUL_GROQ_KEY" ]; then
    echo "WARNING: ENSOUL_GROQ_KEY is not set — Aria will not be able to reply."
    echo "  Export it first:  export ENSOUL_GROQ_KEY=\"gsk_...\""
    echo "  Or add it to ~/.bashrc for persistence."
    echo ""
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

exec kas build kas/anime-ai-qemuarm64.yml
