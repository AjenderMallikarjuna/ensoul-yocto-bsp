#!/usr/bin/env python3
"""
Anime.AI Companion Daemon

Pipeline per conversation turn:
  mic capture → Whisper STT → Claude LLM → TTS → speaker + servo nod
Web chat available at http://<device-ip>:8080/
"""
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/usr/lib/anime-ai")

from companion import actuator as act_module
from companion import api_server, audio, chat, config as cfg_module, stt, tts

CONFIG_PATH = Path("/etc/anime-ai/companion.toml")
SECRETS_PATH = Path("/etc/anime-ai/secrets.toml")
STATE_PATH = Path("/run/anime-ai-companion.json")

log = logging.getLogger("companion")


class CompanionDaemon:
    def __init__(self):
        self.state = "starting"
        self.started_at = time.time()
        self._lock = threading.Lock()

        self.cfg = cfg_module.load(CONFIG_PATH, SECRETS_PATH)
        self.actuator = act_module.create(self.cfg.actuator.driver, self.cfg.actuator.enabled)
        llm_key = {
            "groq": self.cfg.groq_api_key,
            "anthropic": self.cfg.anthropic_api_key,
        }.get(self.cfg.api.llm_provider, "")
        self.session = chat.ChatSession(
            provider=self.cfg.api.llm_provider,
            system_prompt=self.cfg.personality.system_prompt,
            api_key=llm_key,
        )

        log.info(
            "Device=%r  Mode=%r  STT=%r  LLM=%r  TTS=%r",
            self.cfg.device_name,
            self.cfg.mode,
            self.cfg.api.stt_provider,
            self.cfg.api.llm_provider,
            self.cfg.api.tts_provider,
        )

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _set_state(self, s: str) -> None:
        with self._lock:
            self.state = s
        self._write_health()

    def health(self) -> dict:
        emotion_label, emotion_intensity = self.session.current_emotion
        return {
            "service": "anime-ai-companion",
            "status": "running",
            "state": self.state,
            "uptime_seconds": round(time.time() - self.started_at, 2),
            "device": self.cfg.device_name,
            "mode": self.cfg.mode,
            "personality": self.cfg.personality.name,
            "emotion": {"label": emotion_label, "intensity": emotion_intensity},
        }

    def _write_health(self) -> None:
        try:
            STATE_PATH.write_text(json.dumps(self.health(), indent=2))
        except OSError as e:
            log.warning("Cannot write health file: %s", e)

    # ------------------------------------------------------------------
    # Emotion callback (called by api_server on each /chat response)
    # ------------------------------------------------------------------

    def on_emotion_change(self, label: str, intensity: float) -> None:
        log.info("Emotion → %s @ %.2f", label, intensity)
        if self.state == "idle":
            act_module.nod_for_emotion(self.actuator, label, intensity)

    # ------------------------------------------------------------------
    # Voice pipeline
    # ------------------------------------------------------------------

    def handle_conversation(self) -> None:
        """Full pipeline: record → STT → LLM → TTS → play + nod."""
        try:
            self._set_state("recording")
            wav_in = audio.record(
                self.cfg.audio.input,
                self.cfg.audio.record_seconds,
                self.cfg.audio.sample_rate,
            )

            self._set_state("processing")
            transcript = stt.transcribe(wav_in, self.cfg.api.stt_provider, self.cfg.openai_api_key)
            wav_in.unlink(missing_ok=True)

            if not transcript:
                log.warning("Empty transcript — skipping response")
                return

            self._speak_reply(transcript)

        except Exception:
            log.exception("Conversation pipeline error")
        finally:
            self._set_state("idle")

    def handle_text_input(self, text: str) -> None:
        """Development shortcut: skip audio capture, feed text directly."""
        try:
            self._set_state("processing")
            self._speak_reply(text)
        except Exception:
            log.exception("Text input pipeline error")
        finally:
            self._set_state("idle")

    def _speak_reply(self, user_text: str) -> None:
        """Shared tail: LLM → TTS → play + nod."""
        log.info("User: %s", user_text)
        reply, label, intensity = self.session.send(user_text)
        log.info("Aria [%s @ %.2f]: %s", label, intensity, reply)

        self._set_state("speaking")
        wav_out = tts.synthesize(reply, self.cfg.api.tts_provider, self.cfg.openai_api_key)

        speak_seconds = max(len(reply.split()) / 2.5, 2.0)
        nod_thread = threading.Thread(
            target=act_module.nod_while_speaking,
            args=(self.actuator, speak_seconds),
            daemon=True,
            name="actuator-nod",
        )
        nod_thread.start()

        audio.play(wav_out, self.cfg.audio.output)
        wav_out.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop(self, *_args) -> None:
        log.info("Stopping Anime.AI companion daemon")
        self._running = False

    def run(self) -> None:
        self._running = True
        log.info("Anime.AI companion daemon starting")

        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

        api_server.start(self)
        self._set_state("idle")

        while self._running:
            self._write_health()
            time.sleep(10)

        log.info("Anime.AI companion daemon stopped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    CompanionDaemon().run()


if __name__ == "__main__":
    main()
