SUMMARY = "Piper: fast local neural TTS"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "2023.11.14"

SRC_URI = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
SRC_URI[sha256sum] = "fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb"

S = "${WORKDIR}/piper"

INSANE_SKIP:${PN} = "arch already-stripped file-rdeps dev-so"
FILES:${PN}-dev = ""
FILES:${PN}-staticdev = ""

COMPATIBLE_MACHINE = "qemuarm64|rk3588"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    # Install everything into /usr/lib/piper — binary, bundled libs, espeak-ng-data
    install -d ${D}/usr/lib/piper
    cp -a ${S}/. ${D}/usr/lib/piper/

    # Wrapper script: cd into the piper dir so the binary finds espeak-ng-data
    # relative to itself, and sets LD_LIBRARY_PATH for the bundled .so files.
    install -d ${D}${bindir}
    cat > ${D}${bindir}/piper <<'WRAPPER'
#!/bin/sh
PIPER_DIR=/usr/lib/piper
cd "$PIPER_DIR" || exit 1
exec env LD_LIBRARY_PATH="${PIPER_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
    ./piper "$@"
WRAPPER
    chmod 0755 ${D}${bindir}/piper

    # Placeholder dir for voice models (populated at runtime by ensoul-provision)
    install -d ${D}/opt/ensoul/models/tts
}

FILES:${PN} = " \
    /usr/lib/piper \
    ${bindir}/piper \
    /opt/ensoul/models/tts \
"
