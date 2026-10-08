from pathlib import Path
import os

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


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

DATABASE_PATH = Path(
    os.getenv(
        "DATABASE_PATH",
        "sample-data/memory/companion.db",
    )
)

if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = PROJECT_ROOT / DATABASE_PATH

MIC_ENABLED = (
    os.getenv("MIC_ENABLED", "true").lower()
    == "true"
)

WHISPER_EXECUTABLE = PROJECT_ROOT / os.getenv(
    "WHISPER_EXECUTABLE",
    "deployment/windows/whisper-cpp/Release/whisper-cli.exe",
)

WHISPER_MODEL_PATH = PROJECT_ROOT / os.getenv(
    "WHISPER_MODEL_PATH",
    "deployment/models/ggml-tiny.en.bin",
)

WHISPER_LANGUAGE = os.getenv(
    "WHISPER_LANGUAGE",
    "en",
)

PIPER_EXECUTABLE = PROJECT_ROOT / os.getenv(
    "PIPER_EXECUTABLE",
    "deployment/windows/piper/piper.exe",
)

PIPER_MODEL_PATH = PROJECT_ROOT / os.getenv(
    "PIPER_MODEL_PATH",
    "deployment/models/piper/en_US-lessac-medium.onnx",
)