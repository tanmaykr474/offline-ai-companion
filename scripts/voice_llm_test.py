from offline_ai_companion.core.privacy_policy import debug_text

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

    print(f"\nYou: {debug_text(transcript) or '[No speech detected]'}")

    if not transcript:
        return

    print("\nGenerating response...")

    try:
        response = llm.generate(transcript)
        print(f"\nAssistant: {debug_text(response)}")
    except RuntimeError as exc:
        print(f"\nError: {type(exc).__name__}")


if __name__ == "__main__":
    main()
