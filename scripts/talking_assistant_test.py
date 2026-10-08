
from pathlib import Path

from offline_ai_companion.audio.recorder import AudioRecorder
from offline_ai_companion.audio.player import AudioPlayer
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.tts.piper import PiperTTS


def main() -> None:
    recorder = AudioRecorder()
    player = AudioPlayer()
    stt = WhisperSTT()
    assistant = Assistant()
    tts = PiperTTS()

    input_audio = Path(
        "sample-data/audio/talking_input.wav"
    )

    output_audio = Path(
        "sample-data/audio/talking_response.wav"
    )

    print("Talking AI Companion")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            input("Press Enter to speak...")

            recorder.record(
                duration=5,
                output_path=input_audio,
            )

            print("Transcribing...")
            transcript = stt.transcribe(input_audio)

            print(f"\nYou: {transcript}")

            if not transcript:
                print("No speech detected.\n")
                continue

            try:
                response = assistant.process(transcript)
                print(f"\nAssistant: {response}\n")

                print("Generating speech...")
                tts.synthesize(response, output_audio)

                print("Speaking...")
                player.play(output_audio)

            except (
                ValueError,
                RuntimeError,
                FileNotFoundError,
            ) as exc:
                print(f"Error: {exc}")

    except KeyboardInterrupt:
        print("\nAssistant stopped.")


if __name__ == "__main__":
    main()
