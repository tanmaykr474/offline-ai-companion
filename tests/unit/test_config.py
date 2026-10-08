from offline_ai_companion.config import (
    APP_NAME,
    APP_ENV,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    DATABASE_PATH,
)


def test_default_configuration():
    assert APP_NAME == "OfflineAICompanion"
    assert APP_ENV == "development"
    assert OLLAMA_HOST == "http://localhost:11434"
    assert OLLAMA_MODEL == "llama3.2:1b"
    assert DATABASE_PATH.name == "companion.db"