"""Local GPIO controls; importing this module never imports or opens GPIO."""
from dataclasses import dataclass
import logging
import math
import platform
from threading import Event, Thread
import time

from .state import AssistantState as S

logger = logging.getLogger("nova.hardware")


def validate_gpio_dependencies():
    """Import/API checks only: never opens a GPIO chip or acquires any pins."""
    from importlib.metadata import version
    from gpiozero import DigitalInputDevice, DigitalOutputDevice
    from gpiozero.pins.lgpio import LGPIOFactory
    import lgpio
    major = int(version("gpiozero").split(".")[0])
    return (major == 2 and callable(LGPIOFactory) and callable(DigitalInputDevice)
            and callable(DigitalOutputDevice)
            and all(callable(getattr(lgpio, name, None)) for name in
                    ("gpiochip_open", "gpio_read", "gpio_claim_input", "gpio_claim_output")))


class HardwareConfigurationError(ValueError):
    pass


def boolean(env, name, default):
    value = env.get(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise HardwareConfigurationError("Invalid hardware boolean setting.")
    return value == "true"


@dataclass(frozen=True)
class HardwareConfig:
    backend: str = "none"
    red: int = 17
    green: int = 27
    blue: int = 22
    switch: int = 23
    active_high: bool = True
    muted_high: bool = True
    chip: int = 0
    debounce: float = .1
    poll_interval: float = .02

    def __post_init__(self):
        if self.backend not in {"none", "mock", "lgpio"}:
            raise HardwareConfigurationError("Unsupported GPIO backend.")
        if type(self.active_high) is not bool or type(self.muted_high) is not bool:
            raise HardwareConfigurationError("GPIO polarity settings must be boolean.")
        pins = (self.red, self.green, self.blue, self.switch)
        if len(set(pins)) != 4 or any(type(pin) is not int or not 2 <= pin <= 27 for pin in pins):
            raise HardwareConfigurationError("GPIO pins must be distinct BCM pins from 2 to 27.")
        if type(self.chip) is not int or not 0 <= self.chip <= 63:
            raise HardwareConfigurationError("Invalid GPIO chip index.")
        if not math.isfinite(self.debounce) or not .05 <= self.debounce <= 1:
            raise HardwareConfigurationError("GPIO debounce must be 0.05 to 1 second.")
        if not math.isfinite(self.poll_interval) or not .005 <= self.poll_interval <= .1:
            raise HardwareConfigurationError("GPIO poll interval must be 0.005 to 0.1 second.")

    @classmethod
    def from_env(cls, env):
        try:
            return cls(backend=env.get("NOVA_GPIO_BACKEND", "none"),
                       red=int(env.get("NOVA_LED_RED_BCM", "17")),
                       green=int(env.get("NOVA_LED_GREEN_BCM", "27")),
                       blue=int(env.get("NOVA_LED_BLUE_BCM", "22")),
                       switch=int(env.get("NOVA_MUTE_SWITCH_BCM", "23")),
                       active_high=boolean(env, "NOVA_LED_ACTIVE_HIGH", True),
                       muted_high=boolean(env, "NOVA_SWITCH_MUTED_HIGH", True),
                       chip=int(env.get("NOVA_GPIO_CHIP", "0")),
                       debounce=float(env.get("NOVA_SWITCH_DEBOUNCE_SECONDS", ".1")),
                       poll_interval=float(env.get("NOVA_GPIO_POLL_SECONDS", ".02")))
        except (ValueError, TypeError, OverflowError):
            raise HardwareConfigurationError("Invalid GPIO configuration; check documented settings.") from None


class NoopBackend:
    """Unavailable hardware fallback. Never grants permission to listen."""
    available = False
    def read_muted(self):
        return True
    def set_rgb(self, red, green, blue):
        pass
    def close(self):
        pass


class MockBackend:
    """Pure Python backend for Windows tests, with no GPIO dependencies."""
    available = True
    def __init__(self, muted=True):
        self.muted = muted
        self.rgb = (False, False, False)
        self.closed = False
        self.error = False
    def read_muted(self):
        if self.closed or self.error:
            raise OSError("GPIO unavailable")
        return self.muted
    def set_rgb(self, red, green, blue):
        if self.closed or self.error:
            raise OSError("GPIO unavailable")
        self.rgb = (bool(red), bool(green), bool(blue))
    def close(self):
        self.rgb = (False, False, False)
        self.closed = True


class LGPIOBackend:
    available = True
    def __init__(self, config):
        if platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"}:
            raise HardwareConfigurationError("Real GPIO requires Linux ARM64.")
        if not validate_gpio_dependencies():
            raise HardwareConfigurationError("Unsupported GPIO dependency APIs.")
        # An explicit local factory avoids environment-driven remote/mock fallback.
        from gpiozero import DigitalInputDevice, DigitalOutputDevice
        from gpiozero.pins.lgpio import LGPIOFactory
        self.devices, self.factory = [], None
        try:
            self.factory = LGPIOFactory(chip=config.chip)
            self.input = DigitalInputDevice(config.switch, pull_up=config.muted_high,
                                            bounce_time=None, pin_factory=self.factory)
            self.devices.append(self.input)
            self.outputs = []
            for pin in (config.red, config.green, config.blue):
                output = DigitalOutputDevice(pin, active_high=config.active_high,
                                             initial_value=False, pin_factory=self.factory)
                self.devices.append(output)
                self.outputs.append(output)
            self.muted_high = config.muted_high
        except BaseException:
            self.close()
            raise
    def read_muted(self):
        # value/is_active invert pull-ups; raw pin state preserves wiring polarity.
        return bool(self.input.pin.state) == self.muted_high
    def set_rgb(self, red, green, blue):
        for output, enabled in zip(self.outputs, (red, green, blue)):
            output.value = bool(enabled)
    def close(self):
        for device in reversed(self.devices):
            try:
                if hasattr(device, "off"):
                    device.off()
                device.close()
            except Exception:
                logger.warning("GPIO cleanup failed; output state requires physical inspection.")
        self.devices.clear()
        if self.factory is not None:
            try:
                self.factory.close()
            except Exception:
                logger.warning("GPIO factory cleanup failed.")
            self.factory = None


class HardwareController:
    """Poll/debounce physical permission using the application's privacy lock.

    No callbacks run under a different controller lock, avoiding lock inversion
    with set_state. Faults never auto-recover or unmute. LED faults also fail closed.
    """
    def __init__(self, app, config, backend_factory=None, clock=time.monotonic):
        self.app, self.config, self.clock = app, config, clock
        self.stop_event, self.thread = Event(), None
        self.closed = self.faulted = self.shutting_down = False
        self.backend = NoopBackend()
        self.candidate = None
        self.candidate_since = 0
        self.stable = None
        self.armed = False
        self.last_rgb = None
        app.set_muted(True)
        app.set_physical_muted(True)
        try:
            if backend_factory is None:
                backend_factory = {"lgpio": lambda: LGPIOBackend(config),
                                   "mock": MockBackend, "none": NoopBackend}[config.backend]
            self.backend = backend_factory()
            if not self.backend.available:
                raise RuntimeError("GPIO unavailable")
            self.poll_once()
        except Exception:
            self._fault()
        except BaseException:
            try:
                self.backend.close()
            except Exception:
                logger.warning("GPIO shutdown cleanup failed.")
            raise

    def _fault(self):
        if self.faulted:
            return
        self.faulted = True
        self.armed = False
        self.app.set_physical_muted(True)
        self.app.set_muted(True)
        try:
            self.backend.close()
        except Exception:
            pass
        self.backend = NoopBackend()
        logger.error("GPIO control unavailable; microphone remains muted until restart.")

    def poll_once(self):
        with self.app.privacy.lock:
            if self.closed or self.faulted or self.shutting_down:
                return
            try:
                muted = self.backend.read_muted()
                if type(muted) is not bool:
                    raise ValueError("Invalid GPIO sample")
                now = self.clock()
                if muted:
                    self.app.set_physical_muted(True)  # Privacy assertion is not delayed by debounce.
                    self.app.set_muted(True)
                if self.candidate is not muted:
                    self.candidate, self.candidate_since = muted, now
                if now - self.candidate_since >= self.config.debounce and self.stable is not muted:
                    self.stable = muted
                    if muted:
                        self.armed = True
                    elif self.armed:
                        self.armed = False
                        self.app.set_physical_muted(False)
                        self.app.set_muted(False)  # A deliberate stable physical release is authorization.
                self.update(self.app.state)
            except Exception:
                self._fault()

    def update(self, state):
        with self.app.privacy.lock:
            if state == S.SHUTTING_DOWN:
                self.shutting_down = True
            if self.closed or self.faulted:
                return
            rgb = ((False, False, False) if self.shutting_down else
                   (True, False, False) if self.app.privacy.muted else
                   (False, True, False) if state == S.LISTENING else
                   (False, False, True) if state in {S.PROCESSING, S.SPEAKING} else
                   (False, False, False))
            if rgb != self.last_rgb:
                try:
                    self.backend.set_rgb(*rgb)
                    self.last_rgb = rgb
                except Exception:
                    self._fault()

    def start(self):
        if self.thread is None and not self.faulted and not self.closed:
            self.thread = Thread(target=self._run, name="nova-gpio", daemon=True)
            self.thread.start()
    def _run(self):
        while not self.stop_event.wait(self.config.poll_interval):
            self.poll_once()
            if self.faulted:
                return
    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        with self.app.privacy.lock:
            if self.closed:
                return
            self.closed = True
            self.app.set_physical_muted(True)
            self.app.set_muted(True)
            try:
                self.backend.set_rgb(False, False, False)
            except Exception:
                pass
            try:
                self.backend.close()
            except Exception:
                logger.warning("GPIO shutdown cleanup failed.")
