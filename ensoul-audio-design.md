# Ensoul AI — Audio System Design Document

**Project:** Ensoul AI Companion Device  
**Document type:** Technical Architecture & Design  
**Status:** Working Draft — QEMU Development Phase  
**Prepared by:** Ajender Reddy Mallikarjuna  
**Date:** June 2026

---

## Table of Contents

1. [Project Context](#1-project-context)
2. [Audio Use Cases](#2-audio-use-cases)
3. [The Full Audio Signal Flow](#3-the-full-audio-signal-flow)
4. [Original Architecture Analysis](#4-original-architecture-analysis)
5. [Component Deep Dive](#5-component-deep-dive)
6. [VAD — What It Is and Why It Matters](#6-vad--what-it-is-and-why-it-matters)
7. [STT Decision — Sherpa-ONNX vs Whisper.cpp](#7-stt-decision--sherpa-onnx-vs-whispercpp)
8. [Latency Budget](#8-latency-budget)
9. [Revised Architecture — Our Approach](#9-revised-architecture--our-approach)
10. [Open Source Components](#10-open-source-components)
11. [Component-by-Component Elimination Map](#11-component-by-component-elimination-map)
12. [Co-Processor — Risk and Alternative](#12-co-processor--risk-and-alternative)
13. [Development Build Plan](#13-development-build-plan)
14. [Design Decisions Log](#14-design-decisions-log)

---

## 1. Project Context

Ensoul is an AI companion toy with a hologram display targeting children. The product strategy (from the board briefing) rests on five decisions:

1. **Hybrid edge-cloud architecture** — local path for instant response, cloud for conversational depth
2. **RK3588-class SoC** — 6 TOPS NPU, 8 GB RAM, strong enough for on-device models and hologram rendering
3. **Embedded Linux (Yocto)** — lean stack, fast boot, full control, no Android bloat
4. **Perceived speed, not raw latency** — guarantee a local acknowledgment within 300ms, stream the rest
5. **No camera in v1** — removes the largest COPPA/child-safety liability

The audio system is the emotional core of the product. A child's first interaction is: say the wake word → get a response. If that loop feels sluggish or unreliable, the product fails regardless of how good the AI is.

### Hardware context (target production)

| Component | Spec |
|-----------|------|
| SoC | RK3588 (4× Cortex-A76 + 4× Cortex-A55, Mali-G610 GPU, 6 TOPS NPU) |
| Microphone array | 4-mic linear array + hardware AEC codec |
| Speaker | Tuned full-range driver + amplifier |
| Connectivity | Dual-band WiFi + BLE |
| Always-on | RTOS co-processor (Zephyr/FreeRTOS) for wake word during SoC sleep |
| OS | Yocto Linux (Scarthgap), built with kas |

### Current development status

No hardware exists yet. Development is on QEMU ARM64 using the existing kas build configuration in `kas/anime-ai-qemuarm64.yml`. The full Yocto layer is in `meta-anime-ai/`. A companion daemon (`companion-daemon`) already exists with the device's AI personality logic.

---

## 2. Audio Use Cases

The audio system must support all of the following simultaneously or in sequence:

| Use Case | Description | Critical requirement |
|----------|-------------|---------------------|
| **Wake word detection** | Always listening for "Hey Ensoul" | Runs 24/7, ultra-low CPU |
| **Speech-to-text** | Convert child's speech to text for the LLM | Low latency, streaming results |
| **Text-to-speech** | Speak the LLM's response | Natural voice, <100ms to first audio |
| **Echo cancellation** | Remove speaker output from mic input | Must work or STT transcribes TTS |
| **Noise suppression** | Clean up background noise | Works in noisy home environment |
| **Barge-in** | User can interrupt device mid-speech | Stops playback, immediately listens |
| **End-of-speech detection** | Know when user finished talking | Directly determines perceived latency |
| **Beamforming** | Focus on user, reject TV/background | Better accuracy in real rooms |

---

## 3. The Full Audio Signal Flow

There are two signal paths that must run simultaneously, sharing one clock:

```
CAPTURE PATH (mic → brain)
════════════════════════════════════════════════════════════════════

Mic 1 ─┐
Mic 2 ─┤──► I2S bus ──► ALSA driver ──► HPF ──► AEC ──► Beamform ──► NS ──► AGC
Mic 3 ─┤                                          ▲
Mic 4 ─┘                                          │
                                          AEC reference signal
                                          (delayed playback)

After AGC, three detectors run in parallel on every 10ms frame:
         ┌───────────────────────────────────────────────────┐
         │                                                   │
    Wake word                    VAD                    STT feed
    detector               (onset / offset)          (Sherpa-ONNX
   (tiny model,           (Silero VAD, 30ms)          streaming)
    always on,                   │                        │
    < 1% CPU)                    │                        │
         │               SPEECH_START                  partial
    IDLE ──► WAKE         SPEECH_END                  results
                               │                      every 100ms


PLAYBACK PATH (brain → speaker)
════════════════════════════════════════════════════════════════════

LLM text ──► Piper TTS ──► EQ ──► DRC ──► ALSA ──► I2S ──► Codec ──► Speaker
                                                                │
                                              also captured as AEC reference ──►
```

**The shared clock is the single most important thing in this diagram.** If capture and playback run from different clocks, they drift. A 1 ppm drift at 16kHz = 1 sample per 17 minutes. Over an hour-long play session, the AEC reference drifts by 3–4 samples. Echo cancellation degrades. This is why one process must own both.

---

## 4. Original Architecture Analysis

The `Audio_Box_Software_Architecture.docx` defines a production-grade custom audio daemon called **abox**. This section analyses what it specifies and why each decision was made.

### What abox is

A single real-time C++ daemon that:
- Owns all ALSA hardware exclusively (one clock, no drift)
- Runs the complete DSP graph (HPF → AEC → beamform → NS → AGC → detectors)
- Manages TTS playback (EQ → DRC → speaker)
- Exposes a UNIX socket API to the companion daemon
- Enforces barge-in
- Monitors its own health via a watchdog thread

Higher-level services (dialog, LLM) are separate processes that talk to abox over the socket. Keeping all audio in one process is the correct architectural principle.

### The two-plane design

abox splits into two planes that never touch each other directly:

**Data plane (real-time):**
- Audio I/O, DSP graph, AEC reference buffer, wake word, VAD, STT feed
- Runs at SCHED_FIFO priority
- Communicates only through lock-free ring buffers and atomic variables
- Never allocates memory, never calls blocking syscalls, never locks a mutex

**Control plane (non-real-time):**
- IPC socket server, session state machine, parameter hot-apply
- Runs at normal SCHED_OTHER priority
- Passes commands to the data plane through a lock-free command queue

**Why this split is non-negotiable:**

At 16kHz with 10ms periods, the RT thread has exactly 160 audio samples = 10ms to complete all processing. If it ever waits — for a mutex, a malloc, a file read — it misses the deadline. A missed deadline = an xrun = an audible glitch or dropout.

The specific threading model in the document:

| Thread | Role | Scheduling | Priority |
|--------|------|-----------|----------|
| `io_rt` | ALSA + entire DSP graph + playback | SCHED_FIFO | 80 |
| `detectors` | Wake word, VAD, STT, NPU inference | SCHED_FIFO | 60 |
| `control` | IPC server, state machine | SCHED_OTHER | nice 0 |
| `coproc` | rpmsg listener from MCU | SCHED_FIFO | 50 |
| `watchdog` | Liveness + deadline monitoring | SCHED_OTHER | nice 0 |

**Why mlockall:** Without locking all memory into RAM, the OS can swap pages to disk. A page fault during the 10ms audio window takes 1–50ms. One page fault = one xrun. `mlockall()` is called at startup before any RT threads start.

**Why CPU isolation:** On RK3588 (8 cores), adding `isolcpus=4,5` to the kernel command line reserves those cores for audio. The Linux scheduler never moves any other task onto them. This eliminates random preemption by kernel threads, IRQ handlers, and background processes.

**Why no mutex on the RT path:** Standard mutexes cause priority inversion. A low-priority thread L holds a mutex. High-priority RT thread H tries to acquire it — H blocks. Medium-priority thread M runs (doesn't need the mutex). H is now starved by M even though H has higher priority. Result: audio glitch. Lock-free structures (atomics, SPSC ring buffers) eliminate this entirely.

---

## 5. Component Deep Dive

### 5.1 ALSA I/O (`io` module)

**What it does:**  
Opens the ALSA PCM device, configures period size (160 frames = 10ms at 16kHz, 4 channels), starts capture and playback on the same clock, and handles xrun recovery.

**Why it matters:**  
This is the hardware interface. Nothing works without it. The period size choice (10ms) is a fundamental tradeoff: smaller periods = lower latency but higher CPU overhead from more frequent IRQ handling. 10ms is the standard for voice processing — matches the frame size expected by WebRTC APM, VAD, and STT engines.

**Xrun recovery:** When the playback buffer empties before the hardware reads it (underrun) or the capture buffer fills before software reads it (overrun), the hardware stalls. The software must call `snd_pcm_recover()`, re-sync the clock, and resume. If the graph engine misses its deadline frequently enough, xruns become audible — clicks, silence, artifacts.

**Alternative approach:**  
PipeWire owns this entirely. Our daemon connects to PipeWire as a client and receives a `process()` callback with a pre-filled capture buffer and an empty playback buffer. Period size, xrun recovery, and clock management are all inside PipeWire. We never call ALSA directly.

---

### 5.2 AEC Reference Buffer (`reference` module)

**What it does:**  
Captures the exact playback signal at the moment it enters the ALSA write buffer, stores it in a ring buffer with a configurable delay, and feeds the delayed signal to the AEC as the "far-end reference."

**Why this is subtle and critical:**  
AEC works by subtracting the echo from the mic signal. To subtract the echo, you need to know what the echo sounds like at the moment it reaches the microphone — not what was sent to the speaker. The acoustic path introduces delay:

```
Software write → DAC → Amplifier → Speaker → Air → Microphone → ADC
     0ms          2ms     5ms        3ms     10-80ms    0ms       2ms
                                                    ═══════════════
                                            Total delay: ~20-100ms (hardware dependent)
```

If the reference signal is fed to the AEC without compensating for this delay, the AEC is trying to cancel echo that has already passed. Even a 2-sample error at 16kHz (0.125ms) measurably degrades cancellation.

The `tail_ms` configuration parameter sets how long the echo reverb is expected to last. A reflective concrete room: 200ms. A soft furnished bedroom: 50ms. Too short: echo leaks through. Too long: wastes CPU.

**`nlp: on` (Non-Linear Processing):**  
Even after the linear adaptive filter cancels the direct echo, there's residual distortion from speaker non-linearity (clipping at high volumes, harmonic distortion from the amplifier). NLP applies a spectral suppressor on the AEC residual to clean this up. Essential at high playback volumes.

**Alternative approach:**  
WebRTC APM's AEC3 (the current version) includes built-in delay estimation. It correlates the mic signal with the reference signal to automatically figure out the delay. PipeWire has loopback source nodes that can capture the playback signal. Combined, the manual delay alignment is handled automatically. This eliminates the most difficult part of the reference buffer implementation.

---

### 5.3 Node Graph Engine (`graph` module)

**What it does:**  
A framework for connecting processing nodes in a directed graph. It:
- Allocates shared audio buffers
- Performs topological sort to determine execution order
- Calls each node's `process()` in order on every 10ms period
- Supports runtime rewiring for use-case switching (near-field ↔ far-field ↔ playback-only)

**Why it matters:**  
Different operating modes need different processing chains. A "music playback" mode doesn't need AEC or beamforming. A "far-field voice" mode needs more aggressive beamforming and NS than near-field. The graph lets you reconfigure the pipeline by rewiring nodes without stopping audio.

**In-place processing:**  
Nodes process audio in-place — each node reads from and writes to the same buffer. At 16kHz mono float, 160 frames = 640 bytes. This fits in L1 cache. Copying buffers between stages would double memory bandwidth and evict cache lines needlessly.

**Why float not int16:**  
Fixed-point requires careful scaling management to avoid overflow at every stage. Float gives headroom without thinking about bit depth at each node. On ARM Cortex-A with NEON SIMD, float math throughput is equal to integer.

**Alternative approach:**  
PipeWire is this module. PipeWire's filter node API provides a `process()` callback where our code runs on PipeWire's RT thread. PipeWire manages buffer allocation, clock-driven scheduling, and graph topology. We chain processing steps inside our filter callback. The node graph engine is completely eliminated.

---

### 5.4 HPF — High-Pass Filter

**What it does:**  
Removes all audio content below ~80Hz from the microphone signal before any other processing.

**Why it matters:**  
Microphones pick up physical vibrations and low-frequency rumble that human speech doesn't contain: HVAC systems, vibration from the device being touched or moved, electrical hum, acoustics in the room below 80Hz. These low-frequency components:
- Confuse the AEC (the adaptive filter wastes coefficients modelling them)
- Interfere with VAD (broadband energy metrics include the noise)
- Reduce STT accuracy

A 2nd-order Butterworth HPF at 80Hz is about 20 lines of math (biquad coefficients, transposed direct form II).

**Alternative approach:**  
WebRTC APM applies a HPF as its first stage automatically. When we use WebRTC APM for AEC/NS, HPF comes for free.

---

### 5.5 AEC — Acoustic Echo Cancellation

**What it does:**  
Removes the speaker output from the microphone input. When the device plays TTS through its speaker, that sound propagates through the air, bounces off surfaces, and re-enters the microphone. Without AEC, the device hears itself.

**Why it is the hardest problem:**  
Without AEC working correctly:
- The STT engine transcribes the device's own TTS speech (loop)
- The wake word detector triggers on the device's own voice
- Barge-in is impossible (the mic always "hears" the speaker, so VAD never triggers correctly during playback)

The AEC uses an adaptive filter that models the acoustic path from speaker to mic. The model is continuously updated as the room acoustics change (someone moves, a door opens, the device is picked up). At 16kHz with 128ms tail, the filter has 2,048 coefficients that are updated every period.

**Key parameters:**
- `tail_ms: 128` — models echoes up to 128ms after the original sound
- `nlp: on` — post-processing to remove non-linear echo residual

**Alternative approach:**  
WebRTC APM AEC3. This is Google's production echo canceller, battle-tested in billions of Google Meet, Chrome, and Android devices. It handles delay estimation automatically, is optimised for ARM NEON, and is available in `meta-openembedded` as a Yocto recipe. We use it as a drop-in library.

---

### 5.6 Beamforming

**What it does:**  
Uses the physical arrangement of 4 microphones to electronically "point" the microphone array toward the speaker and reject sound from other directions.

**Why it matters:**  
Sound from the target direction arrives at each microphone at slightly different times (the delay depends on the angle and the spacing between mics). Beamforming phase-aligns the signals from the target direction, then sums them — signal from the target direction adds coherently (+6dB for 4 mics), while noise from other directions averages toward zero.

For a 4-mic linear array with 3cm spacing:
- Maximum directional gain: ~6dB
- Null depth in perpendicular direction: ~15-20dB
- Practical SNR improvement in typical room: 4–8dB

This directly improves STT accuracy and wake word reliability when there's a TV or background noise source in a different direction.

**Direction of Arrival (DOA):**  
Beamforming also gives you the direction the speaker is coming from. This is used in barge-in: if near-end speech is detected during playback, but it's coming from the same direction as the speaker (not the user), it's likely echo residual or TV audio — not a real barge-in. The DOA gate prevents false interruptions.

**Alternative approach:**  
This is the one component without a simple drop-in replacement. Options:
- **SpeexDSP** has a basic beamformer — adequate for prototype
- **Custom delay-and-sum** implementation: ~150 lines of C, straightforward for linear arrays
- **For QEMU development:** skip entirely (QEMU has one virtual mono mic, no array geometry)
- **Defer to hardware phase:** implement properly when real 4-mic hardware is available

---

### 5.7 NS — Noise Suppression

**What it does:**  
Reduces stationary background noise remaining after AEC and beamforming. Targets sounds like HVAC, fans, traffic, rain — noise that is consistent over time (stationary).

**Types and tradeoffs:**

| Type | Quality | CPU cost | Artifacts |
|------|---------|----------|-----------|
| Spectral subtraction | Fair | Very low | Musical noise (tonal artifacts) |
| Wiener filter (WebRTC NS) | Good | Low | Slight over-suppression |
| RNNoise (96KB neural net) | Very good | Low | Minimal |
| DTLN / FENS (neural) | Excellent | Medium | Near-zero |

**"Musical noise"** is the artifact from classical spectral subtraction — when noise estimates are wrong, you get tonal chirping sounds that are often more distracting than the original noise.

**Alternative approach:**  
WebRTC APM NS (Wiener filter) for baseline — comes free with AEC3. RNNoise (96KB model, Apache 2.0) for better quality with minimal extra CPU. Both are available in meta-openembedded or easy to add as recipes. Neural NS (FENS) deferred to NPU phase.

---

### 5.8 AGC — Automatic Gain Control

**What it does:**  
Adjusts the capture gain in software so that speech arrives at the STT engine at a consistent level, regardless of:
- How loud the speaker is (shouting vs. whispering)
- How far away the speaker is (10cm vs. 3m)
- Variation between individual users

**Why it matters for STT:**  
STT models are trained on audio at a specific level (typically around -20 to -15 dBFS). Audio that is too quiet produces poor transcription. Audio that is too loud clips and produces poor transcription. AGC normalises the input to the sweet spot.

**Analog vs digital AGC:**  
Hardware codecs often have an analog AGC in the ADC path. This is faster to react (no buffering delay) but less controllable. Digital AGC in software allows precise level targeting and can cooperate with the VAD (don't adjust gain during silence, only during confirmed speech).

**Alternative approach:**  
WebRTC APM AGC2. Included with the AEC3 package. Hardware codec analog AGC as a first pass. Both together give excellent performance.

---

### 5.9 EQ — Parametric Equalizer

**What it does:**  
Applies a chain of biquad filters to the playback signal to compensate for the speaker's frequency response. Cheap speakers have weak bass and harsh, peaky highs. EQ makes the voice output sound natural and pleasant.

**Filter types:**
- **Peak/dip:** Boost or cut a band of frequencies around a centre frequency
- **Low shelf / high shelf:** Boost or cut all frequencies below/above a cutoff
- **High-pass / low-pass:** Roll off extreme frequencies

Configuration example from the architecture doc:
```yaml
eq:
  - {type: peak, f: 3000, q: 1.1, gain_db: 3}
  - {type: low_shelf, f: 200, gain_db: -2}
```

**Alternative approach:**  
Keep a simple version — this is 80 lines of C. Can be tuned by ear once real hardware is available. For QEMU, a flat EQ (no-op) is fine.

---

### 5.10 DRC — Dynamic Range Compression

**What it does:**  
A compressor + peak limiter on the playback path. When TTS audio peaks too high, DRC prevents clipping (which sounds like harsh crackling from the speaker). Also protects the speaker driver from over-excursion at high volumes.

**How a limiter works:**  
When the signal amplitude exceeds a threshold (e.g., -3 dBFS), apply gain reduction to bring it back under. A lookahead limiter can see 5–10ms into the future, allowing it to reduce gain before the peak arrives — zero distortion.

**Alternative approach:**  
Keep it — 60 lines of C. A simple peak limiter is sufficient for prototype.

---

### 5.11 Wake Word Detection

**What it does:**  
Continuously monitors the cleaned mic signal for a specific phrase ("Hey Ensoul"). When detected with confidence above a threshold, fires a WAKE event that transitions the session state machine from IDLE to WAKE.

**Why it must be separate from full STT:**  
Running Whisper or Zipformer STT continuously would consume 20–40% CPU at all times. Wake word models are tiny (~1–5MB) and use <1% CPU. They're designed to run perpetually.

**False wake rate:**  
How often the device wakes without being called. A rate of 1/hour is acceptable. 1/minute is extremely annoying. The confidence threshold is the tuning knob — higher threshold = fewer false wakes but risks missing real wakes.

**Alternative approach:**  
Sherpa-ONNX has built-in keyword spotting with ONNX models. OpenWakeWord (Apache 2.0, ~5MB models) is another excellent option. Both run comfortably on one A55 core. For QEMU development, use a keyboard trigger to simulate wake word (no mic array, no need for real wake word accuracy yet).

---

### 5.12 Detectors and Event Bus (`detect` module)

**What it does:**  
Runs wake word detector, VAD, and STT feed in the `detectors` thread (SCHED_FIFO 60). When any detector fires, it publishes a typed event to the event bus:

```cpp
struct Event {
    enum Type {
        WakeWord, SpeechStart, SpeechEnd,
        Doa, SourceId, BargeIn,
        SttPartial, SttFinal, TtsDone
    };
    Type   type;
    float  conf;       // detection confidence
    int    doa_deg;    // direction of arrival (degrees)
    string text;       // for STT events
};
```

**Why a separate thread:**  
NPU inference for wake word and VAD takes 2–8ms per frame. Running this inside the `io_rt` thread (which has only 10ms total) would risk deadline misses. A separate SCHED_FIFO thread at lower priority can take a bit longer without impacting audio I/O.

**Alternative approach:**  
Sherpa-ONNX provides its own threading internally. Its streaming decoder processes audio frames fed to it and fires callbacks (equivalent to events) when wake word, VAD onset, VAD offset, or STT partial/final results occur. We call `sherpa->AcceptWaveform(frame)` and receive typed callbacks. The detector module reduces to a thin wrapper around Sherpa-ONNX.

---

### 5.13 Session State Machine and Barge-In (`session` module)

**What it does:**  
This is the brain of the audio system. It manages 6 conversational states and the transitions between them. It is the only module that orchestrates all other components.

**State diagram:**

```
                    timeout / cancel
        ┌───────────────────────────────────────────┐
        │                                           │
      IDLE ──wake word──► WAKE ──VAD onset──► LISTENING ──endpoint──► THINKING
        ▲                                           ▲                     │
        │                                     barge-in!                speak()
        │                                           │                     │
        └──── TtsDone / complete ─────── SPEAKING ◄─────────────────────┘
```

**State descriptions:**

| State | What the device is doing |
|-------|--------------------------|
| IDLE | Waiting, wake word detector only |
| WAKE | Wake word heard, playing acknowledgment tone, arming VAD |
| LISTENING | VAD detected speech onset, streaming to STT |
| THINKING | VAD detected speech end (endpoint), STT finalising, LLM called |
| SPEAKING | TTS audio playing to speaker, monitoring for barge-in |
| (return to LISTENING) | Barge-in detected, playback stopped |

**Barge-in — the hardest state transition:**

Barge-in is the ability to interrupt the device while it is speaking. Without it, the user must wait for the device to finish every response — extremely frustrating for children.

While in SPEAKING state, the capture pipeline still runs fully (AEC → NS → AGC). The AEC-cleaned signal is monitored by VAD. When near-end speech is detected during playback, three gates must all pass before triggering barge-in:

1. **Energy gate:** Near-end speech energy must exceed a threshold. Real speech is significantly louder than AEC residual. This prevents residual echo from triggering false barge-in.

2. **Duration gate:** The detected speech must persist for >150ms. Clicks, coughs, and brief sounds are filtered out. Real speech is sustained.

3. **DOA gate (when hardware available):** The direction of the detected speech must match the user's expected direction, not the speaker direction. If the speech is coming from the speaker, it is echo residual. This is the most effective gate.

When all three gates pass:
1. `duck()` — immediately reduce playback volume
2. `stop()` — halt playback entirely
3. Flush the pre-roll ring buffer into STT — the first 300–400ms of the user's speech was being buffered continuously; this prevents losing the first words of the barge-in utterance
4. Transition to LISTENING

**Alternative approach:**  
Keep this module exactly — it is product logic, not infrastructure. For QEMU, simplify to energy gate + duration gate only (no DOA, single virtual mic). Add DOA gate when real hardware arrives. This is 200–300 lines of C++ that cannot be replaced by a library.

---

### 5.14 STT Adapter (`adapters` module)

**What it does:**  
Wraps the speech-to-text engine behind a common interface. The rest of the system doesn't know or care whether STT is running locally (Sherpa-ONNX) or in the cloud (Google, AWS, Azure). The adapter translates:
- Incoming: `AudioFrame` chunks from the detector thread
- Outgoing: `SttPartial` and `SttFinal` events to the event bus

**Why the adapter pattern:**  
You will switch STT engines. During prototype, you may use whisper.cpp. During development, Sherpa-ONNX. On hardware with NPU, RKNN-accelerated models. In production, possibly a cloud fallback for difficult accents. The adapter pattern means changing one file, not the whole system.

**Alternative approach:**  
Sherpa-ONNX streaming Zipformer adapter. Approximately 100 lines of C++. Feed PCM frames via `AcceptWaveform()`, receive partial and final results via callbacks. The model file is loaded at startup from a path in the YAML config.

---

### 5.15 TTS Adapter

**What it does:**  
Receives text from the companion daemon's `speak()` call, synthesises audio using Piper, and feeds the resulting PCM into the playback graph.

**Piper TTS specifics:**
- Time to first audio: ~50–80ms on A55 (very fast)
- Streaming synthesis: starts producing audio before the full sentence is synthesised
- Model sizes: low (~30MB), medium (~60MB), high quality (~130MB)
- Voice customisation: different voice models available
- Licence: MIT

**Alternative approach:**  
Piper TTS adapter. ~100 lines of C++. Keep as planned — this is the right tool.

---

### 5.16 Params / Configuration (`params` module)

**What it does:**  
Loads YAML configuration files at startup and hot-applies parameter updates to running nodes without stopping audio.

**Hot-apply mechanism:**  
Uses a double-buffer (shadow copy) pattern:
1. New parameters written to a shadow copy (non-RT thread, takes any time)
2. A single atomic pointer swap makes the RT thread see the new values on the next period
3. Zero glitch, zero lock, zero missed deadlines

**Use-case profiles:**  
Different rooms and distances need different tuning. The config defines named profiles:
```yaml
paths:
  near_field:   { aec: { tail_ms: 64 }, ns: { level: medium } }
  far_field:    { aec: { tail_ms: 128 }, ns: { level: high }, beamform: { ... } }
  quiet_room:   { agc: { target_dbfs: -24 }, ns: { level: low } }
```

**Alternative approach:**  
For prototype, static YAML config loaded at startup — no hot-apply needed. Hot-apply can be added later as a tuning feature. This defers significant implementation complexity.

---

### 5.17 IPC Server (`ipc` module)

**What it does:**  
A UNIX domain socket server that accepts connections from the companion daemon and other clients. Uses protobuf for message serialisation. Provides 7 RPC calls:

| RPC | Direction | Description |
|-----|-----------|-------------|
| `startSession(useCase)` | client → audio | Arm capture, select parameter profile |
| `speak(text, voice)` | client → audio | Synthesise and play text |
| `cancelSpeak()` | client → audio | Stop playback immediately |
| `setUseCase(path)` | client → audio | Switch parameter profile |
| `applyParams(blob)` | client → audio | Hot-tune a parameter |
| `subscribeEvents()` | audio → client | Stream of WakeWord/STT/TTS events |
| `getMetrics()` | client → audio | Xrun counts, latency, signal levels |

**Why a separate process for the companion daemon:**  
Audio processing and AI logic evolve independently. A crash in the LLM process doesn't kill the audio daemon. The audio daemon can restart the companion daemon if it dies. Security: the LLM process doesn't need root or RT privileges.

**Alternative approach:**  
Replace protobuf with newline-delimited JSON for the prototype. Same UNIX socket, same 7 calls, but no protobuf compile dependency. This is faster to develop and debug. JSON is sufficient until you need the throughput that protobuf provides (you probably never will for this API surface).

---

### 5.18 Co-Processor Interface (`coproc` module)

**What it does:**  
Communicates with an always-on MCU (Cortex-M class, running Zephyr/FreeRTOS) via the Linux rpmsg (remote processor messaging) subsystem. The MCU runs while the main RK3588 SoC is in deep sleep, listening for the wake word using a tiny model. When the wake word is detected, the MCU wakes the main SoC via a hardware interrupt and sends a wake event over rpmsg.

**Why this is the highest-risk item:**  
This requires:
- Separate RTOS firmware development (Zephyr or FreeRTOS)
- A wake word model small enough to run on a Cortex-M (~100KB flash, 64KB RAM)
- rpmsg driver integration in the Linux BSP
- Hardware mailbox / interrupt controller configuration in the device tree
- System suspend/resume logic that properly arms the co-processor before sleep

Each of these is a non-trivial engineering task. Combined, this is 2–3 months of work for an experienced embedded systems engineer. It is not needed for prototype or even EVT.

**Alternative approach (recommended):**  
Use one A55 little core as a software co-processor:
- Park the big A76 cores (WFI / low-frequency)
- Pin wake word detection process to one A55 core at 200–400MHz
- Sherpa-ONNX wake word uses ~1–2% CPU at this frequency = ~0.5W idle
- On wake detection, ramp all cores to full frequency
- Main SoC never fully sleeps, but idle power is acceptable for a plugged-in device

This eliminates the coproc module entirely. The rpmsg firmware risk disappears. Add the real hardware co-processor path as a v2 feature for a battery SKU.

---

### 5.19 Telemetry (`telemetry` module)

**What it does:**  
Two functions:
1. **PCM taps:** Save audio at key points in the pipeline (raw mic, post-AEC, post-NS, playback) to WAV files for offline analysis. Without this, debugging audio quality issues in the field is impossible.
2. **Metrics:** Track xrun counts, RT deadline misses, per-node processing time, signal levels, and detection confidence scores.

**Alternative approach:**  
- PipeWire has `pw-record` — a command-line tool that can tap any node in the PipeWire graph and save to WAV. Zero code required.
- Add Prometheus metrics export for xruns and processing time. `prometheus-cpp` is a simple header-only library.
- This eliminates the telemetry module and replaces it with existing tooling.

---

## 6. VAD — What It Is and Why It Matters

**VAD = Voice Activity Detection.** It answers one question every 10–20ms: *"is a human speaking right now, or is it silence/noise?"*

### Why VAD exists

Running full STT continuously is extremely expensive. STT engines like Sherpa-ONNX Zipformer use ~15–30% CPU. Running at 100% duty cycle would prevent the device from doing anything else. VAD is a tiny model (~2MB, <1% CPU) that gatekeeps the STT — only pass audio to the expensive model when a human is actually talking.

### VAD's two jobs

**Job 1 — Speech onset detection (SPEECH_START):**
- Detected within ~30ms of speech beginning
- Triggers: wake from WAKE → LISTENING, start feeding STT
- False positive cost: accidentally feeding noise to STT (minor)
- False negative cost: missing the first syllable of the user's speech (bad UX)

**Job 2 — Speech offset / endpointing (SPEECH_END):**
- Detected when speech has been absent for a configurable silence threshold (typically 250–400ms)
- Triggers: LISTENING → THINKING, finalise STT result, call LLM
- **This is the largest single contributor to perceived latency**
- False positive cost: cutting off the user mid-sentence (very bad UX)
- False negative cost: waiting too long after the user finishes (feels sluggish)

### The endpointing tradeoff

```
Silence threshold:  200ms   300ms   400ms   500ms
Perceived speed:    Fast    Good    Slow    Very slow
Cut-off risk:       High    Low     Minimal  None
```

The recommended starting point is 300ms. This feels responsive while reliably not cutting off normal speech. Can be tuned per use-case (children tend to speak with more pauses than adults, so the toy may need 350–400ms).

### Silero VAD

The VAD used in our approach. Key properties:
- Model size: 1.8MB
- CPU on A55: <0.5%
- Onset latency: ~30ms
- Built into Sherpa-ONNX (no separate integration needed)
- Licence: MIT

---

## 7. STT Decision — Sherpa-ONNX vs Whisper.cpp

### The architectural difference

**Whisper.cpp** uses an encoder-decoder Transformer architecture. The encoder processes a fixed-length audio chunk (typically 30 seconds or a shorter configurable window). The decoder then generates the transcription. The encoder must see the complete chunk before the decoder produces a single token.

**Sherpa-ONNX streaming Zipformer** uses a Conformer-based streaming architecture. Audio is processed in 40–80ms frames. The model maintains state between frames and can emit tokens continuously as speech proceeds. Partial results are available every 100–200ms. By the time the user finishes speaking, the transcription is 80–90% complete.

### Comparison table

| Dimension | Whisper.cpp | Sherpa-ONNX (Zipformer) |
|-----------|-------------|------------------------|
| Architecture | Encoder-decoder | Streaming Conformer |
| Designed for | Batch transcription | Real-time streaming |
| Starts transcribing | After speech ends + chunk boundary | While user is still talking |
| Chunk size | 1s–30s window | 10–40ms frames |
| Partial results | Unreliable, polling-based | Native, every ~100ms |
| Latency after speech ends | 500ms – 2s | 80 – 200ms |
| tiny model RAM | ~75MB | ~50MB |
| A55 real-time? | Barely (tiny.en only) | Yes, comfortably |
| Streaming VAD integration | Separate, manual | Built-in (Silero) |
| Wake word integration | Separate | Built-in |
| RKNN NPU support | Via third-party port | Native ONNX → RKNN export |
| Licence | MIT | Apache 2.0 |

### Why Whisper fails for real-time on embedded

The encoder processes audio in fixed windows. Even with 3-second windows (the smallest practical), you have:
- 3 seconds of audio to collect before processing starts
- Then 500–800ms of encoder+decoder inference on A55
- Then another 3 seconds...

This gives a minimum latency floor of 3–4 seconds from speech end to final transcription — unacceptable. The streaming workarounds (sliding window, VAD-triggered chunking) partially improve this but add complexity and hurt accuracy at chunk boundaries.

### Why Sherpa-ONNX wins

The streaming architecture means the model is already processing audio while the user is talking. When VAD detects speech end (SPEECH_END), the final result is available within 80–200ms. The STT latency contribution to the total loop is negligible.

**Model to use:**  
`sherpa-onnx-streaming-zipformer-en-2023-06-26`
- English optimised
- ~70MB
- Runs in real-time on Cortex-A55
- Apache 2.0 licence
- Downloads from the Sherpa-ONNX releases page

**Decision: Use Sherpa-ONNX.**

---

## 8. Latency Budget

The perceived user experience depends on the complete loop from "user stops talking" to "device starts speaking."

### Full latency breakdown

```
User finishes speaking
        │
        ▼ ~300ms ── VAD offset / endpointing (silence threshold)
        │
        ▼ ~80ms  ── STT finalises (Sherpa-ONNX Zipformer, already streaming)
        │
        ▼ ~0ms   ★ PLAY ACKNOWLEDGMENT SOUND / ANIMATE EYES IMMEDIATELY
        │           (This is the <300ms moment from the board brief)
        │           User perceives instant response here
        │
        ▼ ~400ms ── LLM first token (cloud, network dependent)
        │
        ▼ ~80ms  ── Piper TTS first audio chunk synthesised
        │
        ▼ ~20ms  ── Audio reaches speaker
                ──────────────────────────────────────────
Total time user waits for first TTS word: ~880ms (0.9s)
Total before acknowledgment: ~380ms
```

### Tuning levers

| Lever | Default | Faster | Trade-off |
|-------|---------|--------|-----------|
| VAD silence threshold | 300ms | 200ms | More speech cut-offs |
| Sherpa chunk size | 40ms | 20ms | Higher CPU usage |
| Piper model quality | medium | low | Slightly less natural voice |
| LLM (cloud) | gpt-4o | gpt-4o-mini | Worse answers |
| LLM (local) | 3B on NPU | 1B on NPU | Worse answers |

### The acknowledgment trick

The 300ms local acknowledgment mentioned in the board briefing is achieved by:
1. VAD fires SPEECH_END
2. **Immediately** trigger a visual acknowledgment (eyes animate, listening indicator changes)
3. **Simultaneously** finalise STT and call LLM
4. Begin TTS as soon as first LLM tokens arrive

The user perceives the device responding at step 2 (~300ms). The actual spoken response at step 4 (~880ms) feels fast because the device already showed it understood.

---

## 9. Revised Architecture — Our Approach

Rather than building a custom audio daemon from scratch (the original abox design — ~15,000 lines of production C++), we compose existing mature open-source libraries.

### Architecture diagram

```
┌──────────────────────────────────────────────────────────────┐
│                   companion-daemon (existing)                 │
│           LLM, personality, emotion engine, hologram          │
└─────────────────────────────┬────────────────────────────────┘
                              │ UNIX socket (JSON)
                              │ startSession / speak / cancelSpeak
                              │ ← events: WakeWord / SttFinal / TtsDone
┌─────────────────────────────▼────────────────────────────────┐
│                    ensoul-audio (new daemon)                  │
│                     ~1,500 lines C++                          │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐      │
│  │              PipeWire client                         │      │
│  │  Capture filter: WebRTC APM (HPF + AEC3 + NS + AGC) │      │
│  │  Playback filter: EQ → DRC                           │      │
│  └─────────────────────────────────────────────────────┘      │
│                                                               │
│  ┌───────────────────────┐   ┌────────────────────────────┐   │
│  │    Sherpa-ONNX         │   │        Piper TTS            │   │
│  │  Wake word (ONNX)      │   │  text → PCM audio          │   │
│  │  VAD (Silero)          │   │  ~80ms to first audio      │   │
│  │  STT (Zipformer)       │   │                            │   │
│  └───────────────────────┘   └────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐      │
│  │          Session state machine (custom)              │      │
│  │   IDLE → WAKE → LISTENING → THINKING → SPEAKING     │      │
│  │   Barge-in: energy gate + duration gate              │      │
│  └─────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────┘
                              │ PipeWire graph
┌─────────────────────────────▼────────────────────────────────┐
│              PipeWire (audio server)                          │
│   ALSA clock, buffer management, RT scheduling, xrun recovery │
└─────────────────────────────┬────────────────────────────────┘
                              │ ALSA PCM
┌─────────────────────────────▼────────────────────────────────┐
│              Kernel: ALSA + audio codec driver                │
│     QEMU: virtio-snd  │  Hardware: I2S + codec (TBD)         │
└──────────────────────────────────────────────────────────────┘
```

### What this means in practice

| Concern | Original abox | Our approach |
|---------|--------------|-------------|
| Lines of custom C++ | ~15,000 | ~1,500 |
| Libraries integrated | 8+ (build from scratch) | 3 (PipeWire, Sherpa-ONNX, Piper) |
| RT thread management | Manual (5 threads, priorities, mlockall) | PipeWire handles it |
| ALSA xrun recovery | Custom | PipeWire handles it |
| AEC | Custom adaptive filter | WebRTC APM AEC3 |
| NS | Custom spectral / neural | WebRTC APM + RNNoise |
| STT | whisper.cpp (batch, slow) | Sherpa-ONNX (streaming, fast) |
| Wake word | Separate integration | Sherpa-ONNX built-in |
| VAD | Separate integration | Sherpa-ONNX built-in |
| Co-processor firmware | 3 months custom RTOS work | A55 software wake word |

---

## 10. Open Source Components

### PipeWire

**What:** Modern Linux audio server. Replaces PulseAudio and JACK. Handles ALSA, routing, mixing, clock management, RT scheduling, and inter-process audio.

**Why use it:**
- Already the default audio server on modern Linux distributions
- Has dedicated RT thread with mlockall and SCHED_FIFO built-in
- webrtc-audio-processing plugin applies AEC/NS/AGC as a filter node
- `pw-record` lets you tap any point in the audio graph for debugging
- Yocto recipe available in meta-openembedded

**Performance:** Runs on Raspberry Pi 4 (which is less powerful than RK3588) as the default audio server. Latency as low as 2ms round-trip.

### WebRTC Audio Processing Module (webrtc-audio-processing)

**What:** Google's production audio DSP library. Used in billions of Chrome, Android, and Google Meet instances. Provides: HPF, AEC3 (echo cancellation), NS (noise suppression), AGC2 (automatic gain control).

**Why use it:**
- AEC3 is state-of-the-art — handles delay estimation automatically
- Extensively tested in real-world conditions
- ARM NEON optimised
- Apache 2.0 licence
- Available as `webrtc-audio-processing` in meta-openembedded

**CPU cost on A55:** ~3–5% total for HPF + AEC + NS + AGC at 16kHz mono.

### Sherpa-ONNX

**What:** C++ framework for audio AI inference. Bundles: wake word detection, VAD (Silero), streaming STT (Zipformer, Whisper), and TTS. All backed by ONNX runtime.

**Why use it:**
- One dependency does wake word + VAD + STT
- Streaming architecture — low latency, partial results during speech
- ONNX-based: models run on CPU for QEMU, export to RKNN NPU for hardware later
- Apache 2.0 licence
- Pre-built ARM binaries available, or build via CMake

**Models:**
- Wake word: `sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01` (~5MB)
- VAD: Silero (built-in, ~2MB)
- STT: `sherpa-onnx-streaming-zipformer-en-2023-06-26` (~70MB)

### Piper TTS

**What:** Fast, local neural text-to-speech. ~80ms to first audio on Cortex-A55. Small models, natural voice quality.

**Why use it:**
- Best latency of any open-source local TTS
- Streaming synthesis (produces audio before full sentence is synthesised)
- Multiple voice models including different accents and styles
- MIT licence
- ~30–130MB model size (choose based on quality requirement)

### RNNoise (optional, for better NS)

**What:** A 96KB neural network for noise suppression, originally from Mozilla.

**Why use it:**
- Far better quality than classical spectral subtraction
- No "musical noise" artifacts
- 96KB model — runs on any hardware
- BSD licence
- Can chain with WebRTC APM NS for best results

---

## 11. Component-by-Component Elimination Map

| Original abox module | Status | Replaced by | Notes |
|---------------------|--------|-------------|-------|
| `io` — ALSA | Eliminated | PipeWire | PipeWire owns ALSA |
| `reference` — AEC delay align | Eliminated | WebRTC APM AEC3 auto-delay | AEC3 estimates delay automatically |
| `graph` — node graph engine | Eliminated | PipeWire filter graph | PipeWire IS the graph engine |
| `nodes/hpf` | Eliminated | WebRTC APM built-in | Included free with AEC |
| `nodes/aec` | Drop-in library | WebRTC APM AEC3 | ~10 lines of integration code |
| `nodes/ns` | Drop-in library | WebRTC APM NS + RNNoise | ~10 lines of integration code |
| `nodes/beamform` | Deferred | SpeexDSP or custom | Skip for QEMU; add on hardware |
| `nodes/agc` | Drop-in library | WebRTC APM AGC2 | ~5 lines of integration code |
| `nodes/eq` | Keep (small) | Custom biquad chain | ~80 lines, keep |
| `nodes/drc` | Keep (small) | Custom peak limiter | ~60 lines, keep |
| `nodes/src` | Eliminated | PipeWire handles SRC | PipeWire does rate conversion |
| `nodes/cng` | Deferred | Skip for MVP | Low priority |
| `ml` — RKNN inference | Drop-in library | Sherpa-ONNX ONNX runtime | Handles NPU when on hardware |
| `detect` — event bus | Drop-in library | Sherpa-ONNX callbacks | Callbacks replace the event bus |
| `session` — state machine | Keep (core logic) | Custom C++ | Product logic, must build |
| `session` — barge-in | Keep (simplified) | Custom C++ (no DOA for QEMU) | DOA gate deferred to hardware |
| `adapters/stt` | Drop-in library | Sherpa-ONNX streaming | ~100 lines |
| `adapters/tts` | Keep | Piper TTS | ~100 lines |
| `params` — hot-apply | Deferred | Static YAML at startup | Add hot-apply later |
| `ipc` — protobuf | Simplified | JSON over UNIX socket | Same 7 calls, simpler encoding |
| `coproc` — rpmsg firmware | Eliminated | A55 software wake word | Saves 3+ months of work |
| `telemetry` — PCM taps | Eliminated | PipeWire `pw-record` | Existing tooling |
| `telemetry` — metrics | Simplified | Prometheus counters | ~50 lines |
| Threading + mlockall | Eliminated | PipeWire handles it | PipeWire manages RT thread |
| CPU affinity (isolcpus) | Config only | Yocto kernel config | One line in machine config |

**Result: ~15,000 lines custom C++ → ~1,500 lines integration C++**

---

## 12. Co-Processor — Risk and Alternative

### What the original design requires

A separate microcontroller (Cortex-M class) running Zephyr or FreeRTOS that:
1. Runs a tiny wake word model continuously while the main SoC is in deep sleep
2. Communicates with the main SoC via rpmsg when wake word is detected
3. Also handles mic beamforming and VAD at ultra-low power

**Why this is high risk:**
- Requires a second firmware codebase (Zephyr/FreeRTOS) — completely different from Linux
- Wake word model must fit in ~100KB flash and 64KB RAM
- rpmsg integration requires both kernel BSP work and firmware work
- System suspend/resume must properly arm the co-processor before sleep
- Hardware mailbox/interrupt controller must be configured in device tree
- Debugging two separate systems simultaneously is significantly harder
- **Estimated effort: 3+ months for an experienced embedded firmware engineer**

### The practical alternative

The RK3588 has a heterogeneous CPU cluster:
- 4× Cortex-A76 cores (big, high performance)
- 4× Cortex-A55 cores (little, power efficient)

**Strategy:**
- Keep big cores (A76) in WFI (low-power idle) between interactions
- Pin wake word process to one A55 core at 200–400MHz
- Sherpa-ONNX wake word: ~1–2% CPU at 400MHz = negligible power
- On wake detection: ramp all cores to full frequency, start full pipeline

**Power comparison:**
- Real co-processor solution: ~50–100mW idle
- Software wake word on A55 at 400MHz: ~300–500mW idle
- Difference: ~250–400mW

For a device that is plugged into mains power (which v1 almost certainly is), 400mW idle is completely acceptable. This is equivalent to leaving an LED nightlight on. The engineering time saved (3+ months) far outweighs the power cost.

**When to add real co-processor:**
- When a battery SKU is required
- When idle power becomes a product specification
- Not before v2

---

## 13. Development Build Plan

Development proceeds in phases on QEMU ARM64 using the existing kas configuration. All phases produce working, testable software.

### Phase 0 — Bootable QEMU image with audio

**Goal:** QEMU ARM64 boots, PipeWire running, `aplay` and `arecord` work with virtual audio.

**What to build:**
- Add PipeWire and wireplumber to `anime-ai-image.bb`
- Add webrtc-audio-processing to image
- Configure QEMU virtio-snd device in kas config
- Verify with `pw-cli` and `aplay -l`

**Exit criteria:** `aplay /usr/share/sounds/test.wav` produces audio output in QEMU.

**Estimated time:** 1–2 days

---

### Phase 1 — Sherpa-ONNX working in QEMU

**Goal:** Sherpa-ONNX STT processes a WAV file and produces a transcription.

**What to build:**
- Add Sherpa-ONNX as a Yocto recipe (CMake-based, straightforward)
- Download and package the Zipformer model
- Write a test harness: feed a WAV file, print transcription

**Exit criteria:** `abox-test input.wav` prints the correct transcription of a pre-recorded WAV file.

**Estimated time:** 2–3 days

---

### Phase 2 — ensoul-audio daemon core

**Goal:** Running daemon that captures from PipeWire mic, applies WebRTC APM, feeds Sherpa-ONNX, and prints STT results.

**What to build:**
- PipeWire capture client with WebRTC APM filter
- Sherpa-ONNX streaming pipeline fed from PipeWire frames
- Session state machine (IDLE / LISTENING / THINKING)
- VAD-triggered STT (Silero VAD → start STT → endpoint → print result)

**Exit criteria:** Speak into QEMU mic (routed through host), see transcript printed to console in near-real-time.

**Estimated time:** 1 week

---

### Phase 3 — Piper TTS and playback

**Goal:** The daemon synthesises and plays TTS audio in response to a hardcoded LLM response.

**What to build:**
- Piper TTS Yocto recipe
- TTS adapter: text → PCM → PipeWire playback
- EQ and DRC nodes in the playback filter
- Basic SPEAKING state with TtsDone event

**Exit criteria:** After STT produces a result, a hardcoded response is spoken through QEMU audio output.

**Estimated time:** 2–3 days

---

### Phase 4 — Full session state machine + barge-in

**Goal:** Complete state machine with barge-in working end-to-end.

**What to build:**
- All 6 states fully implemented
- Barge-in: energy gate + duration gate (no DOA for QEMU)
- Pre-roll buffer flush into STT on barge-in
- Timeout handling in each state

**Exit criteria:** Device can be interrupted mid-speech and correctly transitions to LISTENING.

**Estimated time:** 3–4 days

---

### Phase 5 — IPC socket → companion daemon

**Goal:** Full conversation loop working end-to-end with the existing companion daemon.

**What to build:**
- JSON-over-UNIX-socket IPC server (7 calls)
- Connect companion daemon's LLM response to `speak()` call
- Connect `SttFinal` event to companion daemon's input
- Wake word (simulated via API for QEMU)

**Exit criteria:** Complete conversation loop: wake trigger → STT → companion daemon → LLM → TTS → spoken response → barge-in works.

**Estimated time:** 3–4 days

---

### Phase 6 — Real hardware (future)

When RK3588 hardware is available:
- Replace virtio-snd with real codec + I2S device tree
- Enable 4-channel capture (4-mic array)
- Add beamforming (SpeexDSP or custom delay-and-sum)
- Add DOA gate to barge-in
- Export Sherpa-ONNX models to RKNN for NPU acceleration
- Tune AEC tail length, NS level, AGC target for the physical room

**Total to working voice loop on QEMU: 3–4 weeks**

---

## 14. Design Decisions Log

| Decision | Choice | Rationale | Alternative considered |
|----------|--------|-----------|----------------------|
| Audio server | PipeWire | Eliminates custom ALSA/RT/clock code | Raw ALSA (more complex) |
| AEC/NS/AGC | WebRTC APM | Production quality, embedded-optimised, free | Custom DSP (6+ months) |
| STT | Sherpa-ONNX streaming Zipformer | Streaming architecture, low latency, ONNX = NPU-ready | Whisper.cpp (batch, higher latency) |
| Wake word | Sherpa-ONNX built-in | Same framework as STT, reduces dependencies | OpenWakeWord (also good) |
| VAD | Silero (built into Sherpa) | Same framework, excellent quality | WebRTC VAD (slightly worse) |
| TTS | Piper | Best latency of open-source options, streaming | Coqui TTS (heavier), Cloud TTS (latency) |
| IPC encoding | JSON (prototype) | Fast to build and debug | Protobuf (add when needed) |
| Co-processor | A55 software wake word | Eliminates 3 months of RTOS firmware work | MCU co-processor (add in v2 for battery SKU) |
| NS quality | WebRTC APM NS | Built-in, zero extra integration | RNNoise (add if WebRTC NS is insufficient) |
| Beamform | Defer to hardware phase | QEMU has single virtual mic, not needed yet | SpeexDSP or custom (add when hardware arrives) |
| Hot-apply config | Deferred to later | Static YAML sufficient for prototype | Atomic double-buffer (add for production tuning) |
| Endpointing silence | 300ms (starting point) | Balance between speed and cut-off risk | 200ms (faster, more cut-offs), 400ms (safer) |

---

*This document captures the complete audio system design discussion as of June 2026. It will be updated as hardware decisions are finalised and implementation progresses.*
