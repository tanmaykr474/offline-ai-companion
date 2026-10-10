"""Windows orchestration with real memory/routing and mocked device boundaries."""

import importlib.util
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from offline_ai_companion.audio.recovery import AudioRecovery
from offline_ai_companion.core.activation_controller import ActivationController
from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.state import AssistantState
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.passive_worker import PassiveMemoryWorker
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.scheduler.reminder_notifications import ReminderNotifications
from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
from offline_ai_companion.tools.memory_tools import MemoryTools

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "always_on_assistant.py"
spec = importlib.util.spec_from_file_location("nova_e2e", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Integration stage did not finish"
        Event().wait(0.005)


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    # No default database, audio files, physical devices or local servers.
    app = module.AlwaysOnAssistant.__new__(module.AlwaysOnAssistant)
    app.stop_event = Event()
    app.state = AssistantState.IDLE
    app.activation_controller = ActivationController()
    repository = MemoryRepository(Database(tmp_path / "voice.db"))
    llm = Mock()
    llm.generate.return_value = '{"memories": []}'
    extractor = Mock()
    extractor.extract.return_value = None
    app.assistant = Assistant(memory_tools=MemoryTools(repository), llm=llm, fact_extractor=extractor)
    processor = PassiveMemoryProcessor(app.assistant.passive_memory_repository, llm)
    app.passive_worker = PassiveMemoryWorker(processor)
    app.notifications = ReminderNotifications()
    app.scheduler = ReminderScheduler(repository, app.notifications.request, interval_seconds=0.01)
    app.audio_recovery = AudioRecovery(retry_delay=0)
    app.recorder, app.stt, app.tts, app.player = Mock(), Mock(), Mock(), Mock()
    app.input_path = tmp_path / "input.wav"
    app.output_path = tmp_path / "response.wav"
    app.reminder_output_path = tmp_path / "reminder.wav"
    # Avoid only the playback settling delay; Event-based synchronization is real.
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    yield app, repository, processor, llm
    app.stop_event.set()
    app.notifications.close()
    assert app.scheduler.stop(timeout=3)
    assert app.passive_worker.stop(timeout=3)


def scripted_run(app, transcripts, before_record=None):
    calls = []
    texts = iter(transcripts)

    def record(*args, **kwargs):
        index = len(calls)
        calls.append(app.state)
        if before_record:
            before_record(index)
        try:
            text = next(texts)
        except StopIteration:
            raise KeyboardInterrupt
        app.stt.transcribe.return_value = text
        return app.input_path

    app.recorder.record_utterance.side_effect = record
    app.run()
    return calls


@pytest.mark.parametrize("speech,question,value", [
    ("I love playing cricket.", "Nova, what sport do I love playing?", "cricket"),
    ("I was born in Bihar.", "Nova, where was I born?", "Bihar"),
    ("I enjoy listening to music.", "Nova, what do I enjoy doing?", "listening to music"),
    ("My favorite food is biryani.", "Nova, what is my favorite food?", "biryani"),
    ("I work as a software developer.", "Nova, what do I do for work?", "software developer"),
])
def test_passive_recording_to_wake_recall_and_playback(pipeline, speech, question, value):
    app, facts, _, llm = pipeline
    snapshot = []

    def barrier(index):
        if index == 1:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)
            snapshot.extend(app.assistant.passive_memory_repository.list_memories())
            assert len(snapshot) == 1
            assert facts.list_facts() == {}
            app.tts.synthesize.assert_not_called()
            app.player.play.assert_not_called()

    states = scripted_run(app, [speech, question], barrier)
    assert states == [AssistantState.LISTENING] * 3
    response, output = app.tts.synthesize.call_args.args
    assert value in response
    assert "unidentified speaker" in response
    assert output == app.output_path
    app.tts.synthesize.assert_called_once()
    app.player.play.assert_called_once_with(app.output_path)
    assert app.assistant.passive_memory_repository.list_memories() == snapshot
    assert app.state == AssistantState.IDLE
    assert not app.passive_worker.thread.is_alive()
    llm.generate.assert_not_called()


