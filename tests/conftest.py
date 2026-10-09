"""Select an isolated runtime before test modules import Nova configuration.

Tests choose experimental/online modes explicitly with fixtures. A developer's
live .env or exported settings must not enable devices/providers or change those
fixtures' control flow. This bootstrap applies only to pytest, never Nova startup.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory


_PREFIXES = ("NOVA_", "OLLAMA_", "WHISPER_", "PIPER_", "PASSIVE_MEMORY_", "CONVERSATION_RETENTION_")
_SETTINGS = {"APP_NAME", "APP_ENV", "LOG_LEVEL", "MIC_ENABLED", "DATABASE_PATH",
             "ASSISTANT_NAME", "WAKE_PHRASES", "REMINDER_TIMEZONE", "WEATHER_API_KEY", "NEWS_API_KEY"}
_original = {name: value for name, value in os.environ.items()
             if name.startswith(_PREFIXES) or name in _SETTINGS}
for _name in _original:
    os.environ.pop(_name)

_runtime = TemporaryDirectory(prefix="nova-pytest-", ignore_cleanup_errors=True)
_env_file = Path(_runtime.name) / "test.env"
_env_file.write_text("# Isolated pytest runtime; no live credentials or devices.\n", encoding="utf-8")
os.environ["NOVA_ENV_FILE"] = str(_env_file)
os.environ["DATABASE_PATH"] = str(Path(_runtime.name) / "companion.db")


def pytest_unconfigure(config):
    # Restore only Nova settings; keep unrelated pytest/plugin environment intact.
    for name in list(os.environ):
        if name.startswith(_PREFIXES) or name in _SETTINGS:
            os.environ.pop(name)
    os.environ.update(_original)
    _runtime.cleanup()
