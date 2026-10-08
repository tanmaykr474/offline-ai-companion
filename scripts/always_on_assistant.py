
from pathlib import Path
from threading import Event
import time

from offline_ai_companion.audio.continuous_recorder import (
    ContinuousRecorder,
)
from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.state import AssistantState
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.tts.piper import PiperTTS


class AlwaysOnAssistant:
    def __init__(self) -> None:
        self.recorder = ContinuousRecorder()
        self.player = AudioPlayer()
        self.stt = WhisperSTT()
        self.assistant = Assistant()
        self.tts = PiperTTS()

        self.state = AssistantState.IDLE
        self.stop_event = Event()

        self.input_path = Path(
            "sample-data/audio/always_on_input.wav"
        )
        self.output_path = Path(
            "sample-data/audio/always_on_response.wav"
        )

    def set_state(self, state: AssistantState) -> None:
        self.state = state
        print(f"\n[STATE] {state.value.upper()}")

    def run(self) -> None:
        print("Offline AI Companion — Always-On Mode")
        print("Speak naturally. Press Ctrl+C to stop.")

        try:
            while not self.stop_event.is_set():
                self.set_state(AssistantState.LISTENING)

                audio_path = self.recorder.record_utterance(
                    self.input_path,
                    self.stop_event,
                )

                if audio_path is None:
                    continue

                self.set_state(AssistantState.PROCESSING)

                transcript = self.stt.transcribe(audio_path)
                print(f"You: {transcript}")

                if not transcript.strip():
                    continue

                try:
                    response = self.assistant.process(transcript)
                    print(f"Assistant: {response}")

                    self.set_state(AssistantState.SPEAKING)

                    self.tts.synthesize(
                        response,
                        self.output_path,
                    )
                    self.player.play(self.output_path)

                    # Small cooldown before reopening the microphone.
                    time.sleep(0.3)

                except (
                    RuntimeError,
                    ValueError,
                    FileNotFoundError,
                ) as exc:
                    print(f"Processing error: {exc}")

        except KeyboardInterrupt:
            print("\nShutdown requested.")

        finally:
            self.stop_event.set()
            self.set_state(AssistantState.IDLE)
            print("Assistant stopped.")


if __name__ == "__main__":
    AlwaysOnAssistant().run()
