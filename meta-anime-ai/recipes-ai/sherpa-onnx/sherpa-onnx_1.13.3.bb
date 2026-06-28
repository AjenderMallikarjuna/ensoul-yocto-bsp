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

# Pre-built aarch64 binaries fetched on an x86_64 build host.
# arch           — target aarch64 built on x86_64 host, intentional
# already-stripped — upstream ships stripped release binaries
# file-rdeps     — libonnxruntime is bundled in this same package (self-satisfied dep);
#                  libasound is declared via RDEPENDS below
INSANE_SKIP:${PN} = "arch already-stripped file-rdeps"

# Yocto default FILES:${PN}-dev claims any unversioned *.so as a linker stub.
# Our libs are real runtime SOs (no libfoo.so.1 symlink chain) — keep them in ${PN}.
FILES:${PN}-dev = ""
FILES:${PN}-staticdev = ""

# ALSA binaries (sherpa-onnx-alsa, etc.) link against libasound.so.2
RDEPENDS:${PN} = "alsa-lib"

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

    # C/C++ API headers — required by hermes_voice_trigger for KWD at build time
    if [ -d ${S}/include ]; then
        install -d ${D}${includedir}
        cp -r ${S}/include/. ${D}${includedir}/
    fi

    # Directories for models (populated at runtime by ensoul-provision)
    install -d ${D}/opt/ensoul/models/stt
    install -d ${D}/opt/ensoul/models/kws
}

FILES:${PN} = " \
    ${libdir}/libonnxruntime.so \
    ${libdir}/libsherpa-onnx-c-api.so \
    ${libdir}/libsherpa-onnx-cxx-api.so \
    ${bindir}/sherpa-onnx* \
    ${bindir}/sense-voice-simulate-streaming-alsa-cxx-api \
    ${bindir}/zipformer-ctc-simulate-streaming-alsa-cxx-api \
    /opt/ensoul/models/stt \
    /opt/ensoul/models/kws \
"

FILES:${PN}-dev = " \
    ${includedir}/sherpa-onnx \
"

# Only meaningful on 64-bit ARM targets
COMPATIBLE_MACHINE = "qemuarm64|rk3588"
