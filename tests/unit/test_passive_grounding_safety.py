"""Adversarial candidates exercise the real processor and temporary SQLite."""

import json
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock

import pytest

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.passive_repository import PassiveMemoryRepository
from offline_ai_companion.memory.passive_worker import PassiveMemoryWorker


CAPTURE = datetime(2026, 10, 9, 23, 55, tzinfo=timezone(timedelta(hours=5, minutes=30)))


@pytest.fixture
def environment(tmp_path):
    repo = PassiveMemoryRepository(Database(tmp_path / "grounding.db"))
    llm = Mock()
    llm.generate.return_value = '{"memories": []}'
    return repo, llm, PassiveMemoryProcessor(repo, llm)


def candidate(category, content, evidence, event_time=None):
    return dict(category=category, subject="speaker", content=content,
                evidence=evidence, event_time=event_time)


def propose(environment, transcript, items, captured_at=CAPTURE):
    repo, llm, processor = environment
    llm.generate.return_value = json.dumps({"memories": items})
    return processor.process(transcript, captured_at=captured_at)


@pytest.mark.parametrize("speech,category,content", [
    ("I don't need to finish the report.", "task", "Finish the report"),
    ("I never liked cricket.", "preference", "Likes cricket"),
    ("I wasn't born in Bihar.", "fact", "Birthplace is Bihar"),
    ("I don’t work as a developer.", "fact", "Works as a developer"),
    ("I will not attend the meeting.", "event", "Attend the meeting"),
    ("I won't attend the meeting tomorrow.", "event", "Attend the meeting tomorrow"),
    ("I have no meeting tomorrow.", "event", "Meeting tomorrow"),
    ("I needn't finish the report.", "task", "Finish the report"),
    ("Do I love playing cricket?", "preference", "Loves playing cricket"),
    ("I love playing cricket?", "preference", "Loves playing cricket"),
    ("Am I from Bihar?", "fact", "Birthplace is Bihar"),
    ("What if I moved to Delhi?", "event", "Moved to Delhi"),
    ("Suppose I worked as a developer.", "fact", "Works as a developer"),
    ('Someone said, "I love playing cricket."', "preference", "Loves playing cricket"),
    ("If I finish the report tomorrow, I can relax.", "task", "Finish the report tomorrow"),
    ("If I need to finish the report tomorrow, I can relax.", "task", "Finish the report tomorrow"),
    ("Do I need to finish the report?", "task", "Finish the report"),
    ("I need to finish the report?", "task", "Finish the report"),
    ("Perhaps I will finish the report.", "task", "Finish the report"),
    ("I might have a meeting tomorrow.", "event", "Meeting tomorrow"),
    ("I think I have a meeting tomorrow.", "event", "Meeting tomorrow"),
    ('Someone said, "I have a meeting tomorrow."', "event", "Meeting tomorrow"),
    ("I have a meeting tomorrow, but it was cancelled.", "event", "Meeting tomorrow"),
    ("I used to work as a developer.", "fact", "Works as a developer"),
    ("My favorite food is not biryani.", "preference", "Favorite food is biryani"),
    ("My favorite food is biryani?", "preference", "Favorite food is biryani"),
    ("If my favorite food is biryani.", "preference", "Favorite food is biryani"),
])
def test_nonasserted_candidates_rejected(environment, speech, category, content):
    assert propose(environment, speech, [candidate(category, content, speech)]) == 0
    assert environment[0].list_memories() == []


@pytest.mark.parametrize("speech", [
    "Do I love playing cricket?", "I love playing cricket?",
    'Someone said, "I love playing cricket."',
    "Someone said, ‘I love playing cricket.’",
    "'I love playing cricket.'", "If I love playing cricket.",
    "I enjoy listening to music, but not anymore.",
    "My favorite food is biryani?", "I was born in Bihar?",
    "I work as a developer?",
])
def test_deterministic_path_cannot_bypass_assertion_check(environment, speech):
    processor = environment[2]
    assert processor._extract_personal_statements(speech) == []
    assert processor.process(speech) == 0


@pytest.mark.parametrize("speech,content", [
    ("I love playing cricket!", "Loves playing cricket"),
    ("I enjoy listening to music.", "Enjoys listening to music"),
    ("I was born in Bihar.", "Birthplace is Bihar"),
    ("I work as a software developer.", "Works as a software developer"),
    ("My favorite food is biryani (homemade)!", "Favorite food is biryani (homemade)"),
    ("My favorite food is biryani, especially homemade.", "Favorite food is biryani, especially homemade"),
    ("My favorite food is grandma's biryani.", "Favorite food is grandma's biryani"),
])
def test_affirmative_personal_observations_and_incidental_punctuation(environment, speech, content):
    repo, llm, processor = environment
    assert processor.process(speech) == 1
    assert repo.list_memories()[0].content == content
    llm.generate.assert_not_called()
    assert processor.process(speech) == 0


