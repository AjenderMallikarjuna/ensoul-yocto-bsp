FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Audio config fragment — enables Intel HDA for QEMU and prepares for
# future virtio-snd support on real hardware.
SRC_URI:append = " file://audio.cfg"
