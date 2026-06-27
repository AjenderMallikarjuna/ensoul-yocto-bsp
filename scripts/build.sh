#!/bin/bash
# Build the Ensoul AI Yocto image.
# Run from the repo root: bash scripts/build.sh
#
# Secrets are passed as environment variables so they never touch git.
# Add to ~/.bashrc (or export before running):
#   export ENSOUL_GROQ_KEY="gsk_..."

set -e

# Load from ~/.ensoul-secrets if the env var isn't already set
if [ -z "$ENSOUL_GROQ_KEY" ] && [ -f "$HOME/.ensoul-secrets" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.ensoul-secrets"
fi

if [ -z "$ENSOUL_GROQ_KEY" ]; then
    echo "WARNING: ENSOUL_GROQ_KEY is not set — Aria will not be able to reply."
    echo "  Option 1: export ENSOUL_GROQ_KEY=\"gsk_...\" before running"
    echo "  Option 2: echo 'ENSOUL_GROQ_KEY=gsk_...' > ~/.ensoul-secrets"
    echo ""
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

exec kas build kas/anime-ai-qemuarm64.yml
