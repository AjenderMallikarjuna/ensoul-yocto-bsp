#!/bin/bash
# Boot Ensoul AI QEMU image with host mic/speaker support via WSLg PulseAudio.
# Run from the repo root: bash scripts/boot-qemu-audio.sh
# Requires: sudo apt install qemu-system-arm (system QEMU with pa support)
# Requires: Windows 11 with WSLg enabled

set -e

REPO=$(cd "$(dirname "$0")/.." && pwd)
IMG=$(ls "$REPO"/build/tmp/deploy/images/qemuarm64/anime-ai-image-qemuarm64.rootfs-*.ext4 2>/dev/null | tail -1)
KERNEL="$REPO/build/tmp/deploy/images/qemuarm64/Image"

if [ ! -f "$IMG" ]; then
    echo "ERROR: No rootfs image found. Run: kas build kas/anime-ai-qemuarm64.yml"
    exit 1
fi

if [ ! -S /mnt/wslg/PulseServer ]; then
    echo "ERROR: WSLg PulseAudio not available at /mnt/wslg/PulseServer"
    echo "       Make sure you are running under WSLg (Windows 11 + WSL2 GUI support)"
    exit 1
fi

echo "Setting WSLg mic input to 300% (avoids clipping that 600% caused)..."
PULSE_SERVER=unix:/mnt/wslg/PulseServer pactl set-source-volume RDPSource 300%

echo "Image: $IMG"
echo "SSH will be available at: ssh -p 2222 root@127.0.0.1"
echo "Aria web UI will be at:   http://127.0.0.1:8080/"
echo ""

export PULSE_SERVER=unix:/mnt/wslg/PulseServer
exec qemu-system-aarch64 \
    -machine virt -cpu cortex-a57 -smp 4 -m 256 \
    -kernel "$KERNEL" \
    -append "root=/dev/vda rw mem=256M ip=dhcp console=ttyAMA0 console=hvc0 swiotlb=0 net.ifnames=0" \
    -drive id=disk0,file="$IMG",if=none,format=raw \
    -device virtio-blk-pci,drive=disk0 \
    -device virtio-net-pci,netdev=net0,mac=52:54:00:12:35:02 \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:8080-:8080 \
    -object rng-random,filename=/dev/urandom,id=rng0 \
    -device virtio-rng-pci,rng=rng0 \
    -device intel-hda \
    -device hda-duplex,audiodev=snd0 \
    -audiodev pa,id=snd0,server=unix:/mnt/wslg/PulseServer,in.name=RDPSource,out.name=RDPSink \
    -device virtio-serial-pci -chardev null,id=virtcon -device virtconsole,chardev=virtcon \
    -device virtio-gpu-pci \
    -nographic