def test_hello_nova_is_active_not_a_passive_memory(pipeline):
    app, _, _, _ = pipeline
    scripted_run(app, ["Hello Nova"])
    app.tts.synthesize.assert_called_once()
    assert app.assistant.passive_memory_repository.list_memories() == []


def test_transcript_display_is_disabled_by_default(pipeline, monkeypatch, capsys):
    monkeypatch.delenv('NOVA_TRANSCRIPT_DEBUG', raising=False)
    pipeline[0].handle_transcript('Nova, hello')
    assert '[STT TRANSCRIPT]' not in capsys.readouterr().out


def test_opt_in_transcript_display_shows_original_stt(pipeline, monkeypatch, capsys):
    monkeypatch.setenv('NOVA_TRANSCRIPT_DEBUG', 'true')
    pipeline[0].handle_transcript('Nova, hello [MUSIC]')
    assert "[STT TRANSCRIPT] 'Nova, hello [MUSIC]'" in capsys.readouterr().out


def test_opt_in_transcript_display_redacts_credentials(pipeline, monkeypatch, capsys):
    monkeypatch.setenv('NOVA_TRANSCRIPT_DEBUG', 'true')
    pipeline[0].handle_transcript('My password is DemoOnly123.')
    output = capsys.readouterr().out
    assert 'DemoOnly123' not in output
    assert '[CREDENTIAL CONTENT OMITTED]' in output


@pytest.mark.parametrize('boundary', ['muted', 'stale', 'shutdown'])
def test_transcript_display_respects_privacy_and_lifecycle(pipeline, monkeypatch, capsys, boundary):
    app = pipeline[0]
    monkeypatch.setenv('NOVA_TRANSCRIPT_DEBUG', 'true')
    generation, _ = app.privacy.snapshot()
    if boundary == 'muted':
        app.set_muted(True)
    elif boundary == 'stale':
        app.set_muted(True)
        app.set_muted(False)
    else:
        app.stop_event.set()
    app.handle_transcript('Nova, private example', generation=generation)
    output = capsys.readouterr().out
    assert '[STT TRANSCRIPT]' not in output
    assert 'private example' not in output


def test_accuracy_duplicates_negation_conflict_unknown_and_fact_priority(pipeline):
    app, facts, _, llm = pipeline
    texts = ["I was born in Bihar.", "I was born in Bihar.",
             "I wasn't born in Kerala.", "I was born in Kerala.",
             "My favorite food is biryani.", "Nova, where was I born?",
             "Nova, what sport do I love playing?", "Nova, what is my favorite food?"]
    snapshots = []
    facts.set_fact("user.favorite_food", "Pizza")

    def barrier(index):
        if index > 0:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)
        if index == 5:
            snapshots.extend(app.assistant.passive_memory_repository.list_memories())
            assert len(snapshots) == 3

    scripted_run(app, texts, barrier)
    answers = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert "conflicting" in answers[0]
    assert "Bihar" in answers[0] and "Kerala" in answers[0]
    assert "don't have" in answers[1]
    assert answers[2] == "Your favorite food is Pizza."
    assert app.assistant.passive_memory_repository.list_memories() == snapshots
    assert facts.list_facts() == {"user.favorite_food": "Pizza"}
    assert len(llm.generate.call_args_list) == 1  # rejected negated transcript


def test_active_command_is_not_blocked_by_passive_extraction(pipeline):
    app, _, processor, _ = pipeline
    entered, release = Event(), Event()
    original = processor.process

    def blocked(text):
        entered.set()
        assert release.wait(3)
        return original(text)

    processor.process = blocked
    app.passive_worker.start()
    try:
        app.handle_transcript("I love playing cricket.")
        assert entered.wait(3)
        # Extraction remains blocked until the active response has played.
        app.handle_transcript("Nova, what is my favorite color?")
        app.player.play.assert_called_once()
        assert not release.is_set()
    finally:
        release.set()
        assert app.passive_worker.stop(timeout=3)
    assert len(app.assistant.passive_memory_repository.list_memories()) == 1


