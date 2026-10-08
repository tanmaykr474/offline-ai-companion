
from pathlib import Path

from offline_ai_companion.audio.recorder import AudioRecorder
from offline_ai_companion.stt.whisper import WhisperSTT


def main() -> None:
    audio_path = Path("sample-data/audio/live_speech.wav")

    recorder = AudioRecorder()
    stt = WhisperSTT()

    input("Press Enter to start recording...")

    recorder.record(
        duration=5,
        output_path=audio_path,
    )

    print("Transcribing...")

    transcript = stt.transcribe(audio_path)

    print("\nYou said:")
    print(transcript or "[No speech detected]")


if __name__ == "__main__":
    main()
