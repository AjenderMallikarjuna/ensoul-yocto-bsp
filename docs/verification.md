# Ensoul AI — Build & Verification Log

Each phase documents what was built, what was tested, the exact command sequence to reproduce the checks, and bugs encountered and fixed.

---

## Phase 0 — QEMU ARM64 boots with PipeWire audio

**Status:** COMPLETE
**Completed:** 2026-06-21
**Commit:** `a056aab`

### What was built

| Component | Recipe / File | Notes |
|-----------|--------------|-------|
| QEMU ARM64 build config | `kas/anime-ai-qemuarm64.yml` | Intel HDA audio flags, WSLg PulseAudio backend |
| Kernel audio config | `meta-anime-ai/recipes-kernel/linux/files/audio.cfg` | Enables `SND_HDA_INTEL`, `SND_DUMMY`, `SND_VIRTIO`, `SND_USB_AUDIO` |
| Package group | `meta-anime-ai/recipes-core/packagegroups/packagegroup-anime-ai.bb` | PipeWire, WirePlumber, ALSA utils, alsa-plugins |
| Image recipe | `meta-anime-ai/recipes-core/images/anime-ai-image.bb` | `webrtc-audio-processing` added directly (allarch packagegroup workaround) |
| WirePlumber service | `meta-anime-ai/recipes-audio/pipewire-system/` | System-wide WirePlumber over the built-in `pipewire.service` |
| Audio verification | `meta-anime-ai/recipes-anime/ensoul-tools/files/test-audio.sh` | Installed to `/usr/share/ensoul/test-audio.sh` |
| Boot script | `scripts/boot-qemu-audio.sh` | QEMU launch with WSLg PulseAudio for host mic/speakers |

### Key architecture decisions made in Phase 0

- **Built-in `pipewire.service`** is socket-activated in Scarthgap. We do NOT run a second PipeWire instance. Our recipe (`pipewire-system.bb`) only installs `wireplumber-system.service`, which depends on `pipewire.service`.
- **`DBUS_SESSION_BUS_ADDRESS=disabled`** in the WirePlumber service prevents D-Bus autolaunch crash on headless (no X11) boot.
- **`pw-dump`** is used in scripts instead of `pw-cli list-objects` — the latter is non-deterministic in subshell/SSH contexts and produces false negatives.
- **System QEMU** (`sudo apt install qemu-system-arm`) is required, not Yocto's `qemu-helper-native`. The Yocto-built QEMU does not have the PulseAudio backend compiled in.
- **WSLg PulseAudio** at `/mnt/wslg/PulseServer` provides host mic + speakers. QEMU audio option: `-audiodev pa,id=snd0,server=unix:/mnt/wslg/PulseServer,in.name=RDPSource,out.name=RDPSink`.

### What was verified (6/6 checks)

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | `snd_hda_intel` kernel module | `modprobe snd_hda_intel` | No error, module loaded |
| 2 | ALSA playback device | `aplay -l` | `card 1: Intel [HDA Intel]` present |
| 3 | ALSA capture device | `arecord -l` | `card 1: Intel [HDA Intel]` present |
| 4 | PipeWire socket | `ls /run/pipewire/pipewire-0` | Socket file exists |
| 5 | PipeWire connection | `PIPEWIRE_RUNTIME_DIR=/run/pipewire pw-dump` | JSON output, no error |
| 6 | WirePlumber audio nodes | `pw-dump \| grep Audio/Sink` | At least 1 sink registered |

### Bugs fixed during Phase 0

