
from pathlib import Path

from offline_ai_companion.audio.recorder import AudioRecorder
from offline_ai_companion.stt.whisper import WhisperSTT
from offline_ai_companion.llm.ollama import OllamaLLM


def main() -> None:
    audio_path = Path(
        "sample-data/audio/voice_llm_test.wav"
    )

    recorder = AudioRecorder()
    stt = WhisperSTT()
    llm = OllamaLLM()

    input("Press Enter to start recording...")

    recorder.record(
        duration=5,
        output_path=audio_path,
    )

    print("\nTranscribing speech...")
    transcript = stt.transcribe(audio_path)

    print(f"\nYou: {transcript or '[No speech detected]'}")

    if not transcript:
        return

    print("\nGenerating response...")

    try:
        response = llm.generate(transcript)
        print(f"\nAssistant: {response}")
    except RuntimeError as exc:
        print(f"\nError: {exc}")


if __name__ == "__main__":
    main()
