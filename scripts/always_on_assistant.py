
"""Always-on voice interface for Nova, the offline AI companion."""

from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from contextlib import contextmanager
import time
import os
from offline_ai_companion.core.performance import timed, enable_performance_logging
from offline_ai_companion.core.runtime_metrics import observed_runtime

from offline_ai_companion.audio.continuous_recorder import (
    ContinuousRecorder,
)
from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.audio.temporary import TemporaryAudio
from offline_ai_companion.core.privacy_policy import model_text
from offline_ai_companion.audio.recovery import AudioRecovery
from offline_ai_companion.audio.half_duplex import HalfDuplexAudio
from offline_ai_companion.audio.diagnostics import stage, event
from offline_ai_companion.config import (
    MIC_ENABLED,
    PASSIVE_MEMORY_ENABLED,
    PASSIVE_MEMORY_QUEUE_SIZE,
    NOVA_INPUT_DEVICE,
    NOVA_OUTPUT_DEVICE,
    NOVA_EXPERIMENTAL_INTERRUPTION,
    NOVA_SPOKEN_INTERRUPTION,
    NOVA_INTERRUPT_LLM_TIMEOUT,
    NOVA_INTERRUPT_STT_TIMEOUT,
)
from offline_ai_companion.core.activation_controller import (
    ActivationController,
)
from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.state import AssistantState, validate_transition
from offline_ai_companion.core.cancellation import (
    ResponseControl, ResponseInterrupted, cancellation_scope, current_cancel, check_cancel,
)
from offline_ai_companion.audio.stop_monitor import StopMonitor
from offline_ai_companion.llm.ollama import OllamaLLM
from offline_ai_companion.core.privacy import SoftwareMute, WindowsMuteHotkey, PosixMuteConsole
from offline_ai_companion.memory.passive_processor import (
    PassiveMemoryProcessor,
)
from offline_ai_companion.memory.passive_worker import (
    PassiveMemoryWorker,
)
from offline_ai_companion.scheduler.reminder_notifications import (
    ReminderNotifications,
)
from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.stt.transcript_filter import (
    is_invalid_transcript,
    strip_audio_captions,
)
from offline_ai_companion.tts.piper import PiperTTS


def is_usable_transcript(transcript: str) -> bool:
    """Reject empty or known non-speech transcriptions."""

    return not is_invalid_transcript(transcript)


