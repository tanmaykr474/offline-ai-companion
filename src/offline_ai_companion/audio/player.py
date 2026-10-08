
from pathlib import Path

import sounddevice as sd
import soundfile as sf


class AudioPlayer:
    """Play WAV audio through the default speaker."""

    def play(self, audio_path: str | Path) -> None:
        path = Path(audio_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"Audio file not found: {path}"
            )

        audio, sample_rate = sf.read(
            path,
            dtype="float32",
        )

        try:
            sd.play(
                audio,
                samplerate=sample_rate,
            )
            sd.wait()
        finally:
            sd.stop()
