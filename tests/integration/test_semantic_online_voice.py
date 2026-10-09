"""Mocked Windows orchestration; actual assistant/SQLite, no physical claims."""
from datetime import datetime, timezone
import httpx
import pytest
from unittest.mock import Mock

from .test_always_on_end_to_end import pipeline, scripted_run, wait_until
from offline_ai_companion.core.state import AssistantState
from offline_ai_companion.core.cancellation import check_cancel
from offline_ai_companion.tools.online_tools import OnlineTools, OnlineConfig
from tests.unit.test_online_tools import provider, settings, NOW


def test_passive_paraphrase_then_multi_fact_voice(pipeline):
    app, facts, _, llm = pipeline
    def barrier(index):
        if index == 1:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)
            assert app.assistant.passive_memory_repository.list_memories()
            app.tts.synthesize.assert_not_called()
    app.assistant.online_tools = OnlineTools(OnlineConfig())
    scripted_run(app, ['My favorite food is biryani. I work as a developer. I enjoy drawing.',
                       'Nova, which dish is my favorite?',
                       'Nova, what do you remember about my work and hobbies?'], barrier)
    responses = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert 'biryani' in responses[0]
    assert 'developer' in responses[1] and 'drawing' in responses[1]
    assert facts.list_facts() == {}
    assert len(app.assistant.passive_memory_repository.list_memories()) == 3
    llm.generate.assert_not_called()


@pytest.mark.parametrize('query', ["Nova, what's the weather today?", "Nova, tell me today's top news."])
def test_offline_voice_response(pipeline, monkeypatch, query):
    app, facts, _, llm = pipeline
    monkeypatch.setattr(httpx, 'Client', Mock(side_effect=AssertionError('offline')))
    app.assistant.online_tools = OnlineTools(OnlineConfig())
    app.handle_transcript(query)
    assert 'unavailable offline' in app.tts.synthesize.call_args.args[0]
    assert facts.list_facts() == {} and facts.list_tasks() == []
    llm.generate.assert_not_called()


def test_switching_memory_weather_news_reminders(pipeline):
    app, facts, _, llm = pipeline
    calls = []
    def capture(request):
        calls.append(request); return provider(request)
    app.assistant.online_tools = OnlineTools(settings(), httpx.MockTransport(capture), lambda: NOW)
    facts.set_fact('user.favorite_food', 'pizza')
    facts.set_fact('user.private_topic', 'private diary not for provider')
    commands = ['Nova, which dish is my favorite?', "Nova, what's the temperature in Pune?",
                'Nova, give me technology headlines.', 'Nova, remind me to take a break in 30 minutes',
                'Nova, what is my favorite food?']
    for command in commands:
        app.handle_transcript(command)
    responses = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert 'pizza' in responses[0] and 'Celsius' in responses[1]
    assert 'Science Daily' in responses[2] and 'Reminder saved' in responses[3]
    assert 'pizza' in responses[4]
    assert len(calls) == 3 and len(facts.list_reminders()) == 1
    for call in calls:
        assert 'pizza' not in str(call.url) and 'private' not in str(call.url)
    llm.generate.assert_not_called()


@pytest.mark.parametrize('query', ["Nova, what's the temperature in Pune?", 'Nova, give me technology headlines.'])
def test_interrupted_live_response_preserves_sqlite_and_next_command(pipeline, query):
    app, facts, _, llm = pipeline
    app.experimental_interruption = True
    app.spoken_interruption = False
    app.assistant.online_tools = OnlineTools(settings(), httpx.MockTransport(provider), lambda: NOW)
    facts.add_task('already committed')
    facts.set_fact('user.favorite_food', 'pizza')
    before_tasks = facts.list_tasks()
    before_facts = facts.list_facts()
    def interrupt(*args, **kwargs):
        assert app.request_interruption()
        check_cancel(kwargs['cancel_event'])
    app.player.play.side_effect = interrupt
    app.handle_transcript(query)
    assert app.state == AssistantState.INTERRUPTED
    assert app.response_control.current is None
    assert facts.list_tasks() == before_tasks and facts.list_facts() == before_facts
    app.player.play.side_effect = None
    app.handle_transcript('Nova, which dish is my favorite?')
    assert 'pizza' in app.tts.synthesize.call_args.args[0]
    llm.generate.assert_not_called()


def test_muted_live_command_has_no_provider_access(pipeline):
    app, _, _, _ = pipeline
    app.assistant.online_tools = OnlineTools(settings(), httpx.MockTransport(lambda r: pytest.fail('muted command')))
    app.set_muted(True)
    app.handle_transcript("Nova, what's the weather in Pune?")
    app.tts.synthesize.assert_not_called()


def test_cancellation_during_provider_result_not_spoken(pipeline):
    app, facts, _, _ = pipeline
    app.experimental_interruption = True
    app.spoken_interruption = False
    def cancelled(request):
        app.request_interruption()
        return provider(request)
    app.assistant.online_tools = OnlineTools(settings(), httpx.MockTransport(cancelled), lambda: NOW)
    app.handle_transcript('Nova, give me technology headlines.')
    app.tts.synthesize.assert_not_called()
    assert app.state == AssistantState.INTERRUPTED
    assert facts.list_facts() == {} and facts.list_reminders() == []
