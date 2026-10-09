
from pathlib import Path
import logging

import sounddevice as sd
import soundfile as sf
from offline_ai_companion.core.cancellation import check_cancel

logger = logging.getLogger("nova.audio")


class AudioPlayer:
    """Play WAV audio with controlled error handling."""

    def __init__(self, device: int | None = None):
        self.device = device

    def play(self, audio_path: str | Path, *, cancel_event=None) -> None:
        check_cancel(cancel_event)
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
            options = {"device": self.device} if self.device is not None else {}
            if cancel_event is not None:
                self._play_interruptible(audio, sample_rate, cancel_event, options)
                return
            sd.play(audio, samplerate=sample_rate, **options)
            status = sd.wait()
            if status is not None and getattr(status, "output_underflow", False) is True:
                logger.warning("Playback underrun: output_underflows=1")

        except (sd.PortAudioError, OSError) as exc:
            raise RuntimeError(
                f"Audio playback failed: {exc}"
            ) from exc

        finally:
            if cancel_event is None:
                sd.stop()

    def _play_interruptible(self, audio, sample_rate, cancel_event, options):
        import numpy as np
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)
        block_size = max(1, int(sample_rate * .02))
        with sd.OutputStream(samplerate=sample_rate, channels=samples.shape[1],
                             dtype="float32", blocksize=block_size, **options) as stream:
            try:
                for start in range(0, len(samples), block_size):
                    check_cancel(cancel_event)
                    if stream.write(samples[start:start + block_size]) is True:
                        logger.warning("Playback underrun: output_underflows=1")
                check_cancel(cancel_event)
            except BaseException:
                stream.abort()
                raise
        check_cancel(cancel_event)
