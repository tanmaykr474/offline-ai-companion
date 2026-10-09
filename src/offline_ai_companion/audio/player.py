
from pathlib import Path

import sounddevice as sd
import soundfile as sf


class AudioPlayer:
    """Play WAV audio with controlled error handling."""

    def play(self, audio_path: str | Path) -> None:
        path = Path(audio_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"Audio file not found: {path}"
            )

        try:
            audio, sample_rate = sf.read(
                path,
                dtype="float32",
            )
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(
                f"Cannot read audio file: {exc}"
            ) from exc

        try:
            sd.play(
                audio,
                samplerate=sample_rate,
            )
            sd.wait()

        except (sd.PortAudioError, OSError) as exc:
            raise RuntimeError(
                f"Audio playback failed: {exc}"
            ) from exc

        finally:
            sd.stop()
