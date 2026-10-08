
from pathlib import Path
from threading import Event

from offline_ai_companion.audio.continuous_recorder import (
    ContinuousRecorder,
)
from offline_ai_companion.stt.whisper import WhisperSTT


def main() -> None:
    recorder = ContinuousRecorder()
    stt = WhisperSTT()
    stop_event = Event()

    audio_path = Path(
        "sample-data/audio/automatic_speech.wav"
    )

    print("Listening automatically...")
    print("Speak normally, then stop talking.")
    print("Press Ctrl+C to cancel.\n")

    try:
        result = recorder.record_utterance(
            audio_path,
            stop_event,
        )

        if result is None:
            print("Recording cancelled.")
            return

        print("Speech detected and recorded.")
        print("Transcribing...")

        transcript = stt.transcribe(result)

        print(f"\nYou said: {transcript}")

    except KeyboardInterrupt:
        stop_event.set()
        print("\nStopped.")


if __name__ == "__main__":
    main()
