from pathlib import Path
import os
import math

from dotenv import load_dotenv
from offline_ai_companion.core.platform_config import runtime_defaults, project_path, optional_integer


PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = project_path(PROJECT_ROOT, os.getenv("NOVA_ENV_FILE", ".env"))

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

PLATFORM_DEFAULTS = runtime_defaults(profile=os.getenv("NOVA_PROFILE", ""))


APP_NAME = os.getenv(
    "APP_NAME",
    "OfflineAICompanion",
)

APP_ENV = os.getenv(
    "APP_ENV",
    "development",
)

LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO",
)

OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://localhost:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "llama3.2:1b",
)

WEATHER_API_KEY = os.getenv(
    "WEATHER_API_KEY",
    "",
)

NEWS_API_KEY = os.getenv(
    "NEWS_API_KEY",
    "",
)

DATABASE_PATH = project_path(PROJECT_ROOT, os.getenv(
    "DATABASE_PATH", "sample-data/memory/companion.db",
))

MIC_ENABLED = (
    os.getenv("MIC_ENABLED", "true").lower()
    == "true"
)

WHISPER_EXECUTABLE = project_path(PROJECT_ROOT, os.getenv(
    "WHISPER_EXECUTABLE", PLATFORM_DEFAULTS["WHISPER_EXECUTABLE"],
))

WHISPER_MODEL_PATH = project_path(PROJECT_ROOT, os.getenv(
    "WHISPER_MODEL_PATH", PLATFORM_DEFAULTS["WHISPER_MODEL_PATH"],
))

WHISPER_LANGUAGE = os.getenv(
    "WHISPER_LANGUAGE",
    "en",
)

PIPER_EXECUTABLE = project_path(PROJECT_ROOT, os.getenv(
    "PIPER_EXECUTABLE", PLATFORM_DEFAULTS["PIPER_EXECUTABLE"],
))

PIPER_MODEL_PATH = project_path(PROJECT_ROOT, os.getenv(
    "PIPER_MODEL_PATH", PLATFORM_DEFAULTS["PIPER_MODEL_PATH"],
))

# Unset limits preserve the previous Windows commands and model payloads.
WHISPER_THREADS = optional_integer("WHISPER_THREADS", 1, 16)
NOVA_AUDIO_QUEUE_SIZE = optional_integer("NOVA_AUDIO_QUEUE_SIZE", 1, 1000)
NOVA_OLLAMA_NUM_CTX = optional_integer("NOVA_OLLAMA_NUM_CTX", 128, 8192)
NOVA_OLLAMA_NUM_THREAD = optional_integer("NOVA_OLLAMA_NUM_THREAD", 1, 16)

ASSISTANT_NAME = os.getenv(
    "ASSISTANT_NAME",
    "Nova",
).strip()

WAKE_PHRASES = tuple(
    phrase.strip().lower()
    for phrase in os.getenv(
        "WAKE_PHRASES",
        "Nova,hey Nova",
    ).split(",")
    if phrase.strip()
)

PASSIVE_MEMORY_ENABLED = (
    os.getenv("PASSIVE_MEMORY_ENABLED", "false")
    .strip()
    .lower()
    in {"true", "1", "yes", "on"}
)

PASSIVE_MEMORY_QUEUE_SIZE = int(
    os.getenv("PASSIVE_MEMORY_QUEUE_SIZE", "10")
)

# Passive extraction has its own timeout and no automatic retries.
PASSIVE_MEMORY_LLM_TIMEOUT = float(
    os.getenv("PASSIVE_MEMORY_LLM_TIMEOUT", "30")
)


def _retention_setting(name: str) -> int:
    value = int(os.getenv(name, "0"))
    if value < 0:
        raise ValueError(f"{name} must be zero or a positive integer.")
    return value


# Zero preserves existing data; expiry never deletes confirmed memory.
PASSIVE_MEMORY_RETENTION_DAYS = _retention_setting("PASSIVE_MEMORY_RETENTION_DAYS")
CONVERSATION_RETENTION_SECONDS = _retention_setting("CONVERSATION_RETENTION_SECONDS")

# IANA timezone, explicit and independent of the Windows process timezone.
REMINDER_TIMEZONE = os.getenv("REMINDER_TIMEZONE", "Asia/Kolkata").strip()


def _audio_device_setting(name):
    value = os.getenv(name, "").strip()
    if not value:
        return None
    index = int(value)
    if index < 0:
        raise ValueError(f"{name} must be a nonnegative device index or empty.")
    return index


NOVA_INPUT_DEVICE = _audio_device_setting("NOVA_INPUT_DEVICE")
NOVA_OUTPUT_DEVICE = _audio_device_setting("NOVA_OUTPUT_DEVICE")

NOVA_EXPERIMENTAL_INTERRUPTION = os.getenv("NOVA_EXPERIMENTAL_INTERRUPTION", "false").lower() in {"true", "1", "yes", "on"}
NOVA_SPOKEN_INTERRUPTION = os.getenv("NOVA_SPOKEN_INTERRUPTION", "false").lower() in {"true", "1", "yes", "on"}
if NOVA_SPOKEN_INTERRUPTION and not NOVA_EXPERIMENTAL_INTERRUPTION:
    raise ValueError("Spoken interruption requires NOVA_EXPERIMENTAL_INTERRUPTION=true.")

def _interruption_timeout(name, default):
    import math
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        raise ValueError(f"{name} must be a numeric timeout.") from None
    if not math.isfinite(value) or not 0 < value <= 120:
        raise ValueError(f"{name} must be positive and at most 120 seconds.")
    return value

NOVA_INTERRUPT_LLM_TIMEOUT = _interruption_timeout("NOVA_INTERRUPT_LLM_TIMEOUT", "30")
NOVA_INTERRUPT_STT_TIMEOUT = _interruption_timeout("NOVA_INTERRUPT_STT_TIMEOUT", "5")

NOVA_RUNTIME_DIAGNOSTICS = os.getenv("NOVA_RUNTIME_DIAGNOSTICS", "false").lower() in {"true", "1", "yes", "on"}
try:
    NOVA_RUNTIME_INTERVAL = float(os.getenv("NOVA_RUNTIME_INTERVAL", "30"))
except ValueError:
    raise ValueError("Runtime sample interval must be numeric.") from None
if not math.isfinite(NOVA_RUNTIME_INTERVAL) or not .1 <= NOVA_RUNTIME_INTERVAL <= 3600:
    raise ValueError("Runtime sample interval must be between 0.1 and 3600 seconds.")
