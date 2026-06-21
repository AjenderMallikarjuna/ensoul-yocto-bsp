# Ensoul AI — Build & Verification Log

Each phase documents what was built, what was tested, the automated verification script, and the manual command sequence to reproduce the same checks from scratch.

---

## Phase 0 — QEMU ARM64 boots with PipeWire audio

**Status:** COMPLETE  
**Date:** 2026-06-21  
**Branch:** main (`a517b38`)

### What was built

| Layer | Component | Location in repo |
|-------|-----------|-----------------|
| Yocto build config | `kas/anime-ai-qemuarm64.yml` | QEMU ARM64 machine, Intel HDA audio flags |
| Kernel config | `meta-anime-ai/recipes-kernel/linux/files/audio.cfg` | Enables `SND_HDA_INTEL`, `SND_DUMMY`, `SND_VIRTIO`, `SND_USB_AUDIO` |
| Package group | `meta-anime-ai/recipes-core/packagegroups/packagegroup-anime-ai.bb` | Pulls in PipeWire, WirePlumber, ALSA utils |
| Image recipe | `meta-anime-ai/recipes-core/images/anime-ai-image.bb` | Adds `webrtc-audio-processing` directly (allarch workaround) |
| PipeWire service | `meta-anime-ai/recipes-audio/pipewire-system/` | System-wide PipeWire + WirePlumber systemd services |
| Test script | `scripts/test-audio.sh` | Installed to `/usr/share/ensoul/test-audio.sh` |

### What was verified

| # | Check | Expected result |
|---|-------|----------------|
| 1 | `snd_hda_intel` kernel module | Loads without error; binds to emulated Intel HDA PCI device |
| 2 | ALSA playback device | `card 1: Intel [HDA Intel]` present in `aplay -l` |
| 3 | ALSA capture device | Same card visible in `arecord -l` |
| 4 | PipeWire socket | `/run/pipewire/pipewire-0` exists after boot |
| 5 | PipeWire client connection | `pw-cli` connects and lists objects without error |
| 6 | WirePlumber audio nodes | 6 nodes registered: HDA sink, HDA source, Dummy sink, Dummy source, MIDI bridge, Device nodes |

### Bugs fixed during Phase 0

| Error | Root cause | Fix |
|-------|-----------|-----|
| `installs files in /run [empty-dirs]` QA error | `pipewire-system.bb` was installing `/run/pipewire` at image build time | Removed from `do_install`; directory created at runtime by `ExecStartPre=/bin/mkdir -p /run/pipewire` |
| `allarch packagegroup shouldn't depend on dynamically renamed packages` | `webrtc-audio-processing` renames itself to `libwebrtc-audio-processing1` at package time | Moved out of allarch packagegroup into `IMAGE_INSTALL` in `anime-ai-image.bb` |
| Only `Dummy` ALSA card in QEMU, no HDA Intel | `runqemu` only adds `-device intel-hda` when the `audio` keyword is passed on the command line | Always run `runqemu qemuarm64 nographic slirp audio` |
| WirePlumber crash loop, no audio nodes | WirePlumber tried to autolaunch D-Bus session bus (needs X11); crashed instead of skipping gracefully; systemd restarted it in a loop | Added `Environment=DBUS_SESSION_BUS_ADDRESS=disabled` to `wireplumber-system.service` |

---

### Manual verification — step by step

Run these commands in order to reproduce the full Phase 0 verification from a clean state.

#### 1. Build the image (first time only)

```bash
# Clone to WSL2 native filesystem (NOT /mnt/c — NTFS is too slow)
git clone https://github.com/AjenderMallikarjuna/ensoul-yocto-bsp.git ~/ensoul-yocto-bsp
cd ~/ensoul-yocto-bsp

# Install host dependencies (Ubuntu 22.04 / 24.04)
sudo apt-get install -y gawk wget git diffstat unzip texinfo gcc build-essential \
  chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils \
  iputils-ping python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev \
  xterm python3-subunit mesa-common-dev zstd liblz4-tool file locales zip rpcsvc-proto
sudo locale-gen en_US.UTF-8
pip3 install --user kas

# Build (2–4 hours first time; subsequent builds use sstate cache)
kas build kas/anime-ai-qemuarm64.yml
```

#### 2. Verify image was created