@pytest.mark.parametrize("phase", ["idle", "transcription", "passive_extraction"])
def test_ctrl_c_at_pipeline_stages_drains_and_closes(pipeline, phase):
    app, _, processor, _ = pipeline
    entered, release = Event(), Event()
    original = processor.process

    def processing(text):
        entered.set()
        assert release.wait(3)
        return original(text)

    if phase == "passive_extraction":
        processor.process = processing
        real_stop = app.passive_worker.stop

        def shutdown(timeout):
            # At the moment shutdown begins, accepted extraction is in flight.
            assert entered.is_set()
            release.set()
            return real_stop(timeout)

        app.passive_worker.stop = shutdown

    records = 0

    def record(*args, **kwargs):
        nonlocal records
        records += 1
        if phase == "idle":
            raise KeyboardInterrupt
        if records > 1:
            assert entered.wait(3)
            raise KeyboardInterrupt
        return app.input_path

    app.recorder.record_utterance.side_effect = record
    app.stt.transcribe.side_effect = KeyboardInterrupt if phase == "transcription" else None
    app.stt.transcribe.return_value = "I love playing cricket."
    try:
        app.run()
    finally:
        release.set()
    assert app.stop_event.is_set()
    assert app.notifications.shutdown.is_set()
    assert not app.passive_worker.thread.is_alive()
    assert app.passive_worker.queue.unfinished_tasks == 0
    assert app.state == AssistantState.IDLE
    expected = 1 if phase == "passive_extraction" else 0
    assert len(app.assistant.passive_memory_repository.list_memories()) == expected
    app.player.play.assert_not_called()


def test_sqlite_restart_and_repeated_worker_cycles(pipeline):
    app, facts, _, llm = pipeline
    for _ in range(3):
        app.passive_worker.start()
        assert app.passive_worker.submit("I was born in Bihar.")
        assert app.passive_worker.stop(timeout=3)
        assert app.passive_worker.queue.unfinished_tasks == 0
    restarted_facts = MemoryRepository(Database(facts.database.path))
    restarted = Assistant(memory_tools=MemoryTools(restarted_facts), llm=llm)
    assert "Bihar" in restarted.process("Where was I born?")
    assert len(restarted.passive_memory_repository.list_memories()) == 1


def test_ollama_timeout_does_not_poison_next_active_command(pipeline):
    app, _, _, llm = pipeline
    llm.generate.side_effect = [RuntimeError("Ollama request timed out"), "A compiler translates code."]
    scripted_run(app, ["Nova, explain a compiler", "Nova, explain a compiler"])
    answers = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert "trouble with my local language model" in answers[0]
    assert answers[1] == "A compiler translates code."
    assert app.player.play.call_count == 2


