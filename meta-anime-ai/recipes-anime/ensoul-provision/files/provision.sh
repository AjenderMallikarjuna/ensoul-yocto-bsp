#!/bin/sh
# Ensoul AI first-boot provisioning.
# Runs as a systemd oneshot at boot; each block is idempotent.

set -e

# ── STT model (sherpa-onnx Zipformer 20M EN int8, ~42 MB) ─────────────────
STT_DIR="/opt/ensoul/models/stt"
STT_NAME="sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
STT_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${STT_NAME}.tar.bz2"
STT_ENCODER="$STT_DIR/$STT_NAME/encoder-epoch-99-avg-1.int8.onnx"

if [ -f "$STT_ENCODER" ]; then
    echo "ensoul-provision: STT model already present"
else
    echo "ensoul-provision: downloading STT model (streaming extract, int8 only)..."
    mkdir -p "$STT_DIR"
    wget -q -O - "$STT_URL" | tar -xjf - -C "$STT_DIR" \
        "$STT_NAME/encoder-epoch-99-avg-1.int8.onnx" \
        "$STT_NAME/decoder-epoch-99-avg-1.int8.onnx" \
        "$STT_NAME/joiner-epoch-99-avg-1.int8.onnx" \
        "$STT_NAME/tokens.txt"
    echo "ensoul-provision: STT model installed"
fi

# ── Piper TTS voice model (hfc_female medium, ~61 MB) ─────────────────────
TTS_DIR="/opt/ensoul/models/tts"
TTS_VOICE="en_US-hfc_female-medium"
TTS_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/hfc_female/medium"
TTS_MODEL="$TTS_DIR/${TTS_VOICE}.onnx"

if [ -f "$TTS_MODEL" ]; then
    echo "ensoul-provision: Piper voice model already present"
else
    echo "ensoul-provision: downloading Piper voice model (~61 MB)..."
    mkdir -p "$TTS_DIR"
    wget -q -O "$TTS_MODEL"        "${TTS_BASE}/${TTS_VOICE}.onnx"
    wget -q -O "${TTS_MODEL}.json" "${TTS_BASE}/${TTS_VOICE}.onnx.json"
    echo "ensoul-provision: Piper voice model installed"
fi

# ── KWS model for "Hey Aria" (sherpa-onnx Zipformer 3.3M, ~4 MB) ──────────
KWS_DIR="/opt/ensoul/models/kws"
KWS_NAME="sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
KWS_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/${KWS_NAME}.tar.bz2"
KWS_ENCODER="$KWS_DIR/$KWS_NAME/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"

if [ -f "$KWS_ENCODER" ]; then
    echo "ensoul-provision: KWS model already present"
else
    echo "ensoul-provision: downloading KWS model (~4 MB)..."
    mkdir -p "$KWS_DIR"
    wget -q -O - "$KWS_URL" | tar -xjf - -C "$KWS_DIR" \
        "$KWS_NAME/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx" \
        "$KWS_NAME/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx" \
        "$KWS_NAME/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx" \
        "$KWS_NAME/tokens.txt"
    echo "ensoul-provision: KWS model installed"
fi

echo "ensoul-provision: done"
