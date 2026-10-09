from datetime import datetime, timedelta, timezone

from .test_always_on_end_to_end import pipeline, scripted_run, wait_until

NOW = datetime(2026, 10, 9, 4, tzinfo=timezone.utc)


def test_task_wake_commands_confirmation_tts_and_private_logs(pipeline, capsys):
    app, repo, _, llm = pipeline
    scripted_run(app, ["Nova, add a task to finish my project",
                       "Nova, show my pending tasks", "Nova, rename task number 1 to API integration",
                       "Nova, yes", "Nova, complete task number 1", "Nova, yes",
                       "Nova, delete task number 1", "Nova, no"])
    responses = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert "task:1" in responses[0] and "project" in responses[1]
    assert "Confirm rename" in responses[2] and "renamed" in responses[3]
    assert "completed" in responses[5] and "Cancelled" in responses[7]
    assert repo.get_task(1).title == "API integration" and repo.get_task(1).is_completed
    assert app.player.play.call_count == 8
    assert "project" not in capsys.readouterr().out
    llm.generate.assert_not_called()


def test_reminder_calendar_reschedule_snooze_cancel_voice(pipeline, capsys):
    app, repo, _, llm = pipeline
    app.assistant.task_management.clock = lambda: NOW
    # Use the same clock in the real scheduler so calendar fixtures remain future.
    app.scheduler.clock = lambda: NOW
    scripted_run(app, ["Nova, remind me to call Mom tomorrow at 6 PM",
                       "Nova, show my upcoming reminders",
                       "Nova, reschedule reminder number 1 to tomorrow at 11 AM", "Nova, yes",
                       "Nova, snooze reminder number 1 for 10 minutes", "Nova, yes",
                       "Nova, cancel my reminder to call Mom", "Nova, yes"])
    responses = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert "reminder:1" in responses[0] and "IST" in responses[1]
    assert "rescheduled" in responses[3] and "snoozed" in responses[5]
    assert "cancelled" in responses[7]
    assert repo.get_reminder(1).is_completed
    assert repo.get_reminder(1).remind_at == NOW + timedelta(minutes=10)
    assert "call Mom" not in capsys.readouterr().out
    llm.generate.assert_not_called()


def test_passive_task_observation_does_not_become_actionable_task(pipeline):
    app, repo, _, llm = pipeline
    def barrier(index):
        if index:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)
    scripted_run(app, ["I need to finish my project.", "Nova, show my pending tasks"], barrier)
    assert repo.list_tasks() == [] and repo.list_reminders() == []
    responses = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert len(responses) == 1 and "No pending tasks" in responses[0]
