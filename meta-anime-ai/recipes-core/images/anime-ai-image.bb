SUMMARY = "Anime.Ai desk companion prototype image"
DESCRIPTION = "A minimal embedded Linux image for the Anime.Ai desk companion prototype."
LICENSE = "MIT"

inherit core-image

IMAGE_FEATURES += "ssh-server-openssh"

IMAGE_INSTALL:append = " \
    packagegroup-anime-ai \
    webrtc-audio-processing \
"

