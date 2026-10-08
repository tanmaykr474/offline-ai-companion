
import numpy as np


class VoiceActivityDetector:
    """Lightweight RMS-energy-based speech activity detector."""

    def __init__(
        self,
        threshold: float = 0.018,
    ) -> None:
        if threshold <= 0:
            raise ValueError("Threshold must be positive.")

        self.threshold = threshold

    def is_speech(self, audio: np.ndarray) -> bool:
        samples = np.asarray(audio, dtype=np.float32)

        if samples.size == 0:
            return False

        rms = float(
            np.sqrt(np.mean(np.square(samples)))
        )

        return rms >= self.threshold
