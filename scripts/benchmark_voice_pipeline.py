"""Benchmark synthetic observations in an isolated database, never user memory.

Optional local audio tests use installed Piper/Whisper, not microphone/speaker.
"""

import argparse
import contextlib
import io
import json
import logging
import statistics
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.performance import timed
from offline_ai_companion.core.wake_detector import WakeDetector
from offline_ai_companion.llm.ollama import OllamaLLM
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.tools.memory_tools import MemoryTools

SCENARIOS = (
    ("I love playing cricket.", "Nova, what sport do I love playing?", "cricket"),
    ("I was born in Bihar.", "Nova, where was I born?", "bihar"),
    ("I enjoy listening to music.", "Nova, what do I enjoy doing?", "listening to music"),
    ("My favorite food is biryani.", "Nova, what is my favorite food?", "biryani"),
    ("I work as a software developer.", "Nova, what do I do for work?", "software developer"),
)


class NoModel:
    def generate(self, *args, **kwargs):
        raise AssertionError("Deterministic benchmark unexpectedly used a model")

    def extract(self, *args):
        return None


class StageCollector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.samples = {}

    def emit(self, record):
        stage, duration, status = record.args
        self.samples.setdefault(stage, []).append((duration, status))


def benchmark(iterations=20, local_audio=False, ollama=False):
    collector = StageCollector()
    logger = logging.getLogger("nova.performance")
    original_level = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    report = {"synthetic_data_only": True, "physical_devices_verified": False,
              "scope": "Real SQLite/extraction/retrieval; optional local audio models; no playback",
              "iterations": iterations, "local_audio": "not requested", "ollama": "not requested"}
    try:
        with tempfile.TemporaryDirectory(prefix=".nova-benchmark-1266-", dir=Path.cwd()) as temporary:
            directory = Path(temporary)
            facts = MemoryRepository(Database(directory / "benchmark.db"))
            assistant = Assistant(memory_tools=MemoryTools(facts), llm=NoModel(), fact_extractor=NoModel())
            processor = PassiveMemoryProcessor(assistant.passive_memory_repository, NoModel())
            # Silence ordinary diagnostics. Only numeric stage samples are saved.
            with contextlib.redirect_stdout(io.StringIO()):
                for speech, _, _ in SCENARIOS:
                    assert processor.process(speech) == 1
                for _ in range(iterations):
                    for speech, question, expected in SCENARIOS:
                        assert processor.process(speech) == 0
                        assert expected in assistant.process(WakeDetector().detect(question).command).casefold()
            report["stored_observations"] = len(assistant.passive_memory_repository.list_memories())
            if local_audio:
                import numpy as np
                import soundfile as sf
                from offline_ai_companion.stt.whisper import WhisperSTT
                from offline_ai_companion.tts.piper import PiperTTS
                stt, tts = WhisperSTT(), PiperTTS()
                # Independent, empty memory proves passive speech recognition
                # actually feeds storage; seeded text memory cannot mask failures.
                audio_facts = MemoryRepository(Database(directory / "audio-benchmark.db"))
                audio_assistant = Assistant(memory_tools=MemoryTools(audio_facts), llm=NoModel(), fact_extractor=NoModel())
                audio_processor = PassiveMemoryProcessor(audio_assistant.passive_memory_repository, NoModel())
                results = []

                def speech_file(text):
                    source = tts.synthesize(text, directory / "source.wav")
                    samples, rate = sf.read(source, dtype="float32")
                    if samples.ndim > 1:
                        samples = samples.mean(axis=1)
                    converted = np.interp(
                        np.arange(round(len(samples) * 16000 / rate)) * rate / 16000,
                        np.arange(len(samples)), samples,
                    )
                    path = directory / "input.wav"
                    sf.write(path, converted, 16000, subtype="PCM_16")
                    return path

                @timed("voice_response")
                def response_from_file(path, expected):
                    text = stt.transcribe(path)
                    detection = WakeDetector().detect(text)
                    if not detection.activated or not detection.command:
                        return False
                    response = audio_assistant.process(detection.command)
                    tts.synthesize(response, directory / "response.wav")
                    return expected in response.casefold()

                for index, (speech, question, expected) in enumerate(SCENARIOS):
                    try:
                        passive_text = stt.transcribe(speech_file(speech))
                        with contextlib.redirect_stdout(io.StringIO()):
                            saved = audio_processor.process(passive_text)
                        path = speech_file(question)
                        matched = response_from_file(path, expected)
                        results.append({"scenario": index + 1, "passive_saved": saved == 1, "matched": matched})
                    except (OSError, RuntimeError, AssertionError) as exc:
                        # Exception type only: paths, transcript or model output are not logged.
                        results.append({"scenario": index + 1, "error_type": type(exc).__name__})
                report["local_audio"] = results
                report["audio_stored_observations"] = len(audio_assistant.passive_memory_repository.list_memories())
            if ollama:
                client = OllamaLLM(timeout=30, max_retries=0)
                if urlparse(client.host).hostname not in {"localhost", "127.0.0.1", "::1"}:
                    report["ollama"] = "skipped: configured host is not loopback"
                else:
                    try:
                        client.generate("Reply with the word ready.", num_predict=16)
                        report["ollama"] = "local generation completed"
                    except RuntimeError as exc:
                        report["ollama"] = {"error_type": type(exc).__name__}
        report["stages"] = {}
        for stage, samples in collector.samples.items():
            durations = sorted(duration for duration, _ in samples)
            report["stages"][stage] = {
                "count": len(samples), "median_ms": round(statistics.median(durations), 3),
                "p95_ms": round(durations[min(len(durations) - 1, int(0.95 * len(durations)))], 3),
                "max_ms": round(max(durations), 3),
                "raised_errors": sum(status != "ok" for _, status in samples),
            }
        return report
    finally:
        logger.removeHandler(collector)
        logger.setLevel(original_level)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--local-audio", action="store_true")
    parser.add_argument("--ollama", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    report = benchmark(args.iterations, args.local_audio, args.ollama)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
