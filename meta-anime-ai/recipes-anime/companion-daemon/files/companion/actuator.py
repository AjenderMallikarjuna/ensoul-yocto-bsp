"""
Actuator abstraction layer.

The mock driver logs commands and tracks position in state.
A real servo driver should implement the same interface and be selected
via companion.toml [actuator] driver = "gpio-pwm" (or similar).
"""
import logging
import time
import threading
from typing import Protocol

log = logging.getLogger("companion.actuator")


class Actuator(Protocol):
    def nod(self, count: int = 2) -> None: ...
    def idle(self) -> None: ...


class MockActuator:
    """Logs motion commands; used in development mode and QEMU."""

    def nod(self, count: int = 2) -> None:
        for _ in range(count):
            log.info("ACTUATOR nod ↓")
            time.sleep(0.25)
            log.info("ACTUATOR nod ↑")
            time.sleep(0.25)

    def idle(self) -> None:
        log.info("ACTUATOR → idle position")


_PWM_SYSFS = "/sys/class/pwm/pwmchip0"


def _gpio_available() -> bool:
    from pathlib import Path
    return Path(_PWM_SYSFS).exists()


def create(driver: str, enabled: bool) -> Actuator:
    if not enabled:
        log.info("Actuator disabled — using mock (no physical movement)")
        return MockActuator()

    if driver == "auto":
        if _gpio_available():
            log.info("Actuator: auto-detected GPIO PWM at %s", _PWM_SYSFS)
            driver = "gpio-pwm"
        else:
            log.info("Actuator: GPIO PWM not found — falling back to mock")
            return MockActuator()

    if driver == "mock":
        log.info("Actuator: mock driver")
        return MockActuator()

    if driver == "gpio-pwm":
        from companion.actuator_gpio import GpioPwmActuator
        return GpioPwmActuator(channel=0)

    raise ValueError(f"Unknown actuator driver: {driver!r}")


def nod_for_emotion(actuator: Actuator, label: str, intensity: float) -> None:
    """Perform an emotion-appropriate nod. Designed to run in a daemon thread."""
    from companion.emotion import SERVO_HINTS
    hints = SERVO_HINTS.get(label, SERVO_HINTS["calm"])
    count = max(1, round(hints["nod_count"] * intensity))
    log.info("EMOTION MOTION: %s @ %.2f → %d nod(s)", label, intensity, count)
    actuator.nod(count)
    actuator.idle()


def nod_while_speaking(actuator: Actuator, duration: float) -> None:
    """Run in a background thread: nod periodically for ~duration seconds."""
    end = time.monotonic() + duration
    while time.monotonic() < end:
        actuator.nod(1)
        time.sleep(0.9)
    actuator.idle()
