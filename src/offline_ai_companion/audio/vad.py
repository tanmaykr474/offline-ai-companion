
import numpy as np


class VoiceActivityDetector:
    """Lightweight RMS-energy-based voice activity detector."""

    def __init__(
        self,
        threshold: float = 0.018,
    ) -> None:
        if not np.isfinite(threshold) or threshold <= 0:
            raise ValueError("Threshold must be positive.")

        self.threshold = threshold

    @staticmethod
    def rms(audio: np.ndarray) -> float:
        samples = np.asarray(audio, dtype=np.float32)

        if samples.size == 0:
            return 0.0

        # Use float64 arithmetic for stable energy calculation.
        values = samples.astype(np.float64)
        return float(np.sqrt(np.mean(np.square(values))))

    def is_speech(self, audio: np.ndarray) -> bool:
        return self.rms(audio) >= self.threshold
