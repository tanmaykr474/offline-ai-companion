
import subprocess
from pathlib import Path

from offline_ai_companion.config import (
    WHISPER_EXECUTABLE,
    WHISPER_MODEL_PATH,
    WHISPER_LANGUAGE,
)


class WhisperSTT:
    """Offline speech-to-text using whisper.cpp."""

    def __init__(
        self,
        executable: Path = WHISPER_EXECUTABLE,
        model_path: Path = WHISPER_MODEL_PATH,
        language: str = WHISPER_LANGUAGE,
    ) -> None:
        self.executable = Path(executable)
        self.model_path = Path(model_path)
        self.language = language

    def transcribe(self, audio_path: str | Path) -> str:
        audio_path = Path(audio_path)

        if not audio_path.is_file():
            raise FileNotFoundError(
                f"Audio file not found: {audio_path}"
            )

        if not self.executable.is_file():
            raise FileNotFoundError(
                f"Whisper executable not found: {self.executable}"
            )

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Whisper model not found: {self.model_path}"
            )

        command = [
            str(self.executable.resolve()),
            "-m",
            str(self.model_path.resolve()),
            "-f",
            str(audio_path.resolve()),
            "-l",
            self.language,
            "-nt",
            "-np",
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Whisper transcription timed out."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Whisper transcription failed: {exc.stderr}"
            ) from exc

        return result.stdout.strip()
