SUMMARY = "PipeWire system-wide service for Ensoul"
DESCRIPTION = "Runs WirePlumber as a systemd system service alongside the \
built-in pipewire.service (socket-activated). The built-in pipewire.service \
already provides system-wide PipeWire on Scarthgap; adding a second instance \
causes a lock-file conflict."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit systemd

RDEPENDS:${PN} = "pipewire wireplumber"

SRC_URI = " \
    file://wireplumber-system.service \
    file://50-pipewire-env.sh \
"

S = "${WORKDIR}"

SYSTEMD_SERVICE:${PN} = "wireplumber-system.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/wireplumber-system.service ${D}${systemd_system_unitdir}/

    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${WORKDIR}/50-pipewire-env.sh ${D}${sysconfdir}/profile.d/

    install -d ${D}${sysconfdir}/environment.d
    echo 'PIPEWIRE_RUNTIME_DIR=/run/pipewire' \
         > ${D}${sysconfdir}/environment.d/10-pipewire.conf
}

FILES:${PN} = " \
    ${systemd_system_unitdir}/wireplumber-system.service \
    ${sysconfdir}/profile.d/50-pipewire-env.sh \
    ${sysconfdir}/environment.d/10-pipewire.conf \
"