class AlwaysOnAssistant:
    """Coordinate Nova's continuous voice-processing pipeline."""

    def __init__(self) -> None:
        self._privacy = SoftwareMute(muted=not MIC_ENABLED)
        # Audio input/output and local AI components.
        from offline_ai_companion.config import NOVA_AUDIO_QUEUE_SIZE
        options = {} if NOVA_AUDIO_QUEUE_SIZE is None else {"queue_size": NOVA_AUDIO_QUEUE_SIZE}
        self.recorder = ContinuousRecorder(device=NOVA_INPUT_DEVICE, **options)
        self.recorder.privacy = self.privacy
        self.player = AudioPlayer(device=NOVA_OUTPUT_DEVICE)
        self.stt = WhisperSTT()
        self.experimental_interruption = NOVA_EXPERIMENTAL_INTERRUPTION
        self.spoken_interruption = NOVA_SPOKEN_INTERRUPTION
        self.assistant = (Assistant(llm=OllamaLLM(timeout=NOVA_INTERRUPT_LLM_TIMEOUT, max_retries=0))
                          if self.experimental_interruption else Assistant())
        self.tts = PiperTTS()

        # Runtime state and audio failure recovery.
        self.stop_event = Event()
        self.audio_recovery = AudioRecovery()
        self.state = AssistantState.IDLE
        self._audio_gate = HalfDuplexAudio()
        self._closed = False

        # A wake-only utterance opens an eight-second command window.
        self.activation_controller = ActivationController(
            activation_timeout=8.0
        )

        # Passive memory is explicitly controlled by configuration.
        self.passive_worker = None

        if PASSIVE_MEMORY_ENABLED:
            repository = getattr(
                self.assistant,
                "passive_memory_repository",
                None,
            )

            if repository is None:
                raise RuntimeError(
                    "Passive memory is enabled, but no SQLite "
                    "passive-memory repository is available."
                )

            processor = PassiveMemoryProcessor(
                repository=repository,
            )

            self.passive_worker = PassiveMemoryWorker(
                processor=processor,
                max_queue_size=PASSIVE_MEMORY_QUEUE_SIZE,
            )
            self.passive_worker.privacy = self.privacy

        # Reminder delivery uses a blocking acknowledgment protocol.
        self.notifications = ReminderNotifications()

        self.scheduler = ReminderScheduler(
            repository=self.assistant.memory_tools.repository,
            on_reminder=self.notifications.request,
        )

        # Local WAV files.
        self.audio_directory = Path(os.getenv("NOVA_AUDIO_DIRECTORY", "data/audio"))
        self.audio_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._temporary_audio = TemporaryAudio(self.audio_directory)
        self.input_path = self._temporary_audio.path("input.wav")
        self.output_path = self._temporary_audio.path("response.wav")
        self.reminder_output_path = self._temporary_audio.path("reminder.wav")

    @property
    def interruption_enabled(self):
        return self.__dict__.get("experimental_interruption", False)

    @property
    def response_control(self):
        if "_response_control" not in self.__dict__:
            self._response_control = ResponseControl()
        return self._response_control

    def request_interruption(self, expected=None):
        if not self.interruption_enabled or not self.response_control.interrupt(expected):
            return False
        self.activation_controller.reset()
        if not self.privacy.muted and not self.__dict__.get("_closed", False):
            self.set_state(AssistantState.INTERRUPTED)
        print("[INTERRUPTION] Response cancelled; committed operations preserved.", flush=True)
        return True

    def _start_stop_monitor(self, token):
        if token is None or not self.__dict__.get("spoken_interruption", False):
            return
        check_cancel(token.cancel)
        if self.audio_gate.media_lock.locked() and not self.audio_gate.playback_pending:
            return
        if "_stop_monitor" not in self.__dict__:
            self._stop_monitor = StopMonitor(
                self.response_control, self.privacy, self.request_interruption,
                device=NOVA_INPUT_DEVICE, stt_timeout=NOVA_INTERRUPT_STT_TIMEOUT,
            )
        self._stop_monitor.start(token)

    @contextmanager
    def response_scope(self):
        if not self.interruption_enabled:
            yield None
            return
        token = self.response_control.current
        owner = token is None or current_cancel() is not token.cancel
        if owner:
            token = self.response_control.begin()
        try:
            if self.privacy.muted or self.stop_event.is_set():
                token.cancel.set()
            with cancellation_scope(token.cancel):
                yield token
                check_cancel()
        except BaseException:
            token.cancel.set()
            raise
        finally:
            if owner:
                monitor = self.__dict__.get("_stop_monitor")
                if monitor is not None and monitor.token is token:
                    while not monitor.stop(timeout=3):
                        print("[INTERRUPTION] Waiting for microphone monitor to close.", flush=True)
                self.response_control.finish(token)
                if token.cancel.is_set() and not self.privacy.muted and not self.__dict__.get("_closed", False):
                    self.set_state(AssistantState.INTERRUPTED)

    def _cleanup_audio(self, path):
        owner = self.__dict__.get("_temporary_audio")
        if owner is not None:
            owner.cleanup(path)

    @property
    def stop_event(self):
        # Transcript-only injected instances use the public dispatch API without
        # initializing the microphone loop, just as privacy/audio guards do.
        if "_stop_event" not in self.__dict__:
            self._stop_event = Event()
        return self._stop_event

    @stop_event.setter
    def stop_event(self, value):
        self._stop_event = value

    @property
    def audio_gate(self):
        if "_audio_gate" not in self.__dict__:
            self._audio_gate = HalfDuplexAudio()
        return self._audio_gate

    @property
    def privacy(self):
        # Older injected test/application instances can initialize lazily.
        if "_privacy" not in self.__dict__:
            self._privacy = SoftwareMute()
        return self._privacy

    def set_muted(self, muted: bool) -> None:
        with self.privacy.lock:
            if self.privacy.set_muted(muted):
                self.activation_controller.reset()
                shutting_down = self.interruption_enabled and (
                    self.__dict__.get("_closed", False)
                    or self.__dict__.get("state") == AssistantState.SHUTTING_DOWN
                )
                if not shutting_down:
                    self.set_state(AssistantState.MUTED if muted else AssistantState.IDLE)
                print("[PRIVACY] Software microphone mute: " + ("ON" if muted else "OFF"), flush=True)
                if muted:
                    self.request_interruption()

    def toggle_mute(self) -> None:
        with self.privacy.lock:
            self.set_muted(not self.privacy.muted)

    def set_state(self, state: AssistantState) -> None:
        """Update and display Nova's current state."""

        with self.privacy.lock:
            cancel = current_cancel()
            if (cancel is not None and cancel.is_set()
                    and state not in {AssistantState.INTERRUPTED, AssistantState.MUTED,
                                      AssistantState.SHUTTING_DOWN, AssistantState.IDLE}):
                raise ResponseInterrupted()
            if state not in {AssistantState.IDLE, AssistantState.SHUTTING_DOWN} and self.privacy.muted:
                state = AssistantState.MUTED
            if self.interruption_enabled:
                validate_transition(self.__dict__.get("state", AssistantState.IDLE), state)
            self.state = state
            print(f"\n[STATE] {state.name}", flush=True)

    def speak(
        self,
        text: str,
        output_path: Path | None = None,
    ) -> None:
        """Synthesize and play speech through Piper."""

        if not isinstance(text, str) or not text.strip():
            return
        if self.__dict__.get("_closed", False):
            return

        if output_path is None:
            output_path = self.output_path

        try:
            with self.response_scope() as token:
                if self.state == AssistantState.INTERRUPTED:
                    self.set_state(AssistantState.PROCESSING)
                self.set_state(AssistantState.SPEAKING)
                if token is not None:
                    self.response_control.set_reference(token, model_text(text))
                with self.audio_gate.playback():
                    self._start_stop_monitor(token)
                    event("playback_guard_enter")
                    try:
                        with stage("synthesis"):
                            if token is None:
                                self.tts.synthesize(model_text(text), output_path)
                            else:
                                self.tts.synthesize(model_text(text), output_path, cancel_event=token.cancel)
                            check_cancel()
                        with stage("playback"):
                            if token is None:
                                self.player.play(output_path)
                            else:
                                self.player.play(output_path, cancel_event=token.cancel)
                    finally:
                        # Keep normal capture closed through the acoustic tail.
                        time.sleep(0.3)
                        event("playback_guard_exit")
        finally:
            self._cleanup_audio(output_path)

    def deliver_pending_reminders(self) -> None:
        """Announce reminders and acknowledge success or failure."""

        while not self.stop_event.is_set():
            notification = self.notifications.get_pending()

            if notification is None:
                break

            reminder = notification.reminder
            error = None

            try:
                print(
                    "[REMINDER] Delivering notification.",
                    flush=True,
                )

                self.speak(
                    f"Reminder: {reminder.message}",
                    self.reminder_output_path,
                )

            except Exception as exc:
                error = exc

                print(
                    f"[REMINDER ERROR] {type(exc).__name__}",
                    flush=True,
                )

            finally:
                # Scheduler marks the reminder completed only
                # after a successful acknowledgment.
                self.notifications.acknowledge(
                    notification,
                    error=error,
                )

    @timed("voice_dispatch")
    def handle_transcript(
        self,
        transcript: str,
        captured_at: datetime | None = None,
        generation: int | None = None,
        audio_generation: int | None = None,
        accepted_shutdown: bool = False,
    ) -> None:
        """Route speech through wake activation or passive memory."""

        if self.__dict__.get("_closed", False) or (self.stop_event.is_set() and not accepted_shutdown):
            return
        if audio_generation is None:
            audio_generation = self.audio_gate.generation
        if not self.audio_gate.valid(audio_generation):
            event("stale_recording_discarded")
            return

        if generation is None:
            generation, _ = self.privacy.snapshot()
        with self.privacy.guard(generation) as allowed:
            if not allowed:
                return
        if not is_usable_transcript(transcript):
            print(
                "[STT] Ignored invalid or non-speech transcription.",
                flush=True,
            )
            return

        if captured_at is None:
            captured_at = datetime.now().astimezone()

        transcript = strip_audio_captions(transcript)
        with self.privacy.guard(generation) as allowed:
            if not allowed:
                return
            decision = self.activation_controller.route(transcript, now=captured_at)

        # Wake phrase detected, but no command was included.
        if decision.action == ActivationController.WAITING:
            print(
                "[WAKE] Nova activated. "
                "Waiting for your command...",
                flush=True,
            )
            return

        # Background speech is never answered aloud.
        if decision.action == ActivationController.PASSIVE:
            if self.passive_worker is None:
                return

            with self.privacy.guard(generation) as allowed:
                if not allowed:
                    return
                if issubclass(type(self.passive_worker), PassiveMemoryWorker):
                    queued = self.passive_worker.submit(transcript, captured_at=captured_at)
                else:
                    queued = self.passive_worker.submit(transcript)

            if queued:
                print(
                    "[MEMORY] Background speech queued "
                    "for processing.",
                    flush=True,
                )
            else:
                print(
                    "[MEMORY] Background speech was not queued.",
                    flush=True,
                )

            return

        if decision.action != ActivationController.ACTIVE:
            return

        command = decision.text.strip()

        if not command:
            return

        if self.interruption_enabled and command.lower().strip(" .!?") == "stop":
            self.request_interruption()
            return

        # Admission is serialized with mute; admitted commands may finish.
        with self.privacy.guard(generation) as allowed:
            if not allowed:
                return

        try:
            with self.response_scope() as token:
                self._start_stop_monitor(token)
                self._respond_command(command, generation, audio_generation, accepted_shutdown)
        except ResponseInterrupted:
            return

    def _respond_command(self, command, generation, audio_generation, accepted_shutdown):
        check_cancel()
        self.set_state(AssistantState.PROCESSING)

        try:
            with stage("processing"):
                response = self.assistant.process(command)
                check_cancel()

        except ResponseInterrupted:
            raise
        except Exception as exc:
            with self.privacy.guard(generation) as allowed:
                if not allowed:
                    return
            print(
                f"[ASSISTANT ERROR] {type(exc).__name__}",
                flush=True,
            )
            return

        if not response:
            return
        if not self.audio_gate.valid(audio_generation) or (self.stop_event.is_set() and not accepted_shutdown):
            return

        with self.privacy.guard(generation) as allowed:
            if not allowed:
                return
            print("[RESPONSE] Playing assistant response.", flush=True)

        try:
            self.speak(
                response,
                self.output_path,
            )

        except ResponseInterrupted:
            raise
        except Exception as exc:
            self.audio_recovery.handle_failure(
                "Audio output",
                exc,
                self.stop_event,
            )

    def runtime_health(self):
        worker = self.passive_worker
        monitor = self.__dict__.get("_stop_monitor")
        busy_since = getattr(worker, "busy_since", None) if worker else None
        return {
            "audio_queue_depth": self.recorder.queue_depth,
            "stop_audio_queue_depth": monitor.recorder.queue_depth if monitor else 0,
            "passive_queue_depth": worker.queue.qsize() if worker else 0,
            "passive_busy_seconds": max(0., time.monotonic() - busy_since) if busy_since is not None else 0,
            "passive_worker_alive": int(bool(worker and worker.thread and worker.thread.is_alive())),
            "scheduler_alive": int(self.scheduler.is_running),
            "notification_queue_depth": self.notifications.pending.qsize(),
        }

    @observed_runtime
    def run(self) -> None:
        """Start Nova's continuous voice-processing loop."""

        print(
            "Nova - Offline Always-On AI Companion",
            flush=True,
        )
        print(
            "Say 'Nova' to activate. "
            "Press Ctrl+C to stop.",
            flush=True,
        )
        print(
            "[PRIVACY] Passive memory: "
            + (
                "ENABLED"
                if self.passive_worker is not None
                else "DISABLED"
            ),
            flush=True,
        )
        if self.interruption_enabled:
            print("[EXPERIMENTAL] Press S to interrupt a response. Spoken stop monitoring: "
                  + ("ON (no acoustic echo cancellation)" if self.spoken_interruption else "OFF"), flush=True)

        try:
            print("[PRIVACY] Software microphone mute: " + ("ON" if self.privacy.muted else "OFF"), flush=True)
            if self.passive_worker is not None:
                self.passive_worker.privacy = self.privacy
                self.passive_worker.start()

            self.scheduler.start()

            while not self.stop_event.is_set():
                # Announce reminders before the next recording.
                self.deliver_pending_reminders()

                if self.stop_event.is_set():
                    break

                if self.privacy.muted:
                    if self.state != AssistantState.MUTED:
                        self.set_state(AssistantState.MUTED)
                    self.stop_event.wait(0.05)
                    continue
                try:
                    generation, _ = self.privacy.snapshot()
                    self.recorder.privacy = self.privacy
                    self.set_state(AssistantState.LISTENING)

                    try:
                        with self.audio_gate.capture(self.stop_event) as capture:
                            if capture is None:
                                continue
                            self.recorder.playback_cancel = capture.cancel
                            with stage("capture"):
                                audio_path = self.recorder.record_utterance(
                                    self.input_path,
                                    self.stop_event,
                                    interrupt_event=self.notifications.interrupt,
                                )

                    except Exception as exc:
                        self.audio_recovery.handle_failure(
                            "Microphone",
                            exc,
                            self.stop_event,
                        )
                        continue

                    # A reminder can interrupt microphone capture.
                    if self.notifications.interrupt.is_set():
                        self.deliver_pending_reminders()
                        continue

                    if audio_path is None:
                        continue

                    # Finish processing a completed recording even
                    # when shutdown was requested during recording.
                    self.process_recording(
                        audio_path, generation=generation,
                        captured_at=datetime.now().astimezone(),
                        audio_generation=capture.generation, accepted=True,
                    )

                    self.deliver_pending_reminders()

                finally:
                    self._cleanup_audio(self.input_path)

        except KeyboardInterrupt:
            print(
                "\nShutdown requested.",
                flush=True,
            )

        finally:
            if self.interruption_enabled:
                self.request_interruption()
                self.set_state(AssistantState.SHUTTING_DOWN)
            self._closed = True
            self.stop_event.set()
            self.activation_controller.reset()

            # Release scheduler waiters before joining its thread.
            self.notifications.close()

            scheduler_stopped = self.scheduler.stop(
                timeout=5.0
            )

            if not scheduler_stopped:
                print(
                    "[WARNING] Reminder scheduler did not stop "
                    "within the timeout.",
                    flush=True,
                )

            if self.passive_worker is not None:
                worker_stopped = self.passive_worker.stop(
                    timeout=5.0
                )

                if not worker_stopped:
                    print(
                        "[MEMORY] Finishing accepted background speech "
                        "before shutdown...",
                        flush=True,
                    )
                    while not worker_stopped:
                        worker_stopped = self.passive_worker.stop(timeout=5.0)

            owner = self.__dict__.get("_temporary_audio")
            if owner is not None:
                owner.close()
            self.set_state(AssistantState.IDLE)

            print(
                "Nova stopped.",
                flush=True,
            )

    @timed("voice_response")
    def process_recording(self, audio_path: Path, generation: int | None = None,
                          captured_at: datetime | None = None, audio_generation: int | None = None,
                          accepted: bool = False) -> None:
        try:
            with self.response_scope():
                self._process_recording(audio_path, generation, captured_at, audio_generation, accepted)
        except ResponseInterrupted:
            return
        finally:
            self._cleanup_audio(audio_path)

    def _process_recording(self, audio_path: Path, generation: int | None = None,
                           captured_at: datetime | None = None, audio_generation: int | None = None,
                           accepted: bool = False) -> None:
        """Measure completed recording -> STT -> dispatch -> playback.

        This excludes time waiting for speech and recording the utterance.
        Passive dispatch completes on queue submission, before extraction.
        """
        if self.__dict__.get("_closed", False) or (self.stop_event.is_set() and not accepted):
            event("stale_recording_discarded")
            return
        accepted_shutdown = accepted and self.stop_event.is_set()
        if audio_generation is None:
            audio_generation = self.audio_gate.generation
        if not self.audio_gate.valid(audio_generation):
            event("stale_recording_discarded")
            return
        if generation is None:
            generation, _ = self.privacy.snapshot()
        with self.privacy.guard(generation) as allowed:
            if not allowed:
                return
        captured_at = captured_at or datetime.now().astimezone()
        self.set_state(AssistantState.PROCESSING)
        try:
            with stage("transcription"):
                cancel = current_cancel()
                transcript = (self.stt.transcribe(audio_path) if cancel is None
                              else self.stt.transcribe(audio_path, cancel_event=cancel))
                check_cancel()
        except ResponseInterrupted:
            raise
        except Exception as exc:
            with self.privacy.guard(generation) as allowed:
                if not allowed:
                    return
            self.audio_recovery.handle_failure(
                "Whisper STT", exc, self.stop_event,
            )
            return
        if (self.stop_event.is_set() and not accepted_shutdown) or not self.audio_gate.valid(audio_generation):
            event("stale_recording_discarded")
            return
        with self.privacy.guard(generation) as allowed:
            if not allowed:
                return
        try:
            self.handle_transcript(transcript, captured_at=captured_at, generation=generation,
                                   audio_generation=audio_generation, accepted_shutdown=accepted_shutdown)
        except Exception as exc:
            print(f"[VOICE PIPELINE ERROR] {type(exc).__name__}", flush=True)


if __name__ == "__main__":
    if os.getenv("NOVA_PERFORMANCE_LOG", "false").lower() in {"1", "true", "yes", "on"}:
        enable_performance_logging()
    app = AlwaysOnAssistant()
    controller = WindowsMuteHotkey if os.name == "nt" else PosixMuteConsole
    controls = {} if os.name == "nt" else {"on_unavailable": lambda: app.set_muted(True)}
    keys = controller(app.toggle_mute, interrupt=app.request_interruption if app.interruption_enabled else None, **controls)
    print("[PRIVACY] " + ("Press M" if os.name == "nt" else "Type M then Enter")
          + " in this console to toggle software microphone mute.", flush=True)
    keys.start()
    try:
        app.run()
    finally:
        keys.stop()
