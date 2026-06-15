SUMMARY = "PipeWire system-wide service for Ensoul"
DESCRIPTION = "Runs PipeWire and WirePlumber as systemd system services so audio \
is available at boot without requiring a logged-in user session."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit systemd

RDEPENDS:${PN} = "pipewire wireplumber"

SRC_URI = " \
    file://pipewire-system.service \
    file://wireplumber-system.service \
    file://50-pipewire-env.sh \
"

S = "${WORKDIR}"

SYSTEMD_SERVICE:${PN} = "pipewire-system.service wireplumber-system.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
    # Systemd system service units
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/pipewire-system.service   ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/wireplumber-system.service ${D}${systemd_system_unitdir}/

    # Profile.d so all shells know where to find the PipeWire socket
    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${WORKDIR}/50-pipewire-env.sh ${D}${sysconfdir}/profile.d/

    # systemd environment drop-in so daemons started by systemd also inherit it
    install -d ${D}${sysconfdir}/environment.d
    echo 'PIPEWIRE_RUNTIME_DIR=/run/pipewire' \
         > ${D}${sysconfdir}/environment.d/10-pipewire.conf
}

FILES:${PN} = " \
    ${systemd_system_unitdir}/pipewire-system.service \
    ${systemd_system_unitdir}/wireplumber-system.service \
    ${sysconfdir}/profile.d/50-pipewire-env.sh \
    ${sysconfdir}/environment.d/10-pipewire.conf \
"
