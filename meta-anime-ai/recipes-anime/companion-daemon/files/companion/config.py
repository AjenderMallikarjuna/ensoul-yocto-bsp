import os
from dataclasses import dataclass, field
from pathlib import Path


def _parse_toml(text: str) -> dict:
    """Minimal TOML parser sufficient for our flat-section config files."""
    result: dict = {}
    section: dict = result
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            key = line[1:-1].strip()
            result[key] = {}
            section = result[key]
        elif "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            # Strip inline comments
            if "#" in v and not v.startswith('"'):
                v = v[: v.index("#")].strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.lower() == "true":
                v = True
            elif v.lower() == "false":
                v = False
            else:
                try:
                    v = int(v)
                except ValueError:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
            section[k] = v
    return result


@dataclass
class AudioConfig:
    input: str = "default"
    output: str = "default"
    record_seconds: int = 5
    sample_rate: int = 16000


@dataclass
class ActuatorConfig:
    enabled: bool = False
    driver: str = "mock"


@dataclass
class PersonalityConfig:
    name: str = "Aria"
    system_prompt: str = (
        "You are Aria, a friendly anime companion sitting on the user's desk. "
        "You are playful, warm, and supportive. Keep your responses short and "
        "conversational — 2 to 3 sentences at most. Never give medical, legal, "
        "or financial advice."
    )


@dataclass
class ApiConfig:
    stt_provider: str = "openai-whisper"
    llm_provider: str = "anthropic"
    tts_provider: str = "espeak"


@dataclass
class Config:
    device_name: str = "anime-ai-prototype"
    mode: str = "development"
    audio: AudioConfig = field(default_factory=AudioConfig)
    actuator: ActuatorConfig = field(default_factory=ActuatorConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""


def load(config_path: Path, secrets_path: Path) -> Config:
    cfg = Config()

    if config_path.exists():
        data = _parse_toml(config_path.read_text())

        device = data.get("device", {})
        cfg.device_name = device.get("name", cfg.device_name)
        cfg.mode = device.get("mode", cfg.mode)

        audio = data.get("audio", {})
        cfg.audio.input = audio.get("input", cfg.audio.input)
        cfg.audio.output = audio.get("output", cfg.audio.output)
        cfg.audio.record_seconds = audio.get("record_seconds", cfg.audio.record_seconds)
        cfg.audio.sample_rate = audio.get("sample_rate", cfg.audio.sample_rate)

        act = data.get("actuator", {})
        cfg.actuator.enabled = act.get("enabled", cfg.actuator.enabled)
        cfg.actuator.driver = act.get("driver", cfg.actuator.driver)

        pers = data.get("personality", {})
        cfg.personality.name = pers.get("name", cfg.personality.name)
        cfg.personality.system_prompt = pers.get("system_prompt", cfg.personality.system_prompt)

        api = data.get("api", {})
        cfg.api.stt_provider = api.get("stt_provider", cfg.api.stt_provider)
        cfg.api.llm_provider = api.get("llm_provider", cfg.api.llm_provider)
        cfg.api.tts_provider = api.get("tts_provider", cfg.api.tts_provider)

    if secrets_path.exists():
        secrets = _parse_toml(secrets_path.read_text())
        cfg.openai_api_key = secrets.get("openai", {}).get("api_key", cfg.openai_api_key)
        cfg.anthropic_api_key = secrets.get("anthropic", {}).get("api_key", cfg.anthropic_api_key)
        cfg.groq_api_key = secrets.get("groq", {}).get("api_key", cfg.groq_api_key)

    # Environment variables take highest priority so secrets can be injected at runtime
    cfg.openai_api_key = os.environ.get("OPENAI_API_KEY", cfg.openai_api_key)
    cfg.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", cfg.anthropic_api_key)
    cfg.groq_api_key = os.environ.get("GROQ_API_KEY", cfg.groq_api_key)

    return cfg
