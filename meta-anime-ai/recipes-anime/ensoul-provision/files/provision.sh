#!/bin/sh
# Ensoul AI first-boot provisioning.
# Runs as a systemd oneshot at boot; skips if model already present.

set -e

MODEL_DIR="/opt/ensoul/models/stt"
MODEL_NAME="sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_NAME}.tar.bz2"
ENCODER="$MODEL_DIR/$MODEL_NAME/encoder-epoch-99-avg-1.int8.onnx"

if [ -f "$ENCODER" ]; then
    echo "ensoul-provision: STT model already present, nothing to do"
    exit 0
fi

echo "ensoul-provision: downloading STT model (streaming extract, int8 only)..."
mkdir -p "$MODEL_DIR"

# Stream the tarball through tar so the 122MB compressed archive never
# touches disk — only the four int8 files (~42MB total) are written.
wget -q -O - "$MODEL_URL" | tar -xjf - -C "$MODEL_DIR" \
    "$MODEL_NAME/encoder-epoch-99-avg-1.int8.onnx" \
    "$MODEL_NAME/decoder-epoch-99-avg-1.int8.onnx" \
    "$MODEL_NAME/joiner-epoch-99-avg-1.int8.onnx" \
    "$MODEL_NAME/tokens.txt"

echo "ensoul-provision: STT model installed at $MODEL_DIR/$MODEL_NAME"
