"""Carry original recording time through STT and the real passive worker."""

import json
from datetime import datetime, timedelta, timezone

from .test_always_on_end_to_end import module, pipeline


def test_recording_timestamp_survives_transcription_crossing_midnight(pipeline, monkeypatch):
    app, _, _, llm = pipeline
    captured = datetime(2026, 10, 9, 23, 59,
                        tzinfo=timezone(timedelta(hours=5, minutes=30)))
    clock_value = captured

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock_value if tz is None else clock_value.astimezone(tz)

    # Pin the local timezone too: the test must not depend on the runner's zone.
    class LocalTimestamp(datetime):
        def astimezone(self, tz=None):
            return captured if tz is None else super().astimezone(tz)

    initial = LocalTimestamp.fromisoformat(captured.isoformat())
    clock_value = initial
    monkeypatch.setattr(module, "datetime", Clock)
    speech = "I have a meeting tomorrow."
    llm.generate.return_value = json.dumps({"memories": [{
        "category": "event", "subject": "speaker", "content": "Meeting tomorrow",
        "evidence": speech, "event_time": None,
    }]})
    recordings = 0

    def record(*args, **kwargs):
        nonlocal recordings
        recordings += 1
        if recordings > 1:
            raise KeyboardInterrupt
        return app.input_path

    def transcribe(path):
        nonlocal clock_value
        clock_value = captured + timedelta(minutes=2)
        return speech

    app.recorder.record_utterance.side_effect = record
    app.stt.transcribe.side_effect = transcribe
    app.run()
    memory, = app.assistant.passive_memory_repository.list_memories()
    assert memory.event_time == "2026-10-10"
    assert memory.captured_at == captured.astimezone(timezone.utc).isoformat()
    assert app.passive_worker.queue.unfinished_tasks == 0
    app.player.play.assert_not_called()
