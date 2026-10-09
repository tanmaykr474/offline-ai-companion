"""Experimental stop-only input. Never route monitored speech to memory/tools."""
import logging
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread

from offline_ai_companion.audio.continuous_recorder import ContinuousRecorder
from offline_ai_companion.core.cancellation import ResponseInterrupted
from offline_ai_companion.core.wake_detector import WakeDetector
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.stt.transcript_filter import is_invalid_transcript, strip_audio_captions

logger = logging.getLogger("nova.audio")


class CombinedCancel:
    def __init__(self, *events):
        self.events = events

    def is_set(self):
        return any(event.is_set() for event in self.events)


def is_spoken_stop(transcript, reference="", detector=None):
    if is_invalid_transcript(transcript):
        return False
    detector = detector or WakeDetector()
    detection = detector.detect(strip_audio_captions(transcript))
    if not detection.activated or detection.command.lower().strip(" .!?\t\r\n") != "stop":
        return False
    # Reject output that could itself produce the stop phrase. This is not AEC.
    reference_words = " ".join(re.findall(r"\w+", reference.lower()))
    for phrase in detector.wake_phrases:
        stop = " ".join(re.findall(r"\w+", phrase.lower())) + " stop"
        if re.search(r"\b" + re.escape(stop) + r"\b", reference_words):
            return False
    return True


class StopMonitor:
    def __init__(self, control, privacy, on_stop, device=None, stt_timeout=5,
                 recorder=None, stt=None):
        self.control, self.privacy, self.on_stop = control, privacy, on_stop
        self.recorder = recorder or ContinuousRecorder(device=device, max_duration=3,
            silence_duration=.3, preroll_duration=.2, queue_size=10)
        self.recorder.privacy = privacy
        self.stt = stt or WhisperSTT()
        self.stt_timeout = stt_timeout
        self.stop_event = Event()
        self.thread = None
        self.token = None

    def start(self, token):
        if self.thread is not None and self.thread.is_alive():
            if self.token is token:
                return
            raise RuntimeError("Previous stop monitor must close before new capture.")
        self.token = token
        self.stop_event = Event()
        self.thread = Thread(target=self._run, args=(token, self.stop_event), name="nova-stop-monitor", daemon=True)
        self.thread.start()

    def _run(self, token, stop):
        cancel = CombinedCancel(stop, token.cancel)
        try:
            with TemporaryDirectory(prefix="nova-interrupt-") as directory:
                path = Path(directory) / "utterance.wav"
                while not cancel.is_set():
                    valid, capture_reference = self.control.snapshot(token)
                    if not valid:
                        break
                    if self.privacy.muted:
                        stop.wait(.05)
                        continue
                    generation, _ = self.privacy.snapshot()
                    try:
                        audio = self.recorder.record_utterance(path, stop_event=cancel)
                        if audio is None or cancel.is_set():
                            continue
                        transcript = self.stt.transcribe(audio, cancel_event=cancel, timeout=self.stt_timeout)
                        with self.privacy.guard(generation) as allowed:
                            if not allowed or cancel.is_set():
                                continue
                            valid, reference = self.control.snapshot(token)
                            if (valid and reference == capture_reference
                                    and is_spoken_stop(transcript, reference)):
                                self.on_stop(token)
                                break
                    finally:
                        path.unlink(missing_ok=True)
        except ResponseInterrupted:
            pass
        except Exception as exc:
            logger.warning("Stop monitor unavailable: %s", type(exc).__name__)

    def stop(self, timeout=3):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout)
        return self.thread is None or not self.thread.is_alive()
