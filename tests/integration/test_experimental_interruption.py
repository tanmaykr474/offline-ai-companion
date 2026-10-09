from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from .test_always_on_end_to_end import pipeline, module, scripted_run
from offline_ai_companion.core.cancellation import ResponseInterrupted, check_cancel
from offline_ai_companion.core.state import AssistantState
from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
from offline_ai_companion.audio.stop_monitor import StopMonitor
from offline_ai_companion.audio.temporary import TemporaryAudio


def enable(app):
    app.experimental_interruption = True
    app.spoken_interruption = False


def test_playback_interrupt_then_new_command_preserves_committed_task(pipeline):
    app, repository, _, _ = pipeline
    enable(app)
    def interrupt(*args, **kwargs):
        assert app.request_interruption()
        assert not app.request_interruption()
        check_cancel(kwargs["cancel_event"])
    app.player.play.side_effect = interrupt
    app.handle_transcript("Nova, add a task to finish my project")
    assert len(repository.list_tasks()) == 1
    assert app.state == AssistantState.INTERRUPTED
    assert app.response_control.current is None
    app.audio_recovery.handle_failure = Mock()
    app.player.play.side_effect = None
    app.handle_transcript("Nova, show my pending tasks")
    assert "project" in app.tts.synthesize.call_args.args[0]
    assert app.player.play.call_count == 2
    assert len(repository.list_tasks()) == 1
    app.audio_recovery.handle_failure.assert_not_called()


@pytest.mark.parametrize("boundary", ["processing", "synthesis", "playback"])
def test_mute_cancels_response_and_unmute_allows_next_command(pipeline, boundary):
    app, _, _, _ = pipeline
    enable(app)
    def cancel(*args, **kwargs):
        app.set_muted(True)
        return "private response"
    target = {"processing": app.assistant, "synthesis": app.tts, "playback": app.player}[boundary]
    attribute = {"processing": "process", "synthesis": "synthesize", "playback": "play"}[boundary]
    original = getattr(target, attribute)
    setattr(target, attribute, Mock(side_effect=cancel))
    app.handle_transcript("Nova, show my pending tasks")
    assert app.state == AssistantState.MUTED and app.response_control.current is None
    if boundary != "playback":
        app.player.play.assert_not_called()
    setattr(target, attribute, original)
    app.set_muted(False)
    app.handle_transcript("Nova, show my pending tasks")
    assert app.player.play.called


def test_transcription_interrupted_before_any_memory_or_command(pipeline):
    app, repository, _, _ = pipeline
    enable(app)
    def transcript(*args, **kwargs):
        app.request_interruption()
        return "Nova, add a task to finish the report"
    app.stt.transcribe.side_effect = transcript
    app.process_recording(app.input_path)
    assert repository.list_tasks() == []
    assert app.passive_worker.queue.empty()
    app.tts.synthesize.assert_not_called()


def test_cancelled_model_result_not_spoken_and_thread_rejoins(pipeline):
    app, _, _, _ = pipeline
    enable(app)
    entered, release = Event(), Event()
    def process(command):
        entered.set()
        assert release.wait(3)
        return "late model result"
    app.assistant.process = process
    thread = Thread(target=app.handle_transcript, args=("Nova, tell me a story",))
    thread.start()
    assert entered.wait(3)
    assert app.request_interruption()
    release.set()
    thread.join(3)
    assert not thread.is_alive()
    app.player.play.assert_not_called()
    assert app.response_control.current is None


def test_shutdown_during_playback_closes_scope_and_drains_accepted_work(pipeline):
    app, _, _, _ = pipeline
    enable(app)
    app.passive_worker.start()
    assert app.passive_worker.submit("I love playing cricket.")
    def shutdown(*args, **kwargs):
        app.stop_event.set()
        app.request_interruption()
        check_cancel(kwargs["cancel_event"])
    app.player.play.side_effect = shutdown
    scripted_run(app, ["Nova, show my pending tasks"])
    assert app.state == AssistantState.IDLE
    assert app.response_control.current is None
    assert len(app.assistant.passive_memory_repository.list_memories()) == 1


def test_default_fallback_uses_original_device_interfaces(pipeline):
    app, _, _, _ = pipeline
    assert not app.interruption_enabled
    assert not app.request_interruption()
    app.handle_transcript("Nova, show my pending tasks")
    assert app.tts.synthesize.call_args.kwargs == {}
    app.player.play.assert_called_once_with(app.output_path)
    assert "_stop_monitor" not in app.__dict__


def test_interrupted_reminder_deferred_not_completed_or_immediately_repeated(pipeline):
    app, repository, _, _ = pipeline
    enable(app)
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    reminder = repository.add_reminder("call Mom", now - timedelta(minutes=1))
    def announce(item):
        app.speak(item.message)
    app.player.play.side_effect = lambda *args, **kwargs: (app.request_interruption(), check_cancel(kwargs["cancel_event"]))
    scheduler = ReminderScheduler(repository, announce, clock=lambda: now)
    assert scheduler.check_due() == 0
    assert scheduler.check_due() == 0
    saved = repository.list_reminders()[0]
    assert saved.id == reminder.id and not saved.is_completed
    assert saved.remind_at == now + timedelta(seconds=60)
    app.player.play.side_effect = None
    scheduler.clock = lambda: now + timedelta(seconds=60)
    assert scheduler.check_due() == 1
    assert scheduler.check_due() == 0


