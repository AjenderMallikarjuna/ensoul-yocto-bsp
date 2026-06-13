import json
import logging
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger("companion.stt")

_WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
_BOUNDARY = "AnimeAIBoundary7f3a9b"


def _multipart_body(wav_path: Path) -> bytes:
    audio_bytes = wav_path.read_bytes()
    parts = (
        f"--{_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "whisper-1\r\n"
        f"--{_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + audio_bytes + f"\r\n--{_BOUNDARY}--\r\n".encode()
    return parts


def transcribe_whisper(wav_path: Path, api_key: str) -> str:
    if not api_key:
        log.warning("OPENAI_API_KEY not set — skipping STT")
        return ""

    body = _multipart_body(wav_path)
    req = urllib.request.Request(
        _WHISPER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            text = result.get("text", "").strip()
            log.info("STT → %r", text)
            return text
    except urllib.error.HTTPError as e:
        log.error("STT HTTP %d: %s", e.code, e.read().decode(errors="replace"))
    except Exception as e:
        log.error("STT failed: %s", e)
    return ""


def transcribe(wav_path: Path, provider: str, api_key: str) -> str:
    if provider == "openai-whisper":
        return transcribe_whisper(wav_path, api_key)
    log.warning("Unknown STT provider %r — returning empty", provider)
    return ""
