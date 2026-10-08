from pathlib import Path

from offline_ai_companion.audio.recorder import AudioRecorder


def main() -> None:
    output_path = (
        Path("sample-data")
        / "audio"
        / "microphone_test.wav"
    )

    recorder = AudioRecorder()

    recorder.record(
        duration=5,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()