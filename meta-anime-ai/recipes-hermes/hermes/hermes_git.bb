SUMMARY = "Hermes embedded audio framework for Ensoul AI"
DESCRIPTION = "Two-plane audio architecture: PipeWire DSP data-plane (hermes_abox) + \
POSIX-mq control-plane (Supervisor FSM, VoiceTrigger KWD, CloudConnector AI proxy). \
Provides 'Hey Aria' wake word, STT→LLM→TTS pipeline, and barge-in detection."
LICENSE = "CLOSED"

inherit externalsrc cmake systemd

# ── Source: local Hermes checkout (private repo) ──────────────────────────────
# On the build machine, clone Hermes and set this path, or override in local.conf:
#   EXTERNALSRC:pn-hermes = "/home/mallikarjuna/Hermes"
#   EXTERNALSRC_BUILD:pn-hermes = "/home/mallikarjuna/hermes-build"
EXTERNALSRC ?= "/home/${USER}/Hermes"
EXTERNALSRC_BUILD ?= "${WORKDIR}/hermes-build"

# ── Build dependencies ────────────────────────────────────────────────────────
DEPENDS = " \
    virtual/pkgconfig \
    libpipewire-0.3 \
    libcurl \
    sherpa-onnx \
"

# Hermes processes link against PipeWire + libcurl + sherpa-onnx-c-api at runtime
RDEPENDS:${PN} = " \
    pipewire \
    wireplumber \
    libcurl \
    sherpa-onnx \
"

# ── CMake configuration ───────────────────────────────────────────────────────
EXTRA_OECMAKE = " \
    -DHERMES_BUILD_TESTS=OFF \
    -DCMAKE_BUILD_TYPE=Release \
    -DCURL_INCLUDE_DIR=${STAGING_INCDIR} \
    -DCURL_LIBRARY=${STAGING_LIBDIR}/libcurl.so \
"

# ── Install binaries and service files ───────────────────────────────────────
do_install() {
    # Hermes process binaries
    install -d ${D}${bindir}
    for b in hermes_supervisor hermes_abox hermes_voice_trigger \
              hermes_cloud_connector hermes_codec_hw; do
        if [ -f ${B}/app/${b} ]; then
            install -m 0755 ${B}/app/${b} ${D}${bindir}/
        fi
    done

    # Systemd service files
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/hermes-supervisor.service     ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/hermes-abox.service           ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/hermes-voice-trigger.service  ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/hermes-cloud-connector.service ${D}${systemd_system_unitdir}/

    # KWS model directory (populated at runtime by ensoul-provision)
    install -d ${D}/opt/ensoul/models/kws
}

# ── Systemd integration ───────────────────────────────────────────────────────
SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = " \
    hermes-supervisor.service \
    hermes-abox.service \
    hermes-voice-trigger.service \
    hermes-cloud-connector.service \
"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

SRC_URI += " \
    file://hermes-supervisor.service \
    file://hermes-abox.service \
    file://hermes-voice-trigger.service \
    file://hermes-cloud-connector.service \
"

FILES:${PN} = " \
    ${bindir}/hermes_* \
    ${systemd_system_unitdir}/hermes-*.service \
    /opt/ensoul/models/kws \
"

INSANE_SKIP:${PN} = "already-stripped"
COMPATIBLE_MACHINE = "qemuarm64|rk3588"