@pytest.mark.parametrize("category,speech,content", [
    ("task", "I need to finish the report.", "Finish the report"),
    ("task", "I have to submit the draft tomorrow!", "Submit the draft tomorrow"),
    ("task", "I must call Alice before Bob.", "Call Alice before Bob"),
    ("task", "I plan to write the report.", "Write the report"),
    ("task", "I am going to clean the room.", "Clean the room"),
    ("event", "I have a project presentation tomorrow.", "Project presentation tomorrow"),
    ("event", "I will attend the meeting tomorrow.", "Attend the meeting tomorrow"),
    ("event", "I have an appointment on 2026-10-12.", "Appointment on 2026-10-12"),
])
def test_supported_actions_remain_accepted(environment, category, speech, content):
    assert propose(environment, speech, [candidate(category, content, speech)]) == 1


@pytest.mark.parametrize("category,speech,content,evidence", [
    ("task", "I don't need to finish the report.", "Finish the report", "need to finish the report"),
    ("event", "If I have a meeting tomorrow, I will attend.", "Meeting tomorrow", "I have a meeting tomorrow"),
    ("event", 'Someone said, "I have a meeting tomorrow."', "Meeting tomorrow", "I have a meeting tomorrow"),
    ("task", "I must call Alice before Bob.", "Call Bob before Alice", "I must call Alice before Bob."),
    ("task", "I need to finish the draft report.", "Finish the report", "I need to finish the draft report."),
    ("task", "I need to finish the report tomorrow.", "Finish the report", "I need to finish the report tomorrow."),
    ("event", "I have a meeting tomorrow.", "Meeting tomorrow in Delhi", "I have a meeting tomorrow."),
    ("event", "You have a meeting tomorrow.", "Meeting tomorrow", "You have a meeting tomorrow."),
    ("task", "We need to finish the report.", "Finish the report", "We need to finish the report."),
    ("event", "I have a meeting tomorrow at 10:30 +05:30.", "Meeting tomorrow at 10:30 -05:30", "I have a meeting tomorrow at 10:30 +05:30."),
])
def test_substrings_reordering_omission_and_other_speakers_do_not_ground(environment, category, speech, content, evidence):
    assert propose(environment, speech, [candidate(category, content, evidence)]) == 0


@pytest.mark.parametrize("speech,time_value,expected", [
    ("I have a meeting tomorrow.", None, "2026-10-10"),
    ("I have a meeting today.", "2026-10-09", "2026-10-09"),
    ("I have a meeting yesterday.", None, "2026-10-08"),
    ("I have a meeting tonight.", None, "2026-10-09"),
    ("I have a meeting on 2026-12-31.", "2026-12-31", "2026-12-31"),
    ("I have a meeting tomorrow at 10:30.", None, "2026-10-10T10:30:00+05:30"),
    ("I have a meeting tomorrow at 10:30.", "2026-10-10T05:00:00Z", "2026-10-10T10:30:00+05:30"),
    ("I have a meeting on 2026-10-12 at 10:30 +02:00.", None, "2026-10-12T10:30:00+02:00"),
    ("I have a meeting on 2026-10-12 at 10:30 Z.", None, "2026-10-12T10:30:00+00:00"),
    ("I have a meeting.", None, None),
    ("I have a meeting next week.", None, None),
    ("I have a meeting on 10/11/2026.", None, None),
    ("I have a meeting tomorrow at noon.", None, None),
    ("I have a meeting tomorrow at 10:30 PST.", None, None),
])
def test_grounded_time_and_date_precision(environment, speech, time_value, expected):
    content = speech.removeprefix("I have a ").rstrip(".")
    assert propose(environment, speech, [candidate("event", content, speech, time_value)]) == 1
    memory = environment[0].list_memories()[0]
    assert memory.event_time == expected
    assert memory.captured_at == CAPTURE.astimezone(timezone.utc).isoformat()


@pytest.mark.parametrize("speech,time_value", [
    ("I have a meeting.", "2026-10-10T10:00:00+05:30"),
    ("I have a meeting tomorrow.", "2026-10-10T00:00:00+05:30"),
    ("I have a meeting tomorrow.", "2026-10-11"),
    ("I have a meeting tomorrow.", "2026-10-10T10:00:00"),
    ("I have a meeting on 10/11/2026.", "2026-10-11"),
    ("I have a meeting on Monday.", "2026-10-12"),
    ("I have a meeting next month.", "2026-11-09"),
    ("I have a meeting on October 12.", "2026-10-12"),
    ("I have a meeting on 2026-02-30.", "2026-02-28"),
    ("I have a meeting on 2026-10-10 and 2026-10-11.", "2026-10-10"),
    ("I have a meeting tomorrow at 25:30.", "2026-10-10T10:30:00+05:30"),
    ("I have a meeting tomorrow at 10:30 PST.", "2026-10-10T10:30:00+05:30"),
    ("I have a meeting tomorrow at 10:30 am.", "2026-10-10T10:30:00+05:30"),
    ("I have a meeting tomorrow at 10:30.", "2026-10-10T10:30:00+00:00"),
    ("I have a meeting tomorrow at 10:30 +05:30.", "2026-10-10T10:30:01+05:30"),
    ("I have a meeting tomorrow at 10:30 +05:99.", "2026-10-10T10:30:00+06:39"),
])
def test_unsupported_or_ambiguous_model_dates_rejected(environment, speech, time_value):
    content = speech.removeprefix("I have a ").rstrip(".")
    assert propose(environment, speech, [candidate("event", content, speech, time_value)]) == 0
    assert environment[0].list_memories() == []


