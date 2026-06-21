# Ensoul AI — Yocto BSP

Embedded Linux BSP for the Ensoul AI child companion toy. Target hardware is **Rockchip RK3588** (octa-core, 6 TOPS NPU). Development and CI run on QEMU ARM64.

## Audio Pipeline

```
mic → WebRTC APM (AEC/NS/AGC) → Sherpa-ONNX (VAD + wake word + STT) → Claude API → Piper TTS → speaker
                 └── PipeWire (RT audio routing, clock management) ──┘
```

| Component | Role | Replaces |
|-----------|------|---------|
| PipeWire + WirePlumber | RT audio routing, clock, ALSA bridge | Custom abox daemon |
| WebRTC APM (AEC3/NS/AGC2) | Echo cancellation, noise suppression | Custom DSP pipeline |
| Sherpa-ONNX Zipformer | Streaming STT, 80–200 ms latency | Cloud Whisper API |
| Silero VAD | Voice activity detection, endpointing | Custom VAD |
| Piper TTS | On-device TTS, ~80 ms to first audio | Cloud TTS |

See [`ensoul-audio-design.md`](ensoul-audio-design.md) for the full architecture.

## Build Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | QEMU ARM64 boots with PipeWire audio | ✅ Complete |
| 1 | Sherpa-ONNX STT + ensoul-audio daemon | Planned |
| 2 | Piper TTS + session state machine | Planned |
| 3 | Claude API integration + barge-in | Planned |
| 4 | RK3588 hardware bring-up | Planned |

## Workspace Layout

```
.
├── kas/
│   └── anime-ai-qemuarm64.yml      ← QEMU ARM64 build config
├── meta-anime-ai/
│   ├── conf/layer.conf
│   ├── recipes-anime/
│   │   ├── companion-daemon/        ← main application daemon
│   │   └── ensoul-tools/           ← test & verification scripts
│   ├── recipes-audio/
│   │   └── pipewire-system/        ← system-wide PipeWire service
│   ├── recipes-core/
│   │   ├── images/anime-ai-image.bb
│   │   └── packagegroups/packagegroup-anime-ai.bb
│   └── recipes-kernel/
│       └── linux/                  ← audio kernel config (HDA, virtio, USB)
├── scripts/
│   └── test-audio.sh               ← Phase 0 audio verification
└── ensoul-audio-design.md          ← full audio architecture document
```

## Host Requirements

Yocto builds require Linux. On Windows use **WSL2 with Ubuntu 22.04 or 24.04**.

> **Important:** Clone and build on the native WSL2 ext4 filesystem (`~/`), not on `/mnt/c/` (NTFS causes path errors and is too slow).

```bash
sudo apt update
sudo apt install -y gawk wget git diffstat unzip texinfo gcc build-essential \
  chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils \
  iputils-ping python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev \
  xterm python3-subunit mesa-common-dev zstd liblz4-tool file locales \
  zip rpcsvc-proto
sudo locale-gen en_US.UTF-8
python3 -m pip install --user kas
```

## Build

```bash
# Clone to native WSL2 filesystem
git clone <repo-url> ~/ensoul-yocto-bsp
cd ~/ensoul-yocto-bsp

# Build (first build takes 2–4 hours; subsequent builds use sstate cache)
kas build kas/anime-ai-qemuarm64.yml
```

To keep the build running after closing the terminal:

```bash
tmux new-session -d -s ensoul-build -c ~/ensoul-yocto-bsp \
  'kas build kas/anime-ai-qemuarm64.yml 2>&1 | tee ~/ensoul-build/build.log'
tmux attach -t ensoul-build   # reattach anytime; Ctrl+B D to detach
```

## Run in QEMU

```bash
cd ~/ensoul-yocto-bsp
source poky/oe-init-build-env build
runqemu qemuarm64 nographic
```

Login: `root` (no password).

### Phase 0 Audio Verification

Inside QEMU:

```bash
/usr/share/ensoul/test-audio.sh          # check audio stack
/usr/share/ensoul/test-audio.sh --tone   # play 1 kHz test tone
/usr/share/ensoul/test-audio.sh --record # 3-second record + playback
```

Expected output:
- `snd_hda_intel` module loaded
- ALSA capture and playback devices present
- PipeWire socket at `/run/pipewire/pipewire-0`
- WirePlumber session manager running

## Target Hardware

Final product runs on **Rockchip RK3588**:
- 4× Cortex-A76 + 4× Cortex-A55
- 6 TOPS NPU (on-device AI inference)
- HDMI out → hologram display
- `meta-anime-ai` layer is hardware-agnostic; only the BSP layer changes for RK3588 bring-up
