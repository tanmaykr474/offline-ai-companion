"""Foreground or headless runtime controls and graceful POSIX termination."""
from contextlib import contextmanager
import logging
import os
import platform
import signal

from .hardware import HardwareConfig, HardwareConfigurationError, HardwareController, boolean
from .privacy import WindowsMuteHotkey, PosixMuteConsole

logger = logging.getLogger("nova.service")
CONFIGURATION_EXIT = 78


@contextmanager
def termination_handler(app, signals=signal):
    previous = signals.getsignal(signals.SIGTERM)
    requested = False
    def terminate(signum, frame):
        nonlocal requested
        if requested:
            return  # Do not interrupt accepted-work draining with repeated SIGTERM.
        requested = True
        app.stop_event.set()
        # KeyboardInterrupt follows the existing tested cleanup path, including
        # owned subprocess and PortAudio finally blocks and SQLite rollback.
        raise KeyboardInterrupt
    signals.signal(signals.SIGTERM, terminate)
    try:
        yield
    finally:
        signals.signal(signals.SIGTERM, previous)


def run_voice(app_factory, environment=None, backend_factory=None, signals=signal):
    env = os.environ if environment is None else environment
    hardware = keys = app = None
    try:
        config = HardwareConfig.from_env(env)
        headless = boolean(env, "NOVA_HEADLESS", False)
        if headless and (platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"}
                         or config.backend != "lgpio"):
            raise HardwareConfigurationError("Headless production requires Linux ARM64 and local lgpio controls.")
        app = app_factory()
        with termination_handler(app, signals):
            if headless or config.backend != "none":
                app.set_muted(True)
                hardware = HardwareController(app, config, backend_factory)
                app._hardware = hardware
                if hardware.faulted and headless:
                    raise HardwareConfigurationError("Required GPIO controls unavailable.")
                hardware.start()
            if not headless:
                interrupt = app.request_interruption if app.interruption_enabled else None
                if os.name == "nt":
                    keys = WindowsMuteHotkey(app.toggle_mute, interrupt=interrupt)
                else:
                    keys = PosixMuteConsole(app.toggle_mute, interrupt=interrupt,
                                            on_unavailable=lambda: app.set_muted(True))
                keys.start()
                print("[PRIVACY] Console mute: M" + ("" if os.name == "nt" else " + Enter"), flush=True)
            app.run()
        return 0
    except HardwareConfigurationError:
        logger.error("Permanent hardware/startup configuration error; capture not started.")
        return CONFIGURATION_EXIT
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error("Voice runtime failure category=%s", type(exc).__name__)
        return 1
    finally:
        if keys is not None:
            keys.stop()
        if hardware is not None:
            hardware.close()
        # Covers startup failure before run() owns normal worker/audio cleanup.
        if app is not None:
            owner = getattr(app, "_temporary_audio", None)
            if owner is not None:
                owner.close()
