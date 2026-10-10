
import subprocess
from pathlib import Path
from offline_ai_companion.core.performance import timed
from offline_ai_companion.audio.cancellable_subprocess import run_cancellable, run_owned

from offline_ai_companion.config import (
    WHISPER_EXECUTABLE,
    WHISPER_MODEL_PATH,
    WHISPER_LANGUAGE,
    WHISPER_THREADS,
)


class WhisperSTT:
    """Offline speech-to-text using whisper.cpp."""

    def __init__(
        self,
        executable: Path = WHISPER_EXECUTABLE,
        model_path: Path = WHISPER_MODEL_PATH,
        language: str = WHISPER_LANGUAGE,
        threads: int | None = WHISPER_THREADS,
    ) -> None:
        self.executable = Path(executable)
        self.model_path = Path(model_path)
        self.language = language
        if threads is not None and (not isinstance(threads, int) or not 1 <= threads <= 16):
            raise ValueError("Whisper threads must be between one and 16.")
        self.threads = threads

    @timed("transcription")
    def transcribe(self, audio_path: str | Path, *, cancel_event=None, timeout=120) -> str:
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
            "--prompt",
            "Nova is the name of the AI assistant. "
            "Hey Nova. Nova, what is my schedule?",
        ]

        if self.threads is not None:
            command.extend(("-t", str(self.threads)))

        try:
            if cancel_event is not None:
                result = run_cancellable(command, cancel_event=cancel_event, timeout=timeout)
            else:
                result = run_owned(
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
            ) from None
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Whisper transcription failed."
            ) from None
        except OSError as exc:
            raise RuntimeError(
                "Cannot start Whisper executable."
            ) from None

        # whisper.cpp writes acoustic segments on separate lines. A segment
        # break is not a sentence boundary and can split a supported statement.
        # Preserve punctuation (including questions/quotes), join only whitespace.
        return " ".join(result.stdout.split())