```bash
ls -lh ~/ensoul-yocto-bsp/build/tmp/deploy/images/qemuarm64/anime-ai-image-qemuarm64.rootfs.ext4
# Expected: ~310 MB ext4 rootfs image
```

#### 3. Boot in QEMU

```bash
cd ~/ensoul-yocto-bsp
source poky/oe-init-build-env build

# audio    — adds -device intel-hda to QEMU (required for HDA nodes in PipeWire)
# slirp    — userspace networking, no sudo needed for tap
# nographic — serial console only, no display window
runqemu qemuarm64 nographic slirp audio
```

Login: `root` (no password).

> **Note:** The WAV audio backend is used in WSL2 (no PulseAudio). Audio routing
> inside the guest works correctly; playback through host speakers requires WSLg.
> To use WAV backend, patch `qemuboot.conf` before running:
> ```bash
> # In ~/ensoul-yocto-bsp/build/tmp/deploy/images/qemuarm64/
> sed -i 's/qb_audio_drv = pa/qb_audio_drv = wav/' *.qemuboot.conf
> sed -i 's/-audiodev pa,id=snd0/-audiodev wav,id=snd0,path=\/tmp\/ensoul-qemu.wav/' *.qemuboot.conf
> ```

#### 4. Run the automated verification script

Inside QEMU:

```bash
/usr/share/ensoul/test-audio.sh
```

Expected output:

```
=== Ensoul Audio Stack — Phase 0 Verification ===
── Kernel modules ──
[PASS] snd_hda_intel loaded (modprobe)
── ALSA devices ──
[PASS] ALSA playback device found
card 0: Dummy [Dummy], device 0: Dummy PCM [Dummy PCM]
card 1: Intel [HDA Intel], device 0: Generic Analog [Generic Analog]
[PASS] ALSA capture device found
card 0: Dummy [Dummy], device 0: Dummy PCM [Dummy PCM]
card 1: Intel [HDA Intel], device 0: Generic Analog [Generic Analog]
── PipeWire ──
[PASS] PipeWire socket exists at /run/pipewire/pipewire-0
[PASS] pw-cli connected to PipeWire
── WirePlumber / Audio nodes ──
[PASS] Audio nodes visible in PipeWire graph
6 audio node(s) registered
=== Results: 6 passed, 0 failed ===
Phase 0 COMPLETE — audio stack verified.
```

#### 5. Manual spot checks (run individually inside QEMU)

```bash
# Kernel: confirm HDA Intel driver bound to PCI device
modprobe snd_hda_intel && echo "module OK"

# ALSA: list all playback and capture hardware
aplay -l
arecord -l

# ALSA: confirm HDA Intel card is card 1
cat /proc/asound/cards

# PipeWire: confirm socket created by system service
ls -la /run/pipewire/

# PipeWire: list all registered objects
PIPEWIRE_RUNTIME_DIR=/run/pipewire pw-cli list-objects

# PipeWire: confirm audio sinks and sources are registered
PIPEWIRE_RUNTIME_DIR=/run/pipewire pw-cli list-objects 2>/dev/null \
  | grep -E 'media.class|node.name'
# Expected: alsa_output.* Audio/Sink, alsa_input.* Audio/Source

# WirePlumber: confirm service is active and running
systemctl status wireplumber-system.service

# WirePlumber: check no crash loop in journal
journalctl -u wireplumber-system.service --no-pager | grep -E "Started|ERROR|crash"

# PipeWire: confirm service is active
systemctl status pipewire-system.service
```

#### 6. Exit QEMU

```bash
poweroff
```

---

## Phase 1 — Sherpa-ONNX STT + ensoul-audio daemon

**Status:** PLANNED

### Planned verification
- Wake word detection (Silero VAD + Sherpa-ONNX)
- Streaming STT latency < 300 ms
- Session state machine: IDLE → WAKE → LISTENING → THINKING
- ensoul-audio daemon socket IPC

---

## Phase 2 — Piper TTS + barge-in

**Status:** PLANNED

### Planned verification
- TTS first audio latency < 150 ms
- Barge-in interrupts playback within 200 ms
- Full loop: wake → STT → Claude API → TTS → speaker

---

## Phase 3 — RK3588 hardware bring-up

**Status:** PLANNED

### Planned verification
- BSP layer swap (QEMU → RK3588)
- I2S audio codec bring-up
- NPU wake word inference on A55 cores
- Full audio loop on real hardware