def test_mixed_personal_sentences_keep_only_assertions(environment):
    repo, llm, processor = environment
    speech = ('My favorite food is biryani? My favorite food is pasta. '
              'Someone said, "I love playing cricket." I enjoy listening to music! '
              'If I was born in Bihar. I work as a developer.')
    assert processor.process(speech) == 3
    assert {m.content for m in repo.list_memories()} == {
        "Favorite food is pasta", "Enjoys listening to music", "Works as a developer"}
    llm.generate.assert_not_called()


def test_mixed_llm_actions_validate_each_statement_and_prevent_duplicates(environment):
    speech = "I don't need to finish the report. I need to write the draft. I have a meeting tomorrow."
    good = candidate("task", "Write the draft", "I need to write the draft.")
    items = [candidate("task", "Finish the report", "I don't need to finish the report."),
             good, good, candidate("event", "Meeting tomorrow", "I have a meeting tomorrow.")]
    assert propose(environment, speech, items) == 2
    assert propose(environment, speech, items) == 0
    assert len(environment[0].list_memories()) == 2


@pytest.mark.parametrize("response", [
    "not JSON", "null", "[]", '{"memories": null}', '{"memories": {}, "extra": 1}',
    '{"memories": [null, [], 1, "x"]}',
    json.dumps({"memories": [candidate([], "Meeting tomorrow", "I have a meeting tomorrow.")]}),
    json.dumps({"memories": [candidate("event", "Meeting tomorrow", "I have a meeting tomorrow.", {})]}),
    json.dumps({"memories": [dict(category="event", content="Meeting tomorrow")]}),
])
def test_malformed_llm_responses_fail_closed(environment, response):
    repo, llm, processor = environment
    llm.generate.return_value = response
    assert processor.process("I have a meeting tomorrow.") == 0
    assert repo.list_memories() == []


def test_audio_captions_do_not_change_question_safety(environment):
    processor = environment[2]
    assert processor.process("[MUSIC] I love playing cricket? [NOISE]") == 0
    assert processor.process("[MUSIC] I love playing cricket! [NOISE]") == 1


def test_worker_keeps_capture_time_across_queued_delay_and_shutdown(environment):
    repo, llm, processor = environment
    entered, release = Event(), Event()
    original = processor.process
    calls = []

    def delayed(text, captured_at=None):
        calls.append(captured_at)
        entered.set()
        assert release.wait(3)
        return original(text, captured_at=captured_at)

    processor.process = delayed
    speech = "I have a meeting tomorrow."
    llm.generate.return_value = json.dumps({"memories": [candidate("event", "Meeting tomorrow", speech)]})
    worker = PassiveMemoryWorker(processor)
    worker.start()
    try:
        assert worker.submit(speech, captured_at=CAPTURE)
        assert entered.wait(3)
        assert worker.submit(speech, captured_at=CAPTURE + timedelta(days=1))
        assert not worker.stop(timeout=0)
    finally:
        release.set()
        assert worker.stop(timeout=3)
    assert calls == [CAPTURE, CAPTURE + timedelta(days=1)]
    assert {m.event_time for m in repo.list_memories()} == {"2026-10-10", "2026-10-11"}
    assert worker.queue.unfinished_tasks == 0


def test_worker_rejects_naive_capture_timestamp(environment):
    worker = PassiveMemoryWorker(environment[2])
    worker.start()
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            worker.submit("I have a meeting tomorrow.", datetime(2026, 10, 9))
    finally:
        assert worker.stop()


def test_question_evidence_cannot_borrow_identical_affirmative_statement(environment):
    speech = "I have a meeting tomorrow? I have a meeting tomorrow."
    item = candidate("event", "Meeting tomorrow", "I have a meeting tomorrow?")
    assert propose(environment, speech, [item]) == 0


@pytest.mark.parametrize("day,expected", [
    (datetime(2026, 12, 31, tzinfo=timezone.utc), "2027-01-01"),
    (datetime(2028, 2, 28, tzinfo=timezone.utc), "2028-02-29"),
])
def test_relative_dates_follow_original_calendar_context(environment, day, expected):
    speech = "I have a meeting tomorrow."
    assert propose(environment, speech, [candidate("event", "Meeting tomorrow", speech)], day) == 1
    assert environment[0].list_memories()[0].event_time == expected
