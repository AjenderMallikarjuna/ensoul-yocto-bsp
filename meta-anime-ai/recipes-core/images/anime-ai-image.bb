SUMMARY = "Anime.Ai desk companion prototype image"
DESCRIPTION = "A minimal embedded Linux image for the Anime.Ai desk companion prototype."
LICENSE = "MIT"

inherit core-image

IMAGE_FEATURES += "ssh-server-openssh"

# Extra space for runtime-downloaded models: STT ~42MB + Piper voice ~61MB + headroom
IMAGE_ROOTFS_EXTRA_SPACE = "204800"

IMAGE_INSTALL:append = " \
    packagegroup-anime-ai \
    webrtc-audio-processing \
"

