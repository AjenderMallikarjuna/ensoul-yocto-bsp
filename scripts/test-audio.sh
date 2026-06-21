#!/bin/sh
# Run this INSIDE the QEMU image to verify the audio stack.
# Usage: test-audio.sh [--tone] [--record]

set -e

PASS=0
FAIL=0

ok()   { echo "[PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }
info() { echo "       $1"; }

echo "=== Ensoul Audio Stack — Phase 0 Verification ==="
echo ""

# ── 1. Kernel audio modules ────────────────────────────────────────────────
echo "── Kernel modules ──"
if lsmod | grep -q snd_hda_intel; then
    ok "snd_hda_intel loaded"
else
    # Try to load it (not fatal — may be built-in)
    modprobe snd_hda_intel 2>/dev/null && ok "snd_hda_intel loaded (modprobe)" \
        || fail "snd_hda_intel not loaded (check audio.cfg kernel fragment)"
fi

# ── 2. ALSA devices ────────────────────────────────────────────────────────
echo ""
echo "── ALSA devices ──"
if aplay -l 2>&1 | grep -q "card"; then
    ok "ALSA playback device found"
    info "$(aplay -l 2>&1 | grep 'card')"
else
    fail "No ALSA playback card — QEMU needs -device intel-hda flag"
fi

if arecord -l 2>&1 | grep -q "card"; then
    ok "ALSA capture device found"
    info "$(arecord -l 2>&1 | grep 'card')"
else
    fail "No ALSA capture card"
fi

# ── 3. PipeWire ────────────────────────────────────────────────────────────
echo ""
echo "── PipeWire ──"
if [ -S /run/pipewire/pipewire-0 ]; then
    ok "PipeWire socket exists at /run/pipewire/pipewire-0"
else
    fail "PipeWire socket not found — is pipewire-system.service running?"
    info "  systemctl status pipewire-system.service"
fi

if PIPEWIRE_RUNTIME_DIR=/run/pipewire pw-cli info 0 >/dev/null 2>&1; then
    ok "pw-cli connected to PipeWire"
else
    fail "pw-cli cannot connect to PipeWire"
fi

# ── 4. WirePlumber / ALSA nodes ────────────────────────────────────────────
echo ""
echo "── WirePlumber / Audio nodes ──"
# pw-dump is reliable over non-interactive connections; pw-cli list-objects
# is non-deterministic and sometimes returns empty output in subshells.
PW_DUMP=$(PIPEWIRE_RUNTIME_DIR=/run/pipewire pw-dump 2>/dev/null || true)

if echo "$PW_DUMP" | grep -q '"Audio/Sink"'; then
    ok "Audio nodes visible in PipeWire graph"
    SINKS=$(echo "$PW_DUMP" | grep -c '"Audio/Sink"' || true)
    SOURCES=$(echo "$PW_DUMP" | grep -c '"Audio/Source"' || true)
    info "$SINKS sink(s), $SOURCES source(s) registered"
else
    fail "No audio nodes in PipeWire — WirePlumber may not have discovered ALSA yet"
    info "  systemctl status wireplumber-system.service"
fi

# ── 5. Optional: tone test ─────────────────────────────────────────────────
if [ "$1" = "--tone" ]; then
    echo ""
    echo "── Tone test (2 s, 440 Hz) ──"
    if PIPEWIRE_RUNTIME_DIR=/run/pipewire speaker-test -t sine -f 440 -l 1 -D pipewire >/dev/null 2>&1; then
        ok "Tone played via PipeWire"
    elif speaker-test -t sine -f 440 -l 1 >/dev/null 2>&1; then
        ok "Tone played via ALSA directly"
    else
        fail "Tone test failed"
    fi
fi

# ── 6. Optional: mic record test ───────────────────────────────────────────
if [ "$1" = "--record" ]; then
    echo ""
    echo "── Capture test (2 s to /tmp/test-capture.wav) ──"
    if arecord -d 2 -f cd /tmp/test-capture.wav >/dev/null 2>&1; then
        SIZE=$(wc -c < /tmp/test-capture.wav)
        if [ "$SIZE" -gt 1000 ]; then
            ok "Captured $SIZE bytes to /tmp/test-capture.wav"
        else
            fail "Capture file too small ($SIZE bytes) — microphone may not be active"
        fi
    else
        fail "arecord failed"
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && echo "    Phase 0 COMPLETE — audio stack verified." \
                  || echo "    Fix failures above before proceeding to Phase 1."
