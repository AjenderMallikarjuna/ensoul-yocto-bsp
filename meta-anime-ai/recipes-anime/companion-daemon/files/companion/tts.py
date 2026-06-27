import json
import logging
import os
import re
import select
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("companion.tts")

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

_PIPER_VOICE = "en_US-hfc_female-medium"
_PIPER_MODEL_DIRS = [
    "/opt/ensoul/models/tts",
    "/tmp/tts",
]

# ── Persistent Piper process state ────────────────────────────────────────────
_piper_lock = threading.Lock()
_piper_proc: subprocess.Popen | None = None
_piper_model_used: str | None = None
_PIPER_SAMPLE_RATE = 22050  # default; overridden from voice config JSON


def _find_piper_model() -> str | None:
    for d in _PIPER_MODEL_DIRS:
        model = os.path.join(d, f"{_PIPER_VOICE}.onnx")
        config = os.path.join(d, f"{_PIPER_VOICE}.onnx.json")
        if os.path.isfile(model) and os.path.isfile(config):
            return model
    return None


def _read_sample_rate(model_path: str) -> int:
    config = model_path + ".json"
    try:
        with open(config) as f:
            return int(json.load(f)["audio"]["sample_rate"])
    except Exception:
        return 22050


def _start_piper(model: str) -> subprocess.Popen:
    global _PIPER_SAMPLE_RATE
    _PIPER_SAMPLE_RATE = _read_sample_rate(model)
    log.info("Starting persistent Piper (model=%s, rate=%d Hz)", model, _PIPER_SAMPLE_RATE)
    proc = subprocess.Popen(
        ["piper", "--model", model, "--output-raw", "--sentence_silence", "0.2"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait until Piper logs "Initialized piper" before accepting requests
    deadline = time.monotonic() + 60
    buf = b""
    while time.monotonic() < deadline:
        r, _, _ = select.select([proc.stderr], [], [], 1.0)
        if r:
            buf += os.read(proc.stderr.fileno(), 4096)
            if b"Initialized piper" in buf:
                log.info("Piper ready (model loaded)")
                return proc
        if proc.poll() is not None:
            raise RuntimeError(f"Piper exited during startup: {buf.decode(errors='replace')}")
    raise RuntimeError("Piper startup timed out")


def _ensure_piper(model: str) -> subprocess.Popen:
    global _piper_proc, _piper_model_used
    if (_piper_proc is not None
            and _piper_proc.poll() is None
            and _piper_model_used == model):
        return _piper_proc
    if _piper_proc is not None and _piper_proc.poll() is None:
        _piper_proc.kill()
    _piper_proc = _start_piper(model)
    _piper_model_used = model
    return _piper_proc


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    n = len(pcm)
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + n, b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", n,
    ) + pcm


def _synth_raw(proc: subprocess.Popen, text: str, timeout: float = 120.0) -> bytes:
    """
    Send one line of text to a persistent Piper --output-raw process.
    Returns raw PCM bytes.

    Uses select() on both stdout and stderr simultaneously to prevent
    pipe-buffer deadlock. Piper flushes all PCM to stdout, then logs
    the RTF line (with audio duration) to stderr. Once we parse that
    line we know exactly how many bytes to expect.
    """
    proc.stdin.write((text.strip() + "\n").encode())
    proc.stdin.flush()

    pcm = bytearray()
    stderr_buf = b""
    audio_samples: int | None = None
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if audio_samples is not None and len(pcm) >= audio_samples * 2:
            break

        r, _, _ = select.select([proc.stdout, proc.stderr], [], [], 0.05)
        for fd in r:
            if fd is proc.stdout:
                chunk = os.read(proc.stdout.fileno(), 65536)
                if chunk:
                    pcm.extend(chunk)
            elif fd is proc.stderr:
                chunk = os.read(proc.stderr.fileno(), 4096)
                if chunk:
                    stderr_buf += chunk
                    while b"\n" in stderr_buf:
                        line, stderr_buf = stderr_buf.split(b"\n", 1)
                        m = re.search(rb"audio=([\d.]+)\s*sec", line)
                        if m:
                            audio_sec = float(m.group(1))
                            audio_samples = round(audio_sec * _PIPER_SAMPLE_RATE)
                            log.debug("Piper done: %.3fs audio → %d samples", audio_sec, audio_samples)

    # Drain any remaining bytes after the RTF line arrives
    drain_deadline = time.monotonic() + 2.0
    while audio_samples is not None and len(pcm) < audio_samples * 2 and time.monotonic() < drain_deadline:
        r, _, _ = select.select([proc.stdout], [], [], 0.1)
        if r:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if chunk:
                pcm.extend(chunk)

    if audio_samples is None:
        raise RuntimeError("Piper did not complete synthesis within timeout")

    return bytes(pcm[: audio_samples * 2])


def _piper(text: str) -> Path:
    global _piper_proc, _piper_model_used

    model = _find_piper_model()
    if not model:
        log.warning("Piper model not found — falling back to espeak")
        return _espeak(text)

    with _piper_lock:
        try:
            proc = _ensure_piper(model)
            pcm = _synth_raw(proc, text)
            wav = _pcm_to_wav(pcm, _PIPER_SAMPLE_RATE)
        except Exception as e:
            log.error("Piper synthesis failed: %s — restarting process, falling back to espeak", e)
            if _piper_proc and _piper_proc.poll() is None:
                _piper_proc.kill()
            _piper_proc = None
            _piper_model_used = None
            return _espeak(text)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.write(wav)
    tmp.close()
    out = Path(tmp.name)
    log.info("Piper TTS (persistent) → %s (%d bytes)", out, out.stat().st_size)
    return out


def _espeak(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.close()
    out = Path(tmp.name)
    subprocess.run(
        ["espeak", "-w", str(out), "-s", "155", "-p", "55", text],
        capture_output=True,
    )
    return out


def _openai_tts(text: str, api_key: str) -> Path:
    payload = json.dumps({
        "model": "tts-1",
        "input": text,
        "voice": "nova",
        "response_format": "wav",
    }).encode()
    req = urllib.request.Request(
        _OPENAI_TTS_URL,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        method="POST",
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.close()
    out = Path(tmp.name)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out.write_bytes(resp.read())
        log.info("OpenAI TTS → %s", out)
        return out
    except urllib.error.HTTPError as e:
        log.error("TTS HTTP %d: %s — falling back to piper", e.code, e.read().decode(errors="replace"))
    except Exception as e:
        log.error("TTS failed: %s — falling back to piper", e)
    return _piper(text)


def synthesize(text: str, provider: str, openai_api_key: str = "") -> Path:
    """Return path to a temporary WAV file containing synthesised speech."""
    if provider == "openai" and openai_api_key:
        return _openai_tts(text, openai_api_key)
    if provider == "piper":
        return _piper(text)
    return _espeak(text)
