SUMMARY = "Anime.AI companion device daemon"
DESCRIPTION = "Device-side control loop: audio capture, STT, LLM chat, TTS playback, actuator control, and HTTP API."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://anime-ai-companion.py \
    file://anime-ai-companion.service \
    file://companion.toml \
    file://companion/__init__.py \
    file://companion/actuator.py \
    file://companion/actuator_gpio.py \
    file://companion/api_server.py \
    file://companion/audio.py \
    file://companion/chat.py \
    file://companion/config.py \
    file://companion/emotion.py \
    file://companion/stt.py \
    file://companion/tts.py \
"

S = "${WORKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "anime-ai-companion.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

COMPANION_LIB = "/usr/lib/anime-ai"

do_install() {
    # Main entry point
    install -d ${D}${bindir}
    install -m 0755 ${WORKDIR}/anime-ai-companion.py ${D}${bindir}/anime-ai-companion

    # Python package
    install -d ${D}${COMPANION_LIB}/companion
    for f in __init__.py actuator.py actuator_gpio.py api_server.py audio.py chat.py config.py emotion.py stt.py tts.py; do
        install -m 0644 ${WORKDIR}/companion/$f ${D}${COMPANION_LIB}/companion/$f
    done

    # Config
    install -d ${D}${sysconfdir}/anime-ai
    install -m 0640 ${WORKDIR}/companion.toml ${D}${sysconfdir}/anime-ai/companion.toml

    # Systemd unit
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/anime-ai-companion.service ${D}${systemd_system_unitdir}/anime-ai-companion.service
}

FILES:${PN} += " \
    ${COMPANION_LIB}/ \
    ${systemd_system_unitdir}/anime-ai-companion.service \
    ${sysconfdir}/anime-ai/ \
"

RDEPENDS:${PN} = " \
    python3-core \
    python3-logging \
    python3-json \
    alsa-utils \
    espeak \
"
