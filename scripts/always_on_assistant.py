
from pathlib import Path
from threading import Event
import time

from offline_ai_companion.audio.continuous_recorder import (
    ContinuousRecorder,
)
from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.audio.recovery import AudioRecovery
from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.state import AssistantState
from offline_ai_companion.scheduler.reminder_scheduler import (
    ReminderScheduler,
)
from offline_ai_companion.scheduler.reminder_notifications import (
    ReminderNotifications,
)
from offline_ai_companion.stt.transcript_filter import (
    is_invalid_transcript,
)
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.tts.piper import PiperTTS


class AlwaysOnAssistant:
    """Always-on offline voice assistant."""

    def __init__(self) -> None:
        self.recorder = ContinuousRecorder()
        self.player = AudioPlayer()
        self.stt = WhisperSTT()
        self.assistant = Assistant()
        self.tts = PiperTTS()

        self.state = AssistantState.IDLE
        self.stop_event = Event()

        self.audio_recovery = AudioRecovery(
            retry_delay=2.0
        )

        self.notifications = ReminderNotifications()

        self.scheduler = ReminderScheduler(
            repository=self.assistant.memory_tools.repository,
            on_reminder=self.notifications.request,
            interval_seconds=1.0,
        )

        self.input_path = Path(
            "sample-data/audio/always_on_input.wav"
        )
        self.output_path = Path(
            "sample-data/audio/always_on_response.wav"
        )
        self.reminder_output_path = Path(
            "sample-data/audio/reminder_response.wav"
        )

    def set_state(self, state: AssistantState) -> None:
        self.state = state
        print(f"\n[STATE] {state.value.upper()}")

    def speak(self, text: str, output_path: Path) -> None:
        self.set_state(AssistantState.SPEAKING)

        self.tts.synthesize(
            text,
            output_path,
        )

        self.player.play(output_path)

        time.sleep(0.3)

    def deliver_pending_reminders(self) -> None:
        """Deliver queued reminders on the main audio thread."""

        while not self.stop_event.is_set():
            notification = self.notifications.get_pending()

            if notification is None:
                return

            reminder = notification.reminder
            error = None

            try:
                print(
                    f"\n[REMINDER] {reminder.message}"
                )

                self.speak(
                    f"Reminder: {reminder.message}",
                    self.reminder_output_path,
                )

            except Exception as exc:
                error = exc

                print(
                    f"Reminder playback failed: {exc}"
                )

            finally:
                self.notifications.acknowledge(
                    notification,
                    error=error,
                )

    def run(self) -> None:
        print(
            "Offline AI Companion - Always-On Mode"
        )
        print(
            "Speak naturally. Press Ctrl+C to stop."
        )

        self.scheduler.start()

        try:
            while not self.stop_event.is_set():

                self.deliver_pending_reminders()

                if self.stop_event.is_set():
                    break

                self.set_state(
                    AssistantState.LISTENING
                )

                # Microphone recovery.
                try:
                    audio_path = (
                        self.recorder.record_utterance(
                            self.input_path,
                            self.stop_event,
                            interrupt_event=(
                                self.notifications.interrupt
                            ),
                        )
                    )

                except (
                    RuntimeError,
                    ValueError,
                    OSError,
                ) as exc:
                    self.audio_recovery.handle_failure(
                        "Microphone",
                        exc,
                        self.stop_event,
                    )
                    continue

                # Reminder interrupted microphone recording.
                if self.notifications.interrupt.is_set():
                    self.deliver_pending_reminders()
                    continue

                if audio_path is None:
                    continue

                self.set_state(
                    AssistantState.PROCESSING
                )

                # Speech-to-text recovery.
                try:
                    transcript = self.stt.transcribe(
                        audio_path
                    )

                except (
                    RuntimeError,
                    ValueError,
                    OSError,
                    FileNotFoundError,
                ) as exc:
                    self.audio_recovery.handle_failure(
                        "Whisper STT",
                        exc,
                        self.stop_event,
                    )
                    continue

                print(f"You: {transcript}")

                if is_invalid_transcript(transcript):
                    print(
                        "[INFO] Ignoring empty "
                        "or non-speech audio."
                    )
                    continue

                # Assistant processing.
                try:
                    response = self.assistant.process(
                        transcript
                    )

                except (
                    RuntimeError,
                    ValueError,
                    OSError,
                ) as exc:
                    print(
                        f"[PROCESSING ERROR] {exc}"
                    )
                    continue

                print(f"Assistant: {response}")

                # Speech synthesis and playback recovery.
                try:
                    self.speak(
                        response,
                        self.output_path,
                    )

                except (
                    RuntimeError,
                    ValueError,
                    OSError,
                    FileNotFoundError,
                ) as exc:
                    print(
                        f"[SPEECH ERROR] {exc}"
                    )
                    print(
                        "[INFO] Response remains "
                        "available in the console."
                    )

                # Deliver reminders that became due
                # during processing or speaking.
                self.deliver_pending_reminders()

        except KeyboardInterrupt:
            print("\nShutdown requested.")

        finally:
            self.stop_event.set()

            # Release pending reminder acknowledgments.
            self.notifications.close()

            # Stop background reminder scheduler.
            scheduler_stopped = (
                self.scheduler.stop(
                    timeout=5.0
                )
            )

            if not scheduler_stopped:
                print(
                    "[WARNING] Reminder scheduler "
                    "did not terminate within "
                    "the shutdown timeout."
                )

            self.set_state(
                AssistantState.IDLE
            )

            print("Assistant stopped.")


if __name__ == "__main__":
    AlwaysOnAssistant().run()
