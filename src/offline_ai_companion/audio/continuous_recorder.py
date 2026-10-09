
from collections import deque
from contextlib import ExitStack, nullcontext
from pathlib import Path
from threading import Event
import os
import queue
import time
import logging
import math
from offline_ai_companion.core.runtime_metrics import metrics

import numpy as np
import sounddevice as sd
import soundfile as sf

from offline_ai_companion.audio.vad import VoiceActivityDetector
from offline_ai_companion.audio.diagnostics import event

logger = logging.getLogger("nova.audio")


class ContinuousRecorder:
    """Record utterances with VAD and reminder interruption."""

    def __init__(
        self,
        sample_rate: int = 16000,
        block_duration: float = 0.1,
        silence_duration: float = 1.0,
        max_duration: float = 15.0,
        threshold: float | None = None,
        preroll_duration: float = 0.7,
        min_speech_duration: float = 0.2,
        queue_size: int = 100,
        device: int | None = None,
        input_stall_timeout: float = 5.0,
    ) -> None:

        if threshold is None:
            threshold = float(
                os.getenv("VAD_THRESHOLD", "0.018")
            )

        if (
            not all(math.isfinite(value) for value in (sample_rate, block_duration,
                silence_duration, max_duration, preroll_duration, min_speech_duration))
            or not isinstance(queue_size, int)
            or sample_rate <= 0
            or block_duration <= 0
            or silence_duration <= 0
            or max_duration <= 0
            or preroll_duration < 0
            or min_speech_duration <= 0
            or queue_size < 1
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
        # Bound retained samples even if a faulty backend supplies blocks faster
        # than wall time, while retaining the normal utterance/pre-roll budget.
        self.max_capture_blocks = (math.ceil(max_duration / block_duration)
                                   + self.preroll_blocks + self.min_speech_blocks)

        self.vad = VoiceActivityDetector(threshold)
        self.privacy = None
        self.playback_cancel = None
        self.queue_size = queue_size
        self.device = device
        self.last_capture_stats = {"dropped_blocks": 0, "input_overflows": 0}
        if not math.isfinite(input_stall_timeout) or input_stall_timeout <= 0:
            raise ValueError("Input stall timeout must be positive and finite.")
        self.input_stall_timeout = input_stall_timeout
        self._active_queue = None

    @property
    def queue_depth(self):
        queue = self._active_queue
        return 0 if queue is None else queue.qsize()

    def record_utterance(
        self,
        output_path: str | Path,
        stop_event: Event | None = None,
        interrupt_event: Event | None = None,
    ) -> Path | None:

        output_path = Path(output_path)

        if stop_event is None:
            stop_event = Event()
        privacy = self.privacy
        generation, mute_cancel = privacy.snapshot() if privacy is not None else (None, Event())
        playback_cancel = self.playback_cancel
        stream_done = Event()
        counts = {"dropped_blocks": 0, "input_overflows": 0}
        self.last_capture_stats = counts.copy()

        def should_stop() -> bool:
            return (
                stop_event.is_set()
                or mute_cancel.is_set()
                or (playback_cancel is not None and playback_cancel.is_set())
                or (
                    interrupt_event is not None
                    and interrupt_event.is_set()
                )
            )

        if should_stop():
            return None

        audio_queue = queue.Queue(maxsize=self.queue_size)
        self._active_queue = audio_queue

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
            # Cancellation is latched for this stream. Do not acquire the
            # stream-opening lock on PortAudio's callback thread.
            if should_stop() or stream_done.is_set():
                return
            if status is not None and getattr(status, "input_overflow", False):
                counts["input_overflows"] += 1
            try:
                audio_queue.put_nowait(indata.copy())
            except queue.Full:
                counts["dropped_blocks"] += 1

        def open_stream(stack):
            options = {"device": self.device} if self.device is not None else {}
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.block_size,
                callback=callback,
                **options,
            )

            class ObservedStream:
                def __enter__(self):
                    result = stream.__enter__()
                    event("stream_open")
                    return result

                def __exit__(self, *args):
                    # Retire callbacks before asking PortAudio to close.
                    stream_done.set()
                    try:
                        result = stream.__exit__(*args)
                    except BaseException:
                        event("stream_close_failed")
                        raise
                    event("stream_closed")
                    return result

            stack.enter_context(ObservedStream())

        def finish_capture():
            self._active_queue = None
            self.last_capture_stats = counts.copy()
            metrics.count("audio_dropped_blocks", counts["dropped_blocks"])
            metrics.count("audio_input_overflows", counts["input_overflows"])
            if counts["dropped_blocks"] or counts["input_overflows"]:
                logger.warning("Capture discarded: dropped_blocks=%s input_overflows=%s",
                               counts["dropped_blocks"], counts["input_overflows"])
        with ExitStack() as stack:
            stack.callback(finish_capture)
            if privacy is not None:
                with privacy.guard(generation) as allowed:
                    if not allowed:
                        return None
                    open_stream(stack)
            else:
                open_stream(stack)

            last_block_at = time.monotonic()
            while not should_stop():
                if counts["dropped_blocks"] or counts["input_overflows"]:
                    break
                try:
                    block = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    if not should_stop() and time.monotonic() - last_block_at >= self.input_stall_timeout:
                        metrics.count("audio_stalls")
                        raise RuntimeError("Microphone stopped delivering audio blocks.")
                    continue

                if should_stop():
                    break

                now = time.monotonic()
                last_block_at = now
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
                if len(frames) >= self.max_capture_blocks:
                    break

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

        if should_stop() or not frames or counts["dropped_blocks"] or counts["input_overflows"]:
            return None

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        audio = np.concatenate(frames, axis=0)

        with privacy.guard(generation) if privacy is not None else nullcontext(True) as allowed:
            if not allowed or should_stop():
                return None
            sf.write(
                output_path,
                audio,
                self.sample_rate,
                subtype="PCM_16",
            )

        return output_path
