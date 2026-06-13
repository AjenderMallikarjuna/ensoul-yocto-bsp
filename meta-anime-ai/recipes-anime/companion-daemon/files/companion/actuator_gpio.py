"""
GPIO PWM servo driver for Raspberry Pi.

Uses the Linux sysfs PWM interface backed by the BCM2835 hardware PWM block.
Requires dtoverlay=pwm-2chan in /boot/firmware/config.txt (set via kas config).

  PWM channel 0 → GPIO 18 (physical pin 12)
  PWM channel 1 → GPIO 19 (physical pin 35)

Standard hobby servo timing at 50 Hz:
  Period   = 20 000 000 ns
  Center   =  1 500 000 ns  (neutral / straight ahead)
  Nod down =  1 800 000 ns  (~15° forward)
  Nod up   =  1 200 000 ns  (~15° back)
"""
import logging
import time
from pathlib import Path

log = logging.getLogger("companion.actuator_gpio")

_PWM_ROOT = Path("/sys/class/pwm/pwmchip0")
_PERIOD_NS    = 20_000_000
_CENTER_NS    =  1_500_000
_NOD_DOWN_NS  =  1_800_000
_NOD_UP_NS    =  1_200_000
_MOVE_DELAY   = 0.30        # seconds to wait after each position change


class GpioPwmActuator:
    """Controls a single servo via the sysfs PWM interface."""

    def __init__(self, channel: int = 0):
        self._chan_path = _PWM_ROOT / f"pwm{channel}"
        self._export(channel)
        self._write("period", str(_PERIOD_NS))
        self._write("enable", "1")
        self.idle()
        log.info("GPIO PWM actuator ready on channel %d", channel)

    # ------------------------------------------------------------------
    # Low-level sysfs helpers
    # ------------------------------------------------------------------

    def _export(self, channel: int) -> None:
        if not self._chan_path.exists():
            (_PWM_ROOT / "export").write_text(str(channel))
            time.sleep(0.15)  # let the kernel create the sysfs node

    def _write(self, attr: str, value: str) -> None:
        try:
            (self._chan_path / attr).write_text(value)
        except OSError as e:
            log.error("PWM sysfs write %s=%s failed: %s", attr, value, e)

    def _set_duty(self, duty_ns: int) -> None:
        self._write("duty_cycle", str(duty_ns))

    # ------------------------------------------------------------------
    # Public interface (matches MockActuator)
    # ------------------------------------------------------------------

    def nod(self, count: int = 2) -> None:
        for _ in range(count):
            self._set_duty(_NOD_DOWN_NS)
            time.sleep(_MOVE_DELAY)
            self._set_duty(_NOD_UP_NS)
            time.sleep(_MOVE_DELAY)
        self.idle()

    def idle(self) -> None:
        self._set_duty(_CENTER_NS)
