
from collections import deque
from pathlib import Path
from threading import Event
import queue
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

from offline_ai_companion.audio.vad import VoiceActivityDetector


class ContinuousRecorder:
    """Record one utterance using microphone activity detection."""

    def __init__(
        self,
        sample_rate: int = 16000,
        block_duration: float = 0.1,
        silence_duration: float = 1.0,
        max_duration: float = 15.0,
        threshold: float = 0.018,
        preroll_duration: float = 0.3,
    ) -> None:
        if (
            sample_rate <= 0
            or block_duration <= 0
            or silence_duration <= 0
            or max_duration <= 0
            or preroll_duration < 0
        ):
            raise ValueError("Invalid recorder configuration.")

        if int(sample_rate * block_duration) < 1:
            raise ValueError("Audio block size must be at least one sample.")

        self.sample_rate = sample_rate
        self.block_size = int(sample_rate * block_duration)
        self.block_duration = block_duration
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.preroll_blocks = max(
            1, int(preroll_duration / block_duration)
        )
        self.vad = VoiceActivityDetector(threshold)

    def record_utterance(
        self,
        output_path: str | Path,
        stop_event: Event | None = None,
    ) -> Path | None:
        """Wait for speech and save one utterance.

        Returns None if stopped before an utterance completes.
        """
        output_path = Path(output_path)
        stop_event = stop_event or Event()

        if stop_event.is_set():
            return None

        audio_queue = queue.Queue(maxsize=100)
        preroll = deque(maxlen=self.preroll_blocks)
        frames = []

        started = False
        speech_started_at = None
        last_speech_at = None

        def callback(indata, frame_count, time_info, status):
            if stop_event.is_set():
                return

            try:
                audio_queue.put_nowait(indata.copy())
            except queue.Full:
                # Discard a block rather than blocking the audio callback.
                pass

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.block_size,
            callback=callback,
        ):
            while not stop_event.is_set():
                try:
                    block = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                now = time.monotonic()
                speech = self.vad.is_speech(block)

                if not started:
                    preroll.append(block)

                    if not speech:
                        continue

                    started = True
                    speech_started_at = now
                    last_speech_at = now
                    frames.extend(preroll)
                    preroll.clear()
                    continue

                frames.append(block)

                if speech:
                    last_speech_at = now

                if (
                    now - last_speech_at
                    >= self.silence_duration
                ):
                    break

                if (
                    now - speech_started_at
                    >= self.max_duration
                ):
                    break

        if stop_event.is_set() or not frames:
            return None

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        audio = np.concatenate(frames, axis=0)

        sf.write(
            output_path,
            audio,
            self.sample_rate,
            subtype="PCM_16",
        )

        return output_path
