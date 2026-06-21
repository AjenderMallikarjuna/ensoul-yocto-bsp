# Ensoul AI — Yocto BSP

Embedded Linux BSP for the Ensoul AI child companion toy. Target hardware is **Rockchip RK3588** (octa-core, 6 TOPS NPU). Development and CI run on QEMU ARM64.

## What Is Built

A Yocto Linux image (`anime-ai-image`) that boots on QEMU ARM64 and on RK3588. The image includes a full real-time audio stack and an on-device speech recognition engine. No cloud dependency for voice input.

```
mic ──► ALSA (hw:1,0)
         │
         ▼
    sherpa-onnx-alsa
    (streaming Zipformer STT, on-device CPU)
         │
         ▼
    transcript text
         │
         ▼
    [Phase 2: LLM response]
         │
         ▼
    [Phase 3: Piper TTS → speaker]
```

## Build Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | QEMU ARM64 boots with PipeWire + ALSA audio | ✅ Complete |
| 1 | Sherpa-ONNX STT in image, verified on live mic | ✅ Complete |
| 2 | LLM response (Claude API or local model) | Planned |
| 3 | Piper TTS — speak the reply | Planned |
| 4 | Wake word — "Hey Ensoul" activation | Planned |
| 5 | ensoul-audio daemon — state machine + IPC | Planned |
| 6 | RK3588 hardware bring-up + NPU inference | Planned |

## Audio Pipeline (current)

| Component | Role | Package |
|-----------|------|---------|
| PipeWire + WirePlumber | System-wide RT audio routing, ALSA bridge | `pipewire`, `wireplumber` |
| Intel HDA (QEMU emulation) | Audio device in QEMU; maps to WSLg mic/speakers | kernel `snd_hda_intel` |
| sherpa-onnx v1.13.3 | STT engine — streaming Zipformer transducer | `sherpa-onnx` (pre-built aarch64) |
| Zipformer 20M EN model | 20M-parameter streaming English ASR model (int8) | downloaded to `/opt/ensoul/models/stt/` |
| WebRTC APM | Echo cancellation + noise suppression (future) | `webrtc-audio-processing` |

## Workspace Layout

```
.
├── kas/
│   └── anime-ai-qemuarm64.yml      ← build config (machine, layers, local.conf)
├── meta-anime-ai/                  ← our Yocto layer
│   ├── conf/layer.conf
│   ├── recipes-ai/
│   │   └── sherpa-onnx/            ← pre-built aarch64 STT binaries + libs
│   ├── recipes-anime/
│   │   ├── companion-daemon/       ← main application daemon (skeleton)
│   │   └── ensoul-tools/           ← test & helper scripts
│   │       └── files/
│   │           ├── test-audio.sh   ← Phase 0 audio verification
│   │           └── fetch-stt-model.sh ← download STT model into QEMU
│   ├── recipes-audio/
│   │   └── pipewire-system/        ← WirePlumber system-wide systemd service
│   ├── recipes-core/
│   │   ├── images/anime-ai-image.bb
│   │   └── packagegroups/packagegroup-anime-ai.bb
│   └── recipes-kernel/
│       └── linux/                  ← audio kernel config (HDA, virtio, USB)
├── scripts/
│   └── boot-qemu-audio.sh          ← boot QEMU with host mic/speakers via WSLg
└── docs/
    └── verification.md             ← per-phase test procedures and results
```

## Host Requirements

Yocto builds require Linux. On Windows use **WSL2 with Ubuntu 22.04 or 24.04**.

> **Critical:** Clone and build on the native WSL2 ext4 filesystem (`~/`), **not** `/mnt/c/`. The Windows NTFS path has spaces in it which breaks kas's shell invocation of `oe-init-build-env`.

```bash
sudo apt update && sudo apt install -y \
  gawk wget git diffstat unzip texinfo gcc build-essential \
  chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils \
  iputils-ping python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev \
  xterm python3-subunit mesa-common-dev zstd liblz4-tool file locales \
  zip rpcsvc-proto qemu-system-arm
sudo locale-gen en_US.UTF-8
python3 -m pip install --user kas
```

Note: `qemu-system-arm` from apt is required (not Yocto's `qemu-helper-native`) — the Yocto-built QEMU lacks the PulseAudio backend needed for host audio passthrough.

## Build

```bash
git clone https://github.com/AjenderMallikarjuna/ensoul-yocto-bsp.git ~/ensoul-yocto-bsp
cd ~/ensoul-yocto-bsp
kas build kas/anime-ai-qemuarm64.yml
```

First build: 2–4 hours. Subsequent builds hit the sstate cache and complete in minutes.

## Run in QEMU (with host audio)

```bash
cd ~/ensoul-yocto-bsp
bash scripts/boot-qemu-audio.sh
```

This boots the image with Intel HDA audio routed to WSLg PulseAudio (your Windows mic and speakers). SSH is available at `ssh -p 2222 root@127.0.0.1`.

Requires WSLg (Windows 11 + WSL2 GUI support). The script checks for `/mnt/wslg/PulseServer` before starting.

## Phase 0 — Audio Verification

Inside QEMU:

```bash
/usr/share/ensoul/test-audio.sh
```

Expected: 6/6 checks pass (kernel module, ALSA playback, ALSA capture, PipeWire socket, PipeWire connection, WirePlumber audio nodes).

## Phase 1 — STT Verification

The STT model is not baked into the image (65 MB+). Download it inside QEMU once via the helper script (requires internet via QEMU slirp networking), or copy it via SCP from the host.

**Option A — download inside QEMU:**
```bash
/usr/share/ensoul/fetch-stt-model.sh
```

**Option B — copy from host (faster, no internet needed in QEMU):**
```bash
# On host: download and extract int8 model files
curl -L https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2 \
  -o /tmp/stt-model.tar.bz2
mkdir -p /tmp/stt-extract
tar -xjf /tmp/stt-model.tar.bz2 -C /tmp/stt-extract \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/tokens.txt \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/encoder-epoch-99-avg-1.int8.onnx \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/decoder-epoch-99-avg-1.int8.onnx \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/joiner-epoch-99-avg-1.int8.onnx

# SCP into QEMU
ssh -p 2222 root@127.0.0.1 "mkdir -p /tmp/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
scp -P 2222 /tmp/stt-extract/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/* \
  root@127.0.0.1:/tmp/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/
```

**Record and transcribe:**
```bash
# SSH into QEMU
ssh -p 2222 root@127.0.0.1

# Record 8 seconds from mic
arecord -D hw:1,0 -f S16_LE -r 16000 -c 2 -d 8 /tmp/speech.wav

# Transcribe
MODEL=/tmp/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17
sherpa-onnx \
  --encoder=$MODEL/encoder-epoch-99-avg-1.int8.onnx \
  --decoder=$MODEL/decoder-epoch-99-avg-1.int8.onnx \
  --joiner=$MODEL/joiner-epoch-99-avg-1.int8.onnx \
  --tokens=$MODEL/tokens.txt \
  --num-threads=2 \
  /tmp/speech.wav
```

## Target Hardware

Final product: **Rockchip RK3588**
- 4× Cortex-A76 @ 2.4 GHz + 4× Cortex-A55 @ 1.8 GHz
- 6 TOPS NPU (on-device AI inference)
- HDMI out → hologram display
- 4-mic array + hardware AEC codec

`meta-anime-ai` is hardware-agnostic. Only the BSP layer changes for RK3588 bring-up. The STT RTF on QEMU is ~2.7 (too slow for live streaming); on RK3588 Cortex-A76 it is expected to be <0.5 (real-time capable).
