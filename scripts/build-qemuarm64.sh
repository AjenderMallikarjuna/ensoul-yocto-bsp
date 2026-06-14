#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PATH="$HOME/.local/bin:$PATH"

if ! command -v kas >/dev/null 2>&1; then
  echo "kas is required. Install with: python3 -m pip install --user kas" >&2
  exit 1
fi

echo "=== Ensoul AI — QEMU ARM64 Build ==="
echo "Config : kas/anime-ai-qemuarm64.yml"
echo "(First build takes 1–3 hours; subsequent builds are incremental)"
echo ""

kas build kas/anime-ai-qemuarm64.yml

echo ""
echo "=== Build complete ==="
echo ""
echo "Boot the image:"
echo "  kas shell kas/anime-ai-qemuarm64.yml -- runqemu qemuarm64 nographic"
echo ""
echo "  With host audio (WSLg / native Linux with PulseAudio):"
echo "  kas shell kas/anime-ai-qemuarm64.yml -- runqemu qemuarm64 nographic audio"
echo ""
echo "  With audio output to WAV file (no host audio needed):"
echo "  QB_AUDIO_DRV=wav QB_AUDIO_OPT='-device intel-hda -device hda-duplex,audiodev=snd0 -audiodev wav,id=snd0,path=/tmp/ensoul-qemu.wav' \\"
echo "  kas shell kas/anime-ai-qemuarm64.yml -- runqemu qemuarm64 nographic audio"
echo ""
echo "Inside QEMU, run the audio verification:"
echo "  /usr/share/ensoul/test-audio.sh"
echo "  /usr/share/ensoul/test-audio.sh --tone"
