import logging
import subprocess
import tempfile
import urllib.request
import urllib.error
import json
from pathlib import Path

log = logging.getLogger("companion.tts")

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


def _espeak(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-tts-")
    tmp.close()
    out = Path(tmp.name)
    cmd = ["espeak", "-w", str(out), "-s", "155", "-p", "55", text]
    result = subprocess.run(cmd, capture_output=True)
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
        log.error("TTS HTTP %d: %s — falling back to espeak", e.code, e.read().decode(errors="replace"))
    except Exception as e:
        log.error("TTS failed: %s — falling back to espeak", e)

    return _espeak(text)


def synthesize(text: str, provider: str, openai_api_key: str) -> Path:
    """Return path to a temporary WAV file containing the synthesised speech."""
    if provider == "openai" and openai_api_key:
        return _openai_tts(text, openai_api_key)
    return _espeak(text)
