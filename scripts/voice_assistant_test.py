
from pathlib import Path

from offline_ai_companion.audio.recorder import AudioRecorder
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.core.assistant import Assistant


def main() -> None:
    recorder = AudioRecorder()
    stt = WhisperSTT()
    assistant = Assistant()

    audio_path = Path(
        "sample-data/audio/voice_command.wav"
    )

    print("Voice AI Companion")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            input("Press Enter to speak...")

            recorder.record(
                duration=5,
                output_path=audio_path,
            )

            transcript = stt.transcribe(audio_path)
            print(f"\nYou: {transcript}")

            if not transcript:
                print("No speech detected.\n")
                continue

            try:
                response = assistant.process(transcript)
                print(f"Assistant: {response}\n")
            except (ValueError, RuntimeError) as exc:
                print(f"Error: {exc}\n")

    except KeyboardInterrupt:
        print("\nAssistant stopped.")


if __name__ == "__main__":
    main()
