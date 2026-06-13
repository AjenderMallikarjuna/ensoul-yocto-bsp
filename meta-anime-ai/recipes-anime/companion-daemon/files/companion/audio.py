import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("companion.audio")


def record(device: str, seconds: int, sample_rate: int) -> Path:
    """Capture audio via arecord and return path to a temporary WAV file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="anime-ai-in-")
    tmp.close()
    out = Path(tmp.name)

    cmd = [
        "arecord",
        "-D", device,
        "-f", "S16_LE",
        "-r", str(sample_rate),
        "-c", "1",
        "-d", str(seconds),
        str(out),
    ]
    log.info("Recording %ds of audio → %s", seconds, out)
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        log.error("arecord failed: %s", result.stderr.decode(errors="replace"))
        raise RuntimeError("Audio recording failed")
    return out


def play(wav_path: Path, device: str) -> None:
    """Play a WAV file via aplay; logs but does not raise on failure."""
    cmd = ["aplay", "-D", device, str(wav_path)]
    log.info("Playing audio ← %s", wav_path)
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        log.error("aplay failed: %s", result.stderr.decode(errors="replace"))
