import logging
import os
import subprocess
import tempfile
import urllib.request
import urllib.error
import json
from pathlib import Path

log = logging.getLogger("companion.tts")

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

_PIPER_VOICE = "en_US-hfc_female-medium"
_PIPER_MODEL_DIRS = [
    "/opt/ensoul/models/tts",
    "/tmp/tts",
]


def _find_piper_model() -> str | None:
    for d in _PIPER_MODEL_DIRS:
        model = os.path.join(d, f"{_PIPER_VOICE}.onnx")
        config = os.path.join(d, f"{_PIPER_VOICE}.onnx.json")
        if os.path.isfile(model) and os.path.isfile(config):
            return model
    return None


def _piper(text: str) -> Path:
    model = _find_piper_model()
    if not model:
        log.warning("Piper model not found at %s — falling back to espeak", _PIPER_MODEL_DIRS)
        return _espeak(text)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.close()
    out = Path(tmp.name)

    result = subprocess.run(
        [
            "piper",
            "--model", model,
            "--output_file", str(out),
            "--sentence_silence", "0.2",
            "--length_scale", "1.0",
        ],
        input=text.encode(),
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        log.error("Piper failed (rc=%d): %s", result.returncode,
                  result.stderr.decode(errors="replace"))
        out.unlink(missing_ok=True)
        return _espeak(text)

    log.info("Piper TTS → %s (%d bytes)", out, out.stat().st_size)
    return out


def _espeak(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.close()
    out = Path(tmp.name)
    result = subprocess.run(
        ["espeak", "-w", str(out), "-s", "155", "-p", "55", text],
        capture_output=True,
    )
    if result.returncode != 0:
        log.error("espeak failed: %s", result.stderr.decode(errors="replace"))
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
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        method="POST",
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.close()
    out = Path(tmp.name)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out.write_bytes(resp.read())
        log.info("OpenAI TTS audio → %s", out)
        return out
    except urllib.error.HTTPError as e:
        log.error("TTS HTTP %d: %s — falling back to piper", e.code,
                  e.read().decode(errors="replace"))
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