@pytest.mark.parametrize("component", ["microphone", "speaker", "transcription"])
def test_audio_failure_recovers_on_next_loop(pipeline, component):
    app, _, _, _ = pipeline
    app.stt.transcribe.return_value = "Nova, where was I born?"
    attempts = 0

    def record(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > 2:
            raise KeyboardInterrupt
        if component == "microphone" and attempts == 1:
            raise RuntimeError("Microphone unavailable")
        return app.input_path

    app.recorder.record_utterance.side_effect = record
    if component == "speaker":
        app.player.play.side_effect = [RuntimeError("Speaker unavailable"), None]
    if component == "transcription":
        app.stt.transcribe.side_effect = [RuntimeError("Whisper timed out"), "Nova, where was I born?"]
    app.run()
    assert attempts == 3
    expected = 2 if component == "speaker" else 1
    assert app.player.play.call_count == expected
    assert app.state == AssistantState.IDLE


def test_due_reminder_interrupts_recording_then_listening_resumes(pipeline):
    app, facts, _, _ = pipeline
    records = 0

    def record(*args, **kwargs):
        nonlocal records
        records += 1
        if records == 1:
            facts.add_reminder("Drink water", datetime.now(timezone.utc) - timedelta(seconds=1))
            assert kwargs["interrupt_event"] is app.notifications.interrupt
            assert app.notifications.interrupt.wait(3)
            return None
        assert app.state == AssistantState.LISTENING
        assert app.player.play.call_count == 1
        wait_until(lambda: facts.list_reminders()[0].is_completed)
        raise KeyboardInterrupt

    app.recorder.record_utterance.side_effect = record
    app.run()
    app.stt.transcribe.assert_not_called()
    app.tts.synthesize.assert_called_once_with("Reminder: Drink water", app.reminder_output_path)
    assert facts.list_reminders()[0].is_completed


def test_unsupported_model_claim_never_becomes_a_spoken_memory(pipeline):
    import json
    app, _, _, llm = pipeline
    llm.generate.return_value = json.dumps({"memories": [{
        "category": "fact", "subject": "speaker",
        "content": "Birthplace is Bihar", "evidence": "I watched the match",
        "event_time": None,
    }]})

    def barrier(index):
        if index == 1:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)

    scripted_run(app, ["I watched the match", "Nova, where was I born?"], barrier)
    assert app.assistant.passive_memory_repository.list_memories() == []
    response = app.tts.synthesize.call_args.args[0]
    assert "don't have" in response
    assert "Bihar" not in response


def test_passive_disablement_prevents_storage_but_preserves_wake_commands(pipeline):
    app, _, _, _ = pipeline
    worker = app.passive_worker
    app.passive_worker = None
    try:
        scripted_run(app, ["I was born in Bihar.", "Nova, where was I born?"])
        assert app.assistant.passive_memory_repository.list_memories() == []
        assert "don't have" in app.tts.synthesize.call_args.args[0]
        app.player.play.assert_called_once()
    finally:
        app.passive_worker = worker


def test_fresh_application_start_stop_cycles_share_only_persistent_memory(pipeline, tmp_path, monkeypatch):
    _, facts, _, llm = pipeline
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "PASSIVE_MEMORY_ENABLED", True)
    monkeypatch.setattr(module, "Assistant", lambda: Assistant(
        memory_tools=MemoryTools(MemoryRepository(Database(facts.database.path))),
        llm=llm, fact_extractor=Mock(extract=Mock(return_value=None)),
    ))
    monkeypatch.setattr(module, "ContinuousRecorder", Mock)
    monkeypatch.setattr(module, "WhisperSTT", Mock)
    monkeypatch.setattr(module, "PiperTTS", Mock)
    monkeypatch.setattr(module, "AudioPlayer", Mock)

    for cycle in range(3):
        app = module.AlwaysOnAssistant()
        app.passive_worker.processor.llm = llm

        def barrier(index):
            if cycle == 0 and index == 1:
                wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)

        try:
            transcripts = ["Nova, where was I born?"]
            if cycle == 0:
                transcripts.insert(0, "I was born in Bihar.")
            scripted_run(app, transcripts, barrier)
            assert "Bihar" in app.tts.synthesize.call_args.args[0]
            assert app.stop_event.is_set()
            assert app.notifications.shutdown.is_set()
            assert not app.passive_worker.thread.is_alive()
            assert len(app.assistant.passive_memory_repository.list_memories()) == 1
        finally:
            app.notifications.close()
            assert app.scheduler.stop(timeout=3)
            assert app.passive_worker.stop(timeout=3)


def test_orchestration_timings_exclude_transcripts_and_responses(pipeline, caplog):
    import logging
    app, _, _, _ = pipeline
    caplog.set_level(logging.INFO, logger="nova.performance")

    def barrier(index):
        if index == 1:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)

    scripted_run(app, ["I was born in PrivateTown.", "Nova, where was I born?"], barrier)
    records = [r.getMessage() for r in caplog.records if r.name == "nova.performance"]
    for stage in ("passive_extraction", "memory_retrieval", "voice_dispatch", "voice_response"):
        assert any(f"stage={stage} " in message for message in records)
    assert all("PrivateTown" not in message and "born" not in message for message in records)