def test_reminder_deferral_cannot_overwrite_concurrent_edit(pipeline):
    _, repository, _, _ = pipeline
    now = datetime.now(timezone.utc)
    reminder = repository.add_reminder("meeting", now)
    claim = repository.claim_reminder(reminder, now)
    assert repository.finish_reminder_delivery(reminder.id, claim, False)
    assert not repository.defer_interrupted_reminder(reminder.id, claim, now)
    assert repository.list_reminders()[0].remind_at == reminder.remind_at


def test_spoken_stop_monitor_interrupts_playback_without_dispatching_feedback(pipeline):
    app, repository, _, _ = pipeline
    enable(app)
    app.spoken_interruption = True
    playing = Event()
    paths = []
    def record(path, stop_event):
        paths.append(path)
        assert playing.wait(3)
        path.write_bytes(b"fake input")
        return path
    stt = Mock()
    # First clip crosses processing -> speaking and must be rejected.
    stt.transcribe.return_value = "Nova, stop"
    monitor = StopMonitor(app.response_control, app.privacy, app.request_interruption,
                          recorder=Mock(record_utterance=record), stt=stt)
    app._stop_monitor = monitor
    def playback(path, cancel_event):
        playing.set()
        assert cancel_event.wait(3)
        check_cancel(cancel_event)
    app.player.play.side_effect = playback
    app.handle_transcript("Nova, add a task to finish my project")
    assert app.state == AssistantState.INTERRUPTED
    assert len(repository.list_tasks()) == 1
    assert app.assistant.passive_memory_repository.list_memories() == []
    assert not monitor.thread.is_alive()
    assert all(not path.exists() for path in paths)


def test_cancel_cleans_runtime_owned_wav_and_preserves_user_file(pipeline, tmp_path):
    app, _, _, _ = pipeline
    enable(app)
    app._temporary_audio = TemporaryAudio(tmp_path)
    app.output_path = app._temporary_audio.path("response.wav")
    user_file = tmp_path / "user.wav"
    user_file.write_bytes(b"user recording")
    def synthesize(text, path, **kwargs):
        path.write_bytes(b"output audio")
        app.request_interruption()
    app.tts.synthesize.side_effect = synthesize
    app.handle_transcript("Nova, show my pending tasks")
    assert not app.output_path.exists() and user_file.read_bytes() == b"user recording"
    app.player.play.assert_not_called()
    app._temporary_audio.close()


def test_experimental_device_failure_recovers_for_following_command(pipeline):
    app, _, _, _ = pipeline
    enable(app)
    app.player.play.side_effect = OSError("disconnected")
    app.handle_transcript("Nova, show my pending tasks")
    assert app.response_control.current is None
    app.player.play.side_effect = None
    app.handle_transcript("Nova, show my pending tasks")
    assert app.player.play.call_count == 2


def test_stale_recording_never_reaches_stt_in_experimental_mode(pipeline):
    app, _, _, _ = pipeline
    enable(app)
    generation = app.audio_gate.generation
    with app.audio_gate.playback():
        pass
    app.process_recording(app.input_path, audio_generation=generation)
    app.stt.transcribe.assert_not_called()


def test_interrupted_notification_acknowledges_failure(pipeline):
    app, repository, _, _ = pipeline
    enable(app)
    due = repository.add_reminder("call Mom", datetime.now(timezone.utc))
    errors = []
    requested = Event()
    original_request = app.notifications.request
    def request():
        requested.set()
        try:
            original_request(due)
        except Exception as exc:
            errors.append(exc)
    thread = Thread(target=request)
    thread.start()
    assert requested.wait(3)
    # Notification enqueue is asynchronous; wait on its existing interrupt signal.
    assert app.notifications.interrupt.wait(3)
    def stop(*args, **kwargs):
        app.request_interruption()
        check_cancel(kwargs["cancel_event"])
    app.player.play.side_effect = stop
    app.deliver_pending_reminders()
    thread.join(3)
    assert not thread.is_alive() and isinstance(errors[0], ResponseInterrupted)
    assert not repository.list_reminders()[0].is_completed


def test_real_assistant_propagates_model_cancel_without_history_or_error_response(pipeline, capsys):
    app, _, _, llm = pipeline
    enable(app)
    def generate(*args, **kwargs):
        app.request_interruption()
        check_cancel()
    llm.generate.side_effect = generate
    previous = app.assistant.conversation_manager.build_context()
    app.handle_transcript("Nova, tell me a story")
    assert app.assistant.conversation_manager.build_context() == previous
    app.tts.synthesize.assert_not_called()
    assert "[LLM ERROR]" not in capsys.readouterr().out


def test_mute_hotkey_during_shutdown_does_not_reenter_audio_state(pipeline):
    app, _, _, _ = pipeline
    enable(app)
    app.set_state(AssistantState.SHUTTING_DOWN)
    app._closed = True
    app.set_muted(True)
    assert app.privacy.muted and app.state == AssistantState.SHUTTING_DOWN
    app.set_muted(False)
    assert not app.privacy.muted and app.state == AssistantState.SHUTTING_DOWN
    app.handle_transcript("Nova, add a task to test")
    app.player.play.assert_not_called()
