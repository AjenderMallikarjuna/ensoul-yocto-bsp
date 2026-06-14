SUMMARY = "Ensoul development and test tools"
DESCRIPTION = "Helper scripts for verifying the Ensoul audio stack inside QEMU."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://test-audio.sh"

# Pull the script from the top-level scripts/ directory
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

S = "${WORKDIR}"

do_install() {
    install -d ${D}/usr/share/ensoul
    install -m 0755 ${WORKDIR}/test-audio.sh ${D}/usr/share/ensoul/
}

FILES:${PN} = "/usr/share/ensoul/*"
