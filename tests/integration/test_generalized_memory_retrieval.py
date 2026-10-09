"""Exercise real extraction, SQLite and assistant routing without production data."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.passive_repository import PassiveMemoryRepository
from offline_ai_companion.memory.passive_retriever import PassiveMemoryRetriever
from offline_ai_companion.memory.passive_worker import PassiveMemoryWorker
from offline_ai_companion.tools.memory_tools import MemoryTools


@pytest.fixture
def environment(tmp_path):
    database = Database(tmp_path / "recall.db")
    facts = MemoryRepository(database)
    passive = PassiveMemoryRepository(database)
    llm = Mock()
    llm.generate.return_value = '{"memories": []}'
    extractor = Mock()
    extractor.extract.return_value = None
    assistant = Assistant(memory_tools=MemoryTools(facts), llm=llm,
                          fact_extractor=extractor, passive_memory_repository=passive)
    return assistant, facts, passive, PassiveMemoryProcessor(passive, llm), llm


@pytest.mark.parametrize("speech,question,content", [
    ("I love playing cricket.", "What sport do I love playing?", "Loves playing cricket"),
    ("I love playing tennis.", "Which sport do I love to play?", "Loves playing tennis"),
    ("I was born in Bihar.", "Where was I born?", "Birthplace is Bihar"),
    ("I born in Kerala.", "Tell me where I was born", "Birthplace is Kerala"),
    ("I enjoy listening to music.", "What do I enjoy doing?", "Enjoys listening to music"),
    ("I enjoy reading books.", "What activities do I enjoy?", "Enjoys reading books"),
    ("I work as a developer.", "What do I do for work?", "Works as a developer"),
    ("I work as an architect.", "What do I work as?", "Works as a architect"),
    ("My favorite food is biryani.", "What is my favorite food?", "biryani"),
    ("My favorite programming language is Python.", "Which language do I like most?", "Python"),
])
def test_extraction_sqlite_recall(environment, speech, question, content):
    assistant, facts, passive, processor, llm = environment
    assert processor.process(speech) == 1
    before = passive.list_memories()
    response = assistant.process("Hey Nova, " + question)
    assert content in response
    assert "unidentified speaker" in response
    assert passive.list_memories() == before
    assert facts.list_facts() == {}
    assert facts.list_notes() == []
    llm.generate.assert_not_called()
    assert assistant.conversation_manager.get_history()[-1].assistant == response
    assert processor.process(speech) == 0


@pytest.mark.parametrize("speech", [
    "I wasn't born in Bihar.", "I don't like cricket.",
    "I used to work as a developer.", "If I was born in Bihar.",
    "If I lived in Bihar, I love playing cricket.",
    "She said I was born in Bihar.", "I love playing cricket but not anymore.",
    "If my favorite food is biryani.",
])
def test_nonaffirmative_speech_is_not_saved(environment, speech):
    _, _, passive, processor, _ = environment
    assert processor.process(speech) == 0
    assert passive.list_memories() == []


def test_unsupported_llm_claim_is_rejected(environment):
    _, _, passive, processor, llm = environment
    llm.generate.return_value = '''{"memories": [{"category": "fact",
        "subject": "speaker", "content": "Birthplace is Bihar",
        "evidence": "I wasn't born in Bihar", "event_time": null}]}'''
    assert processor.process("I wasn't born in Bihar") == 0
    assert passive.list_memories() == []


@pytest.mark.parametrize("speech,question,key,value", [
    ("My favorite programming language is Python.", "What is my favorite programming language?", "user.favorite_language", "Java"),
    ("I work as a developer.", "What do I do for work?", "user.job", "teacher"),
    ("I was born in Bihar.", "Where was I born?", "user.birthplace", "Kerala"),
    ("My favorite food is biryani.", "What is my favorite food?", "user.favorite_food", "Pizza"),
])
def test_confirmed_fact_priority(environment, speech, question, key, value):
    assistant, facts, _, processor, llm = environment
    processor.process(speech)
    facts.set_fact(key, value)
    assert value in assistant.process(question)
    llm.generate.assert_not_called()


def test_conflicting_observations_preserve_sources(environment):
    assistant, facts, passive, processor, llm = environment
    processor.process("I was born in Bihar.")
    processor.process("I was born in Kerala.")
    response = assistant.process("Where was I born?")
    assert "conflicting" in response
    assert "Bihar" in response and "Kerala" in response
    result = PassiveMemoryRetriever(passive, facts).recall("Where was I born?")
    assert result.memories == tuple(passive.list_memories())
    assert all(m.evidence and m.captured_at for m in result.memories)
    llm.generate.assert_not_called()


@pytest.mark.parametrize("question", ["Where was I born?", "What sport do I love playing?", "What is my favorite food?"])
def test_unknown_recall_does_not_use_llm(environment, question):
    assistant, _, _, processor, llm = environment
    processor.process("I enjoy listening to music.")
    assert "don't have" in assistant.process(question)
    llm.generate.assert_not_called()


def test_corrupt_or_other_speaker_observation_is_not_an_answer(environment):
    assistant, _, passive, _, llm = environment
    passive.add("fact", "speaker", "Birthplace is Bihar", "I wasn't born in Bihar")
    passive.add("fact", "Alice", "Birthplace is Kerala", "I was born in Kerala")
    assert "don't have" in assistant.process("Where was I born?")
    llm.generate.assert_not_called()


def test_recall_cancels_unrelated_pending_confirmation(environment):
    assistant, facts, _, processor, llm = environment
    processor.process("My favorite food is biryani.")
    assistant.process("My favorite color is blue")
    assert assistant.confirmation_manager.pending is not None
    assert "biryani" in assistant.process("What is my favorite food?")
    assert assistant.confirmation_manager.pending is None
    assert facts.get_fact("user.favorite_color") is None
    assistant.process("My favorite color is blue")
    assert "Saved" in assistant.process("Yes")
    assert facts.get_fact("user.favorite_color") == "blue"
    llm.generate.assert_not_called()


def test_conflict_outside_first_repository_page(environment):
    assistant, _, passive, processor, _ = environment
    processor.process("I was born in Bihar.")
    for number in range(105):
        passive.add("task", "speaker", f"Task {number}", f"I need to do task {number}")
    processor.process("I was born in Kerala.")
    assert "conflicting" in assistant.process("Where was I born?")


def test_summary_prioritizes_facts_and_attributes_observations(environment):
    assistant, facts, _, processor, llm = environment
    facts.set_fact("user.name", "Tanmay")
    processor.process("I love playing cricket.")
    response = assistant.process("What do you remember about me?")
    assert "Confirmed name: Tanmay" in response
    assert "speaker observation: Loves playing cricket" in response
    assert "captured" in response
    llm.generate.assert_not_called()


def test_background_processing_to_sqlite_recall_and_shutdown(environment):
    assistant, _, _, processor, _ = environment
    from threading import Event
    completed = Event()

    class SignalingProcessor:
        def process(self, transcript):
            try:
                return processor.process(transcript)
            finally:
                completed.set()

    worker = PassiveMemoryWorker(SignalingProcessor())
    worker.start()
    try:
        assert worker.submit("I love playing cricket.")
        assert completed.wait(3)
        assert "cricket" in assistant.process("What sport do I love playing?")
    finally:
        assert worker.stop()
    assert worker.queue.unfinished_tasks == 0


@pytest.mark.parametrize("transcript", ["[MUSIC]", "[XBOX SOUND] [MUSIC]", "(applause)", "..."])
def test_non_speech_never_reaches_extraction(environment, transcript):
    _, _, passive, processor, llm = environment
    assert processor.process(transcript) == 0
    assert passive.list_memories() == []
    llm.generate.assert_not_called()


def test_provenance_timestamp_survives_recall(environment):
    _, facts, passive, processor, _ = environment
    timestamp = datetime(2026, 10, 9, tzinfo=timezone.utc)
    processor.process("I was born in Bihar.", captured_at=timestamp)
    result = PassiveMemoryRetriever(passive, facts).recall("Where was I born?")
    assert result.memories[0].captured_at == timestamp.isoformat()
    assert result.memories[0].event_time is None


def test_shutdown_drains_accepted_observations_into_sqlite(environment):
    from threading import Event
    assistant, _, passive, processor, llm = environment
    entered, release = Event(), Event()

    class SlowProcessor:
        def process(self, transcript):
            entered.set()
            assert release.wait(3)
            return processor.process(transcript)

    worker = PassiveMemoryWorker(SlowProcessor())
    worker.start()
    try:
        assert worker.submit("I love playing cricket.")
        assert entered.wait(3)
        assert worker.submit("I was born in Bihar.")
        assert not worker.stop(timeout=0)
    finally:
        release.set()
        assert worker.stop(timeout=3)
    assert len(passive.list_memories()) == 2
    assert "cricket" in assistant.process("What sport do I love playing?")
    assert "Bihar" in assistant.process("Where was I born?")
    assert worker.queue.unfinished_tasks == 0
    llm.generate.assert_not_called()
