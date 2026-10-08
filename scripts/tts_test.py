
from pathlib import Path

from offline_ai_companion.tts.piper import PiperTTS
from offline_ai_companion.audio.player import AudioPlayer


def main() -> None:
    tts = PiperTTS()
    player = AudioPlayer()

    output_path = Path(
        "sample-data/audio/tts_test.wav"
    )

    print("Generating speech...")

    tts.synthesize(
        "Hello! I am your personal offline AI companion.",
        output_path,
    )

    print("Playing speech...")
    player.play(output_path)

    print("TTS test completed.")


if __name__ == "__main__":
    main()
