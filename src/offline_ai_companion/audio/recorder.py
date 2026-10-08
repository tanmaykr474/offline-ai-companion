from pathlib import Path

import sounddevice as sd
import soundfile as sf


class AudioRecorder:
    """Records microphone audio and saves it as WAV."""

    def __init__(
        self,
        sample_rate: int = 16_000,
        channels: int = 1,
        dtype: str = "float32",
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype

    def record(
        self,
        duration: float,
        output_path: Path,
    ) -> Path:
        """
        Record microphone audio for a fixed duration.

        Args:
            duration: Recording duration in seconds.
            output_path: Destination WAV file.

        Returns:
            Path to the recorded WAV file.
        """

        if duration <= 0:
            raise ValueError("Recording duration must be greater than zero.")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        frames = int(duration * self.sample_rate)

        print(f"Recording for {duration:.1f} seconds...")

        recording = sd.rec(
            frames,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
        )

        sd.wait()

        sf.write(
            output_path,
            recording,
            self.sample_rate,
        )

        print(f"Recording saved to: {output_path}")

        return output_path