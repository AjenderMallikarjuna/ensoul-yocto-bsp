"""
companion/emotion.py — Emotion taxonomy and tag parsing for Aria's responses.

Tag format embedded in LLM output:  [EMO:label:intensity]
  Example: "I love that idea! [EMO:excited:0.85]"

The tag is stripped before displaying text or passing to TTS.
"""
import re
import logging

log = logging.getLogger("companion.emotion")

EMOTIONS = {"joy", "curiosity", "empathy", "playful", "calm", "concerned", "excited"}

# Servo behaviour hints consumed by the actuator layer.
# nod_count: baseline nods, speed: 0.0-1.0, pause: seconds between nods
SERVO_HINTS: dict[str, dict] = {
    "joy":       {"nod_count": 2, "speed": 0.8, "pause": 0.25},
    "curiosity": {"nod_count": 1, "speed": 0.5, "pause": 0.40},
    "empathy":   {"nod_count": 1, "speed": 0.4, "pause": 0.50},
    "playful":   {"nod_count": 3, "speed": 0.9, "pause": 0.20},
    "calm":      {"nod_count": 1, "speed": 0.3, "pause": 0.60},
    "concerned": {"nod_count": 1, "speed": 0.35, "pause": 0.45},
    "excited":   {"nod_count": 3, "speed": 1.0, "pause": 0.15},
}

_TAG_RE = re.compile(r'\[EMO:([a-zA-Z]+):([\d.]+)\]')


def parse_from_response(text: str) -> tuple[str, str, float]:
    """
    Extract [EMO:label:intensity] from a raw LLM reply.

    Returns (clean_text, emotion_label, intensity).
    Defaults to ("calm", 0.5) if no valid tag is found.
    """
    match = _TAG_RE.search(text)
    if not match:
        log.debug("No EMO tag in response — defaulting to calm/0.5")
        return text.strip(), "calm", 0.5

    label = match.group(1).lower()
    if label not in EMOTIONS:
        log.warning("Unknown emotion %r — using calm", label)
        label = "calm"

    try:
        intensity = max(0.0, min(1.0, float(match.group(2))))
    except ValueError:
        log.warning("Invalid intensity %r — using 0.5", match.group(2))
        intensity = 0.5

    clean = re.sub(r"  +", " ", _TAG_RE.sub("", text)).strip()
    log.info("Emotion: %s @ %.2f", label, intensity)
    return clean, label, intensity
