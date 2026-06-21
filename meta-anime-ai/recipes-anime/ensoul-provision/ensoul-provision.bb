SUMMARY = "Ensoul AI first-boot provisioning"
DESCRIPTION = "Installs API keys and downloads the STT model on first boot via systemd oneshot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# Set in build/conf/local.conf — never commit the real value to git.
# Example:  ENSOUL_GROQ_KEY = "gsk_..."
ENSOUL_GROQ_KEY ?= ""

SRC_URI = " \
    file://provision.sh \
    file://ensoul-provision.service \
"

S = "${WORKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "ensoul-provision.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
    # Write secrets.env from the build-time variable — key never touches git
    install -d ${D}${sysconfdir}/anime-ai
    echo "GROQ_API_KEY=${ENSOUL_GROQ_KEY}" > ${WORKDIR}/secrets.env
    install -m 0600 ${WORKDIR}/secrets.env ${D}${sysconfdir}/anime-ai/secrets.env

    # Provision script (downloads STT model on first boot)
    install -d ${D}${datadir}/ensoul
    install -m 0755 ${WORKDIR}/provision.sh ${D}${datadir}/ensoul/provision.sh

    # Systemd unit
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/ensoul-provision.service \
        ${D}${systemd_system_unitdir}/ensoul-provision.service
}

FILES:${PN} = " \
    ${sysconfdir}/anime-ai/secrets.env \
    ${datadir}/ensoul/provision.sh \
    ${systemd_system_unitdir}/ensoul-provision.service \
"
