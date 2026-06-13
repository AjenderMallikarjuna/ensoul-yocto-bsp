import json
import logging
import urllib.request
import urllib.error

from companion.emotion import parse_from_response

log = logging.getLogger("companion.chat")

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.1-8b-instant"

_MAX_TOKENS = 256
_HISTORY_KEEP = 10  # message pairs retained across turns


def _groq_chat(messages: list[dict], system_prompt: str, api_key: str) -> str:
    # Groq uses OpenAI-compatible format; inject system prompt as first message
    clean_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    full_messages = [{"role": "system", "content": system_prompt}] + clean_messages
    payload = json.dumps({
        "model": _GROQ_MODEL,
        "max_tokens": _MAX_TOKENS,
        "messages": full_messages,
    }).encode()

    req = urllib.request.Request(
        _GROQ_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "anime-ai-companion/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            log.info("LLM raw → %r", text)
            return text
    except urllib.error.HTTPError as e:
        log.error("Groq HTTP %d: %s", e.code, e.read().decode(errors="replace"))
    except Exception as e:
        log.error("Groq failed: %s", e)
    return "Sorry, I had a little trouble thinking just now — could you say that again? [EMO:concerned:0.6]"


def _anthropic_chat(messages: list[dict], system_prompt: str, api_key: str) -> str:
    # Strip internal emotion keys before sending to API
    clean_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

    payload = json.dumps({
        "model": _ANTHROPIC_MODEL,
        "max_tokens": _MAX_TOKENS,
        "system": system_prompt,
        "messages": clean_messages,
    }).encode()

    req = urllib.request.Request(
        _ANTHROPIC_URL,
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            text = result["content"][0]["text"].strip()
            log.info("LLM raw → %r", text)
            return text
    except urllib.error.HTTPError as e:
        log.error("LLM HTTP %d: %s", e.code, e.read().decode(errors="replace"))
    except Exception as e:
        log.error("LLM failed: %s", e)
    return "Sorry, I had a little trouble thinking just now — could you say that again? [EMO:concerned:0.6]"


class ChatSession:
    """Maintains per-device conversation history and dispatches to the configured LLM."""

    _HISTORY_KEEP = _HISTORY_KEEP

    def __init__(self, provider: str, system_prompt: str, api_key: str):
        self.provider = provider
        self.system_prompt = system_prompt
        self.api_key = api_key
        self._history: list[dict] = []
        self.current_emotion: tuple[str, float] = ("calm", 0.5)

    def send(self, user_text: str) -> tuple[str, str, float]:
        """
        Send user_text to the LLM.
        Returns (clean_reply, emotion_label, intensity).
        Emotion tag is stripped before storing in history and before returning.
        """
        if not self.api_key:
            log.warning("LLM API key not set — echoing input")
            return f"You said: {user_text}", "calm", 0.5

        self._history.append({"role": "user", "content": user_text})

        # Trim to window before sending (keeps context manageable)
        window = self._history[-(self._HISTORY_KEEP * 2):]

        if self.provider == "groq":
            raw_reply = _groq_chat(window, self.system_prompt, self.api_key)
        elif self.provider == "anthropic":
            raw_reply = _anthropic_chat(window, self.system_prompt, self.api_key)
        else:
            log.warning("Unknown LLM provider %r", self.provider)
            raw_reply = "I'm not sure how to respond right now. [EMO:calm:0.5]"

        clean_reply, label, intensity = parse_from_response(raw_reply)
        self.current_emotion = (label, intensity)

        # Store clean text + emotion metadata inline; extra keys are filtered
        # before the history is sent to the Anthropic API (see _anthropic_chat).
        self._history.append({
            "role": "assistant",
            "content": clean_reply,
            "_emo_label": label,
            "_emo_intensity": intensity,
        })

        return clean_reply, label, intensity