| Error | Root cause | Fix |
|-------|-----------|-----|
| `installs files in /run [empty-dirs]` QA error | Recipe tried to install `/run/pipewire` at image build time | Removed; directory created at runtime by systemd `RuntimeDirectory=` |
| `allarch packagegroup shouldn't depend on dynamically renamed packages` | `webrtc-audio-processing` renames at package time | Moved to `IMAGE_INSTALL` in `anime-ai-image.bb` |
| Only `Dummy` ALSA card in QEMU, no HDA Intel | `qemu-helper-native` built without PulseAudio backend; `runqemu audio` keyword not passed | Installed system QEMU; use `scripts/boot-qemu-audio.sh` |
| WirePlumber crash loop (`status=245/KSM`) | `pipewire-system.service` was starting a second PipeWire on the same socket as the built-in `pipewire.service`, causing lock-file conflict | Removed `pipewire-system.service` entirely; `wireplumber-system.service` now depends on `pipewire.service` |
| `pw-cli list-objects` returning no nodes in test script | Non-deterministic in subshell context (too fast — PipeWire hadn't enumerated nodes yet) | Replaced with `pw-dump` which always returns complete state |
| QEMU `pa` backend rejecting `in.dev=RDPSource` | Invalid option name | Correct option is `in.name=RDPSource,out.name=RDPSink` |
| Mic loopback recorded at 3.7% amplitude | WSLg `RDPSource` default gain too low through QEMU chain | `pactl set-source-volume RDPSource 300%` before boot |

### How to reproduce Phase 0 from scratch

```bash
# 1. Clone to WSL2 native filesystem (NOT /mnt/c — NTFS path has spaces, breaks kas)
git clone https://github.com/AjenderMallikarjuna/ensoul-yocto-bsp.git ~/ensoul-yocto-bsp
cd ~/ensoul-yocto-bsp

# 2. Install host dependencies
sudo apt-get install -y gawk wget git diffstat unzip texinfo gcc build-essential \
  chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils \
  iputils-ping python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev \
  xterm python3-subunit mesa-common-dev zstd liblz4-tool file locales \
  zip rpcsvc-proto qemu-system-arm
sudo locale-gen en_US.UTF-8
pip3 install --user kas

# 3. Build
kas build kas/anime-ai-qemuarm64.yml

# 4. Boot with host audio
bash scripts/boot-qemu-audio.sh

# 5. Inside QEMU — run verification script
/usr/share/ensoul/test-audio.sh
```

Expected result:
```
=== Ensoul Audio Stack — Phase 0 Verification ===
[PASS] snd_hda_intel loaded
[PASS] ALSA playback device found
[PASS] ALSA capture device found
[PASS] PipeWire socket exists at /run/pipewire/pipewire-0
[PASS] pw-cli connected to PipeWire
[PASS] Audio nodes visible in PipeWire graph
=== Results: 6 passed, 0 failed ===
Phase 0 COMPLETE — audio stack verified.
```

---

## Phase 1 — Sherpa-ONNX STT in image, verified on live mic

**Status:** COMPLETE
**Completed:** 2026-06-21
**Commits:** `6658f03`, `fd53707`, `5b12d6a`, `255051d`

### What was built

| Component | Recipe / File | Notes |
|-----------|--------------|-------|
| sherpa-onnx v1.13.3 | `meta-anime-ai/recipes-ai/sherpa-onnx/sherpa-onnx_1.13.3.bb` | Pre-built aarch64 CPU shared library tarball from GitHub releases |
| STT model helper | `meta-anime-ai/recipes-anime/ensoul-tools/files/fetch-stt-model.sh` | Downloads Zipformer 20M EN model inside QEMU at first run |
| Package group update | `packagegroup-anime-ai.bb` | Added `sherpa-onnx` |

**sherpa-onnx package contents (installed in image):**

| File | Location | Size |
|------|----------|------|
| `libonnxruntime.so` | `/usr/lib/` | 16 MB |
| `libsherpa-onnx-c-api.so` | `/usr/lib/` | 3.8 MB |
| `libsherpa-onnx-cxx-api.so` | `/usr/lib/` | 200 KB |
| `sherpa-onnx-alsa` | `/usr/bin/` | streaming ASR direct from ALSA mic |
| `sherpa-onnx` | `/usr/bin/` | offline ASR from WAV file |
| `sherpa-onnx-keyword-spotter-alsa` | `/usr/bin/` | wake-word detection from ALSA mic |
| `sherpa-onnx-vad-alsa` | `/usr/bin/` | VAD only from ALSA mic |
| + 35 other CLI tools | `/usr/bin/` | TTS, diarization, websocket server, etc. |
| Model directory | `/opt/ensoul/models/stt/` | Empty; model downloaded at runtime |

**STT model used for testing:**
- Name: `sherpa-onnx-streaming-zipformer-en-20M-2023-02-17`
- Type: Streaming transducer (Zipformer encoder + LSTM decoder + joiner)
- Size: 42 MB (int8 quantized: encoder + decoder + joiner + tokens)
- Language: English
- Source: GitHub releases tag `asr-models`

### Key recipe decisions

- `INSANE_SKIP:${PN} = "arch already-stripped file-rdeps"` — pre-built aarch64 binaries on x86_64 host; upstream ships stripped; `libonnxruntime.so` symbol deps are intra-package (self-satisfied)
- `FILES:${PN}-dev = ""` — Yocto's default rule grabs any unversioned `*.so` as a linker stub for `-dev`. Our libs are actual runtime SOs without a `libfoo.so.1` symlink chain. Clearing `-dev` keeps them in the main package.
- `RDEPENDS:${PN} = "alsa-lib"` — ALSA-based binaries (`sherpa-onnx-alsa`, etc.) link against `libasound.so.2`
- `COMPATIBLE_MACHINE = "qemuarm64|rk3588"` — prevents accidental build for wrong arch

### What was verified

| # | Check | Result |
|---|-------|--------|
| 1 | `sherpa-onnx-version` in image | v1.13.3, Git SHA `330609da` ✅ |
| 2 | `libonnxruntime.so` present | `/usr/lib/libonnxruntime.so` (16 MB) ✅ |
| 3 | Offline STT on reference WAV | Transcribed correctly (minor start clip, expected) ✅ |
| 4 | ALSA mic device accessible | `hw:1,0` (HDA Intel), 16 kHz stereo capture works ✅ |
| 5 | Live mic → WAV → STT pipeline | Speech captured and transcribed, confidence scores -0.1 to -0.8 ✅ |
| 6 | Live streaming (`sherpa-onnx-alsa`) | XRUNs on QEMU (RTF 2.7, expected) ⚠️ |

### Performance on QEMU (emulated cortex-a57)

| Metric | Value | Expected on RK3588 |
|--------|-------|-------------------|
| Model load time | ~21 s | ~2 s |
| Inference RTF (10s audio) | 2.7 | < 0.5 |
| Real-time streaming | No (XRUNs) | Yes |

RTF > 1.0 on QEMU is an emulation limitation, not a software bug. QEMU emulates cortex-a57 in software on x86. Real RK3588 Cortex-A76 at 2.4 GHz will achieve RTF well below 1.0.

### Mic level calibration

The WSLg RDPSource volume was calibrated during testing:

| Level | Peak | RMS | Result |
|-------|------|-----|--------|
| 600% | 100% (clipping) | 65% | Saturated — STT unintelligible |
| 80% | 100% (occasional clips) | 4% | Too quiet — STT produces only fragments |
| 300% | 100% (transient clips on plosives) | 26% | Good — STT confidence scores -0.1 to -0.8 |

**Calibrated value: 300%** — set automatically by `scripts/boot-qemu-audio.sh`.

The occasional 100% peak at 300% is from speech plosives ("p", "t", "k") hitting the ADC ceiling for a single sample. This is normal for close-mic speech and does not significantly affect STT accuracy.

### Bugs fixed during Phase 1

| Error | Root cause | Fix |
|-------|-----------|-----|
| `kas build` failed with "bitbake directory does not exist" | Running `kas` from `/mnt/c/Users/malli/Documents/New project/` — the space in the path breaks kas's shell invocation of `oe-init-build-env` | Always run `kas` from `~/ensoul-yocto-bsp` (Linux ext4, no spaces) |
| Two repos out of sync | Windows-side repo (`/mnt/c/...`) and Linux-side repo (`~/ensoul-yocto-bsp`) are separate filesystems. Edits on Windows side never reached the Linux build | Push from Windows side to GitHub; pull on Linux side before building |
| `do_package_qa` failures: `dev-elf`, `dev-deps`, `file-rdeps` | (1) Yocto assigns unversioned `*.so` to `-dev`; (2) `libasound.so.2` not in `RDEPENDS`; (3) `libonnxruntime.so` versioned symbol unresolved intra-package | Set `FILES:${PN}-dev = ""`, add `RDEPENDS = "alsa-lib"`, add `file-rdeps` to `INSANE_SKIP` |
| Old QEMU still running on port 2222 | Previous QEMU session from Phase 0 was still alive. New QEMU failed to bind port 2222, SSH polling connected to old image | `kill <old-pid>` before launching new QEMU |
| `fetch-stt-model.sh` got HTTP 404 | Model name `sherpa-onnx-streaming-zipformer-small-2023-06-26` does not exist in GitHub releases | Correct name is `sherpa-onnx-streaming-zipformer-en-20M-2023-02-17` |
| BusyBox `wget` rejected `--show-progress` | BusyBox wget does not support GNU wget flags | Use `-q` (quiet) only |
| `arecord -c 1` failed with "Channels count non available" | HDA Intel in QEMU only supports stereo capture | Use `-c 2` (stereo); extract channel 0 with Python for mono STT input |
| Model returned empty transcript | Recording was silent — no real speaker during automated test | Expected; confirmed with real user speech on second attempt |
| STT confidence scores very low (ys_probs ~-2.0) | Mic at 600% was clipping — ADC saturated, waveform distorted | Lower mic to 300%; verified with amplitude analysis (peak 100% → acceptable, RMS 26%) |

### How to reproduce Phase 1 from scratch

```bash
# After Phase 0 is complete (image built, QEMU booted with host audio):

# On host — download and stage the int8 model files
curl -L https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2 \
  -o /tmp/stt-model.tar.bz2
mkdir -p /tmp/stt-extract
tar -xjf /tmp/stt-model.tar.bz2 -C /tmp/stt-extract \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/tokens.txt \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/encoder-epoch-99-avg-1.int8.onnx \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/decoder-epoch-99-avg-1.int8.onnx \
  sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/joiner-epoch-99-avg-1.int8.onnx

# Copy model into QEMU (port 2222)
MODEL=sherpa-onnx-streaming-zipformer-en-20M-2023-02-17
ssh -p 2222 root@127.0.0.1 "mkdir -p /tmp/stt/$MODEL"
scp -P 2222 /tmp/stt-extract/$MODEL/* root@127.0.0.1:/tmp/stt/$MODEL/

# Verify sherpa-onnx is installed
ssh -p 2222 root@127.0.0.1 "sherpa-onnx-version"
# Expected: sherpa-onnx version : 1.13.3

# Offline STT test on reference audio
ssh -p 2222 root@127.0.0.1 "
  MODEL=/tmp/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17
  sherpa-onnx \
    --encoder=\$MODEL/encoder-epoch-99-avg-1.int8.onnx \
    --decoder=\$MODEL/decoder-epoch-99-avg-1.int8.onnx \
    --joiner=\$MODEL/joiner-epoch-99-avg-1.int8.onnx \
    --tokens=\$MODEL/tokens.txt \
    --num-threads=2 \
    /tmp/test.wav 2>&1 | grep '\"text\"'
"

# Live mic test — record 8 seconds (speak during recording), then transcribe
ssh -p 2222 root@127.0.0.1 "arecord -D hw:1,0 -f S16_LE -r 16000 -c 2 -d 8 /tmp/speech.wav"
ssh -p 2222 root@127.0.0.1 "
  MODEL=/tmp/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17
  sherpa-onnx \
    --encoder=\$MODEL/encoder-epoch-99-avg-1.int8.onnx \
    --decoder=\$MODEL/decoder-epoch-99-avg-1.int8.onnx \
    --joiner=\$MODEL/joiner-epoch-99-avg-1.int8.onnx \
    --tokens=\$MODEL/tokens.txt \
    --num-threads=2 \
    /tmp/speech.wav 2>&1 | grep '\"text\"'
"
```

---

## Phase 2 — LLM response

**Status:** PLANNED

### Planned scope
- Pipe STT transcript to a language model
- Options: Claude API (cloud, requires network) or small local model (llama.cpp / whisper + llama on RK3588)
- Output: text reply

### Planned verification
- Given transcript "what is your name", model responds in character
- Latency from transcript-ready to first token < 500 ms (cloud path)

---

## Phase 3 — Text-to-Speech (Piper TTS)

**Status:** PLANNED

### Planned scope
- Piper TTS Yocto recipe (pre-built aarch64)
- Child-friendly voice model (VITS-based)
- Stream audio to speaker as tokens arrive (don't wait for full response)

### Planned verification
- TTS first audio latency < 200 ms
- Full loop: wake → STT → LLM → TTS → speaker

---

## Phase 4 — Wake word ("Hey Ensoul")

**Status:** PLANNED

### Planned scope
- `sherpa-onnx-keyword-spotter-alsa` (already in image from Phase 1)
- Custom keyword model or reuse `sherpa-onnx` built-in keyword spotter
- Always-on VAD loop; activate STT only on keyword

### Planned verification
- False accept rate < 1/hour in quiet room
- Keyword detection latency < 300 ms

---

## Phase 5 — ensoul-audio daemon

**Status:** PLANNED

### Planned scope
- C daemon: reads ALSA mic, runs VAD, dispatches to STT/keyword spotter
- State machine: `IDLE → WAKE → LISTENING → THINKING → SPEAKING → IDLE`
- Unix socket IPC to companion-daemon
- Barge-in: interrupt TTS playback when speech detected

---

## Phase 6 — RK3588 hardware bring-up

**Status:** PLANNED

### Planned scope
- BSP layer swap: QEMU → RK3588 machine config
- I2S audio codec bring-up (board-specific)
- NPU inference for wake word (RK NPU / RKNN)
- Validate RTF < 0.3 on real hardware for streaming STT

### Expected RTF improvement
On QEMU (emulated cortex-a57): RTF ~2.7 (cannot stream in real time)
On RK3588 (Cortex-A76 @ 2.4 GHz, 4 cores): RTF expected ~0.3–0.5 (fully real-time)
On RK3588 NPU (6 TOPS): RTF expected < 0.1 for wake word keyword model
