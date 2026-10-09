
from collections import deque
from pathlib import Path
from threading import Event
import os
import queue
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

from offline_ai_companion.audio.vad import VoiceActivityDetector


class ContinuousRecorder:
    """Record utterances with VAD and reminder interruption."""

    def __init__(
        self,
        sample_rate: int = 16000,
        block_duration: float = 0.1,
        silence_duration: float = 1.0,
        max_duration: float = 15.0,
        threshold: float | None = None,
        preroll_duration: float = 0.3,
        min_speech_duration: float = 0.3,
    ) -> None:

        if threshold is None:
            threshold = float(
                os.getenv("VAD_THRESHOLD", "0.018")
            )

        if (
            sample_rate <= 0
            or block_duration <= 0
            or silence_duration <= 0
            or max_duration <= 0
            or preroll_duration < 0
            or min_speech_duration <= 0
        ):
            raise ValueError("Invalid recorder configuration.")

        if int(sample_rate * block_duration) < 1:
            raise ValueError(
                "Audio block size must be at least one sample."
            )

        self.sample_rate = sample_rate
        self.block_duration = block_duration
        self.block_size = int(sample_rate * block_duration)
        self.silence_duration = silence_duration
        self.max_duration = max_duration

        self.preroll_blocks = max(
            1,
            int(np.ceil(preroll_duration / block_duration)),
        )

        self.min_speech_blocks = max(
            1,
            int(np.ceil(min_speech_duration / block_duration)),
        )

        self.vad = VoiceActivityDetector(threshold)

    def record_utterance(
        self,
        output_path: str | Path,
        stop_event: Event | None = None,
        interrupt_event: Event | None = None,
    ) -> Path | None:

        output_path = Path(output_path)

        if stop_event is None:
            stop_event = Event()

        def should_stop() -> bool:
            return (
                stop_event.is_set()
                or (
                    interrupt_event is not None
                    and interrupt_event.is_set()
                )
            )

        if should_stop():
            return None

        audio_queue = queue.Queue(maxsize=100)

        # Keep enough pre-roll for speech confirmation.
        preroll = deque(
            maxlen=(
                self.preroll_blocks
                + self.min_speech_blocks
            )
        )

        frames = []
        consecutive_speech = 0

        started = False
        speech_started_at = None
        last_speech_at = None

        def callback(
            indata,
            frame_count,
            time_info,
            status,
        ):
            if should_stop():
                return

            try:
                audio_queue.put_nowait(indata.copy())
            except queue.Full:
                pass

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.block_size,
            callback=callback,
        ):

            while not should_stop():
                try:
                    block = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if should_stop():
                    break

                now = time.monotonic()
                speech = self.vad.is_speech(block)

                if not started:
                    preroll.append(block)

                    if speech:
                        consecutive_speech += 1
                    else:
                        consecutive_speech = 0

                    if (
                        consecutive_speech
                        < self.min_speech_blocks
                    ):
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

        if should_stop() or not frames:
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
