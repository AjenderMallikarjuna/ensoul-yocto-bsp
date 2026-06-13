#!/usr/bin/env bash
# Flash the Anime.AI RPi4 image to an SD card.
# Usage: bash scripts/flash-rpi4.sh /dev/sdX
#
# WARNING: this overwrites the target device completely.
# Double-check the device path with `lsblk` before running.
set -euo pipefail

cd "$(dirname "$0")/.."

DEPLOY_DIR="build/tmp/deploy/images/raspberrypi4-64"
IMG=$(find "$DEPLOY_DIR" -name "anime-ai-image-raspberrypi4-64*.rpi-sdimg" 2>/dev/null | sort | tail -1)

if [[ -z "$IMG" ]]; then
  echo "No rpi-sdimg found in $DEPLOY_DIR — run scripts/build-rpi4.sh first." >&2
  exit 1
fi

DEV="${1:?Usage: $0 /dev/sdX}"

if [[ ! -b "$DEV" ]]; then
  echo "Not a block device: $DEV" >&2
  exit 1
fi

echo "Image : $IMG"
echo "Target: $DEV"
read -rp "Proceed? All data on $DEV will be lost. [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

echo "Flashing..."
sudo dd if="$IMG" of="$DEV" bs=4M status=progress conv=fsync
sudo sync
echo "Done. Insert SD card into RPi4 and power on."
