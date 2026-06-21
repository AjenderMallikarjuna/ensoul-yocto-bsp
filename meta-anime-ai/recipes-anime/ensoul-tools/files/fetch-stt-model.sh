#!/bin/sh
# Download the sherpa-onnx streaming Zipformer small English model.
# Run once inside QEMU (requires outbound internet via QEMU slirp).
# Model lands in /opt/ensoul/models/stt/ ready for sherpa-onnx-alsa.

set -e

MODEL_DIR="/opt/ensoul/models/stt"
MODEL_NAME="sherpa-onnx-streaming-zipformer-small-2023-06-26"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_NAME}.tar.bz2"

if [ -d "${MODEL_DIR}/${MODEL_NAME}" ]; then
    echo "Model already present at ${MODEL_DIR}/${MODEL_NAME}"
    exit 0
fi

echo "Downloading ${MODEL_NAME} (~65 MB)..."
mkdir -p "${MODEL_DIR}"
cd "${MODEL_DIR}"
wget -q --show-progress "${MODEL_URL}" -O "${MODEL_NAME}.tar.bz2"
tar -xjf "${MODEL_NAME}.tar.bz2"
rm "${MODEL_NAME}.tar.bz2"
echo "Done. Model at ${MODEL_DIR}/${MODEL_NAME}"
echo ""
echo "Run STT with:"
echo "  PIPEWIRE_RUNTIME_DIR=/run/pipewire sherpa-onnx-alsa \\"
echo "    --encoder  ${MODEL_DIR}/${MODEL_NAME}/encoder-epoch-99-avg-1-chunk-16-left-128.onnx \\"
echo "    --decoder  ${MODEL_DIR}/${MODEL_NAME}/decoder-epoch-99-avg-1-chunk-16-left-128.onnx \\"
echo "    --joiner   ${MODEL_DIR}/${MODEL_NAME}/joiner-epoch-99-avg-1-chunk-16-left-128.onnx \\"
echo "    --tokens   ${MODEL_DIR}/${MODEL_NAME}/tokens.txt \\"
echo "    --num-threads 2 \\"
echo "    hw:0,0"
