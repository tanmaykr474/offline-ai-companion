
import logging
from inspect import signature
from dataclasses import dataclass
from datetime import datetime
from contextlib import nullcontext
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
import time
from offline_ai_companion.core.runtime_metrics import metrics

from offline_ai_companion.stt.transcript_filter import is_invalid_transcript
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.core.privacy_policy import allows_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AcceptedSpeech:
    transcript: str
    captured_at: datetime


class PassiveMemoryWorker:
    """Process passive transcripts outside the voice loop."""

    def __init__(
        self,
        processor,
        max_queue_size: int = 10,
        max_transcript_chars: int = 16000,
    ) -> None:
        if (not isinstance(max_queue_size, int) or max_queue_size < 1
                or not isinstance(max_transcript_chars, int) or max_transcript_chars < 1):
            raise ValueError(
                "Queue size must be positive."
            )

        self.processor = processor
        self.queue = Queue(maxsize=max_queue_size)
        self.stop_event = Event()
        self.thread = None
        self.lock = Lock()
        self.accepting = False
        self.privacy = None
        self.max_transcript_chars = max_transcript_chars
        self.busy_since = None

    def start(self) -> None:
        """Start one background processing thread."""

        with self.lock:
            if self.thread is not None:
                if self.thread.is_alive():
                    return

            self.stop_event.clear()
            self.accepting = True

            self.thread = Thread(
                target=self._run,
                name="passive-memory-worker",
                # Accepted memories must finish before process exit.
                daemon=False,
            )

            self.thread.start()

    def submit(self, transcript: str, captured_at: datetime | None = None) -> bool:
        """Queue speech without blocking the voice loop."""

        if not isinstance(transcript, str):
            return False
        if len(transcript) > self.max_transcript_chars:
            metrics.count("passive_rejected_size")
            logger.warning("Passive speech rejected: size limit exceeded.")
            return False

        transcript = transcript.strip()

        if is_invalid_transcript(transcript):
            return False
        if not allows_storage(transcript):
            return False

        # Timestamp acceptance, not eventual extraction after queue delays.
        captured_at = captured_at or datetime.now().astimezone()
        if captured_at.utcoffset() is None:
            raise ValueError("Capture timestamp must be timezone-aware.")

        privacy = self.privacy
        generation = privacy.snapshot()[0] if privacy is not None else None
        with privacy.guard(generation) if privacy is not None else nullcontext(True) as allowed:
            if not allowed:
                return False
            with self.lock:
                if not self.accepting:
                    return False
                try:
                    self.queue.put_nowait(_AcceptedSpeech(transcript, captured_at))
                    return True
                except Full:
                    metrics.count("passive_rejected_full")
                    logger.warning("Passive memory queue is full; dropping transcript.")
                    return False

    def _run(self) -> None:
        """Drain accepted transcripts, then exit after shutdown is requested."""

        while True:
            try:
                speech = self.queue.get(
                    timeout=0.2
                )
            except Empty:
                # Submission and shutdown share this lock. A transcript may
                # have arrived just after get() timed out; do not strand it.
                with self.lock:
                    if self.stop_event.is_set() and self.queue.empty():
                        return
                continue

            try:
                self.busy_since = time.monotonic()
                if (issubclass(type(self.processor), PassiveMemoryProcessor)
                        and "captured_at" in signature(self.processor.process).parameters):
                    saved_count = self.processor.process(
                        speech.transcript, captured_at=speech.captured_at,
                    )
                else:
                    # Preserve the one-argument interface of injected processors.
                    saved_count = self.processor.process(speech.transcript)

                logger.info(
                    "Passive memory processing completed: "
                    "%d new memories saved.",
                    saved_count,
                )
                metrics.count("passive_completed")

                print(
                    f"[MEMORY] Processing completed: "
                    f"{saved_count} new memories saved.",
                    flush=True,
                )

            except Exception as exc:
                metrics.count("passive_failures")
                logger.error(
                    "Passive memory processing failed: %s", type(exc).__name__,
                )

                print(
                    "[MEMORY] Background processing failed.",
                    flush=True,
                )

            finally:
                self.busy_since = None
                self.queue.task_done()

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop accepting work and request shutdown.

        All accepted items are processed. False means the worker is still
        draining; callers can wait again with stop(). No threads are killed.
        The non-daemon thread also protects accepted work at process exit.
        """

        if timeout < 0:
            raise ValueError("Shutdown timeout cannot be negative.")

        with self.lock:
            self.accepting = False
            self.stop_event.set()
            thread = self.thread

        if thread is current_thread():
            return False
        if thread is not None:
            thread.join(timeout=timeout)

        stopped = (
            thread is None
            or not thread.is_alive()
        )

        return stopped
