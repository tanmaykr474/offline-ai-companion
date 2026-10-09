
import subprocess
from pathlib import Path
from offline_ai_companion.core.performance import timed
from offline_ai_companion.core.privacy_policy import model_text
from offline_ai_companion.audio.cancellable_subprocess import run_cancellable, run_owned
from offline_ai_companion.core.cancellation import check_cancel, ResponseInterrupted

from offline_ai_companion.config import (
    PIPER_EXECUTABLE,
    PIPER_MODEL_PATH,
)


class PiperTTS:
    """Offline text-to-speech using Piper."""

    def __init__(
        self,
        executable: Path = PIPER_EXECUTABLE,
        model_path: Path = PIPER_MODEL_PATH,
    ) -> None:
        self.executable = Path(executable)
        self.model_path = Path(model_path)

    @timed("tts_generation")
    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        *, cancel_event=None,
    ) -> Path:
        if not text or not text.strip():
            raise ValueError("Speech text cannot be empty.")
        text = model_text(text)
        check_cancel(cancel_event)

        if not self.executable.is_file():
            raise FileNotFoundError(
                f"Piper executable not found: {self.executable}"
            )

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Piper model not found: {self.model_path}"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            str(self.executable.resolve()),
            "--model",
            str(self.model_path.resolve()),
            "--output_file",
            str(output_path.resolve()),
        ]

        try:
            output_path.unlink(missing_ok=True)
            if cancel_event is not None:
                run_cancellable(command, input=text.strip() + "\n", cancel_event=cancel_event)
            else:
                run_owned(
                    command,
                    input=text.strip() + "\n",
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    check=True,
                    timeout=120,
                )
        except ResponseInterrupted:
            output_path.unlink(missing_ok=True)
            raise
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Piper speech synthesis timed out."
            ) from None
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Piper speech synthesis failed."
            ) from None
        except OSError as exc:
            raise RuntimeError(
                "Cannot start Piper executable."
            ) from None

        if not output_path.is_file():
            raise RuntimeError(
                "Piper did not generate an audio file."
            )

        return output_path
