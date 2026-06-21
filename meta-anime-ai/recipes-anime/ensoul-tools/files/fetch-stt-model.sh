#!/bin/sh
# Download the sherpa-onnx streaming Zipformer small English model.
# Run once inside QEMU (requires outbound internet via QEMU slirp).
# Model lands in /opt/ensoul/models/stt/ ready for sherpa-onnx-alsa.

set -e

MODEL_DIR="/opt/ensoul/models/stt"
# 20M-parameter streaming English model — small enough for RK3588 CPU inference
MODEL_NAME="sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_NAME}.tar.bz2"

if [ -d "${MODEL_DIR}/${MODEL_NAME}" ]; then
    echo "Model already present at ${MODEL_DIR}/${MODEL_NAME}"
    exit 0
fi

echo "Downloading ${MODEL_NAME} (~122 MB)..."
mkdir -p "${MODEL_DIR}"
cd "${MODEL_DIR}"
# BusyBox wget: no --show-progress, use -q for quiet
wget -q "${MODEL_URL}" -O "${MODEL_NAME}.tar.bz2"
echo "Extracting..."
tar -xjf "${MODEL_NAME}.tar.bz2"
rm "${MODEL_NAME}.tar.bz2"
echo "Done. Model at ${MODEL_DIR}/${MODEL_NAME}"
echo ""
echo "Run offline STT on a WAV file:"
echo "  sherpa-onnx \\"
echo "    --encoder  ${MODEL_DIR}/${MODEL_NAME}/encoder-epoch-99-avg-1.int8.onnx \\"
echo "    --decoder  ${MODEL_DIR}/${MODEL_NAME}/decoder-epoch-99-avg-1.int8.onnx \\"
echo "    --joiner   ${MODEL_DIR}/${MODEL_NAME}/joiner-epoch-99-avg-1.int8.onnx \\"
echo "    --tokens   ${MODEL_DIR}/${MODEL_NAME}/tokens.txt \\"
echo "    --num-threads 2 \\"
echo "    /path/to/audio.wav"
echo ""
echo "Run live mic STT (ALSA device hw:1,0 = HDA Intel via WSLg):"
echo "  sherpa-onnx-alsa \\"
echo "    --encoder  ${MODEL_DIR}/${MODEL_NAME}/encoder-epoch-99-avg-1.int8.onnx \\"
echo "    --decoder  ${MODEL_DIR}/${MODEL_NAME}/decoder-epoch-99-avg-1.int8.onnx \\"
echo "    --joiner   ${MODEL_DIR}/${MODEL_NAME}/joiner-epoch-99-avg-1.int8.onnx \\"
echo "    --tokens   ${MODEL_DIR}/${MODEL_NAME}/tokens.txt \\"
echo "    --num-threads 2 \\"
echo "    hw:1,0"
