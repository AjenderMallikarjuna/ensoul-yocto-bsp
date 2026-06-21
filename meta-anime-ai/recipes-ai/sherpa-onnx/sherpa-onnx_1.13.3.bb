SUMMARY = "Sherpa-ONNX: on-device speech processing toolkit"
DESCRIPTION = "Pre-built aarch64 CPU shared library package providing \
streaming ASR, offline ASR, VAD, TTS, and keyword spotting via ONNX Runtime. \
Phase 1 of Ensoul AI: STT using the streaming Zipformer model."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "1.13.3"

SRC_URI = "https://github.com/k2-fsa/sherpa-onnx/releases/download/v${PV}/sherpa-onnx-v${PV}-linux-aarch64-shared-cpu.tar.bz2"
SRC_URI[sha256sum] = "dca81c3d36c68e84949158a993e2ea99055bcecc96893f93739209fbe2eac649"

S = "${WORKDIR}/sherpa-onnx-v${PV}-linux-aarch64-shared-cpu"

# Pre-built aarch64 binaries fetched on an x86_64 build host:
# arch    — cross-architecture is intentional (target = aarch64)
# already-stripped — upstream ships stripped release binaries
INSANE_SKIP:${PN} = "arch already-stripped"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${libdir}
    install -m 0755 ${S}/lib/libonnxruntime.so          ${D}${libdir}/
    install -m 0755 ${S}/lib/libsherpa-onnx-c-api.so    ${D}${libdir}/
    install -m 0755 ${S}/lib/libsherpa-onnx-cxx-api.so  ${D}${libdir}/

    install -d ${D}${bindir}
    for b in ${S}/bin/*; do
        install -m 0755 "$b" ${D}${bindir}/
    done

    # Directory for STT models (populated at runtime or by a model recipe)
    install -d ${D}/opt/ensoul/models/stt
}

FILES:${PN} = " \
    ${libdir}/libonnxruntime.so \
    ${libdir}/libsherpa-onnx-c-api.so \
    ${libdir}/libsherpa-onnx-cxx-api.so \
    ${bindir}/sherpa-onnx* \
    ${bindir}/sense-voice-simulate-streaming-alsa-cxx-api \
    ${bindir}/zipformer-ctc-simulate-streaming-alsa-cxx-api \
    /opt/ensoul/models/stt \
"

# Only meaningful on 64-bit ARM targets
COMPATIBLE_MACHINE = "qemuarm64|rk3588"
