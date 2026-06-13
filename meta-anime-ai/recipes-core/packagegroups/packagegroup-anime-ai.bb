SUMMARY = "Anime.AI product package group"
DESCRIPTION = "Packages required by the Anime.AI desk companion prototype."
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    companion-daemon \
    networkmanager \
    python3-core \
    python3-json \
    python3-logging \
    alsa-utils \
    espeak \
    openssh-sftp-server \
"
