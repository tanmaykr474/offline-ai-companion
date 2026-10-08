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

MIC_ENABLED = (
    os.getenv("MIC_ENABLED", "true").lower()
    == "true"
)