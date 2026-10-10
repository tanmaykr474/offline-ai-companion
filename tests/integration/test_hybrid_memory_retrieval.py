"""Real SQLite and assistant integration; no models or network required."""
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock
import time
import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.cancellation import cancellation_scope, ResponseInterrupted
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_repository import PassiveMemoryRepository
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.hybrid_retriever import HybridMemoryRetriever, LocalConceptRanker
from offline_ai_companion.tools.memory_tools import MemoryTools


@pytest.fixture
def env(tmp_path):
    database = Database(tmp_path / 'hybrid.db')
    facts = MemoryRepository(database)
    passive = PassiveMemoryRepository(database)
    llm = Mock()
    llm.generate.return_value = '{"memories": []}'
    extractor = Mock()
    extractor.extract.return_value = None
    assistant = Assistant(memory_tools=MemoryTools(facts), llm=llm,
                          fact_extractor=extractor, passive_memory_repository=passive)
    return assistant, facts, passive, PassiveMemoryProcessor(passive, llm), llm


@pytest.mark.parametrize('speech,question,value', [
    ('My favorite food is biryani.', 'What food do I like most?', 'biryani'),
    ('My favorite food is biryani.', 'Which dish is my favorite?', 'biryani'),
    ('My favorite food is biryani.', 'Do you remember my preferred food?', 'biryani'),
    ('My favorite color is violet.', 'Which colour is my preferred one?', 'violet'),
    ('I work as a software engineer.', 'What is my profession?', 'software engineer'),
    ('I work as a nurse.', 'What do I do for a living?', 'nurse'),
    ('I work as an architect.', 'What job did I tell you about?', 'architect'),
    ('I enjoy drawing.', 'What are my hobbies?', 'drawing'),
    ('I love playing tennis.', 'Do you remember my leisure activities?', 'tennis'),
    ('I was born in Kerala.', 'Do you remember my birth place?', 'Kerala'),
])
def test_paraphrases(env, speech, question, value):
    assistant, facts, passive, processor, llm = env
    assert processor.process(speech) == 1
    before = passive.list_memories()
    answer = assistant.process(question)
    assert value in answer
    assert 'unidentified' in answer
    assert before == passive.list_memories()
    assert facts.list_facts() == {}
    llm.generate.assert_not_called()


def test_multi_fact_confirmed_priority(env):
    assistant, facts, passive, processor, llm = env
    processor.process('I work as a developer. I enjoy listening to music.')
    facts.set_fact('user.job', 'architect')
    answer = assistant.process('What do you remember about my work and hobbies?')
    assert 'architect' in answer and 'listening to music' in answer
    assert 'developer' not in answer
    llm.generate.assert_not_called()


@pytest.mark.parametrize('question', [
    'What sport I love playing?',
    'Which sports I love to play?',
    'Do you remember what sport I love playing?',
    'Do you know which sport do I love playing?',
    'Can you tell me what sport I love playing?',
    'Tell me what sport do I love playing?',
])
def test_spoken_activity_recall_variants(env, question):
    assistant, facts, passive, processor, llm = env
    assert processor.process('I love playing cricket.') == 1
    before = passive.list_memories()
    answer = assistant.process(question)
    assert 'cricket' in answer
    assert 'unidentified' in answer
    assert passive.list_memories() == before
    assert facts.list_facts() == {}
    llm.generate.assert_not_called()


@pytest.mark.parametrize('question', [
    'Do you remember what sport I like playing?',
    'Do you remember what sport I love playing yesterday?',
    'Do you remember what sport I do not love playing?',
])
def test_activity_wrappers_do_not_drop_meaningful_qualifiers(env, question):
    assistant, _, _, processor, _ = env
    processor.process('I love playing cricket.')
    assert 'cricket' not in assistant.process(question).lower()


@pytest.mark.parametrize('question', ['What is my profession?', 'Do you remember my preferred food?'])
def test_unknown_is_honest(env, question):
    assistant, _, _, _, llm = env
    assert "don't have" in assistant.process(question)
    llm.generate.assert_not_called()


def test_conflicts_far_apart(env):
    assistant, _, passive, processor, _ = env
    processor.process('My favorite food is rice.')
    for index in range(150):
        passive.add('task', 'speaker', f'Unrelated {index}', f'I need to finish {index}.')
    processor.process('My favorite food is pasta.')
    answer = assistant.process('Which dish is my favorite?')
    assert 'conflicting' in answer and 'rice' in answer and 'pasta' in answer


def test_correction_deletion_restart(env):
    assistant, facts, passive, _, llm = env
    facts.set_fact('user.job', 'teacher')
    assert 'teacher' in assistant.process('What is my profession?')
    facts.set_fact('user.job', 'nurse')
    restarted = HybridMemoryRetriever(PassiveMemoryRepository(passive.database), MemoryRepository(facts.database))
    assert 'nurse' in restarted.recall('What is my profession?').response
    facts.delete_fact('user.job')
    assert "don't have" in restarted.recall('What is my profession?').response


@pytest.mark.parametrize('evidence,content,subject', [
    ("I don't enjoy music.", 'Enjoys music', 'speaker'),
    ('Do I enjoy music?', 'Enjoys music', 'speaker'),
    ('If I enjoy music.', 'Enjoys music', 'speaker'),
    ('Someone said "I enjoy music."', 'Enjoys music', 'speaker'),
    ('I enjoy music.', 'Enjoys music', 'Alice'),
    ('I enjoy music.', 'Enjoys music and dancing', 'speaker'),
])
def test_unsafe_legacy_records_excluded(env, evidence, content, subject):
    assistant, _, passive, _, llm = env
    passive.add('preference', subject, content, evidence)
    answer = assistant.process('What are my hobbies?')
    assert "don't have" in answer
    llm.generate.assert_not_called()


def test_expiration_and_legacy_secret(env):
    assistant, _, passive, _, _ = env
    passive.retention_days = 1
    passive.add('preference', 'speaker', 'Enjoys music', 'I enjoy music.',
                captured_at=datetime.now(timezone.utc)-timedelta(days=2))
    with passive.database.connect() as connection:
        connection.execute("INSERT INTO passive_memories(category,subject,content,evidence,captured_at,fingerprint) VALUES(?,?,?,?,?,?)",
                           ('preference', 'speaker', 'Enjoys music', 'My password is banana. I enjoy music.', datetime.now(timezone.utc).isoformat(), 'legacy'))
    assert "don't have" in assistant.process('What are my hobbies?')
    assert len(passive.list_memories(include_expired=True)) == 2


@pytest.mark.parametrize('question', ['What outdoor activity did I do last weekend?', 'Do you remember my recent hiking trip?'])
def test_verbatim_past_event(env, question):
    assistant, _, passive, _, llm = env
    passive.add('event', 'speaker', 'Went hiking last Sunday', 'I went hiking last Sunday.')
    answer = assistant.process(question)
    assert 'hiking last Sunday' in answer and 'passive:' in answer
    llm.generate.assert_not_called()


def test_unrelated_event_and_fabricated_date(env):
    assistant, _, passive, _, _ = env
    passive.add('event', 'speaker', 'Went shopping last Sunday', 'I went shopping last Sunday.')
    passive.add('event', 'speaker', 'Went hiking last Sunday', 'I went hiking last Sunday.', event_time='2026-10-04')
    assert "don't have" in assistant.process('Do you remember my recent hiking trip?')


def test_bounded_candidates_and_latency(env):
    _, facts, passive, processor, _ = env
    for index in range(70):
        processor.process(f'I enjoy activity number {index}.')
    start = time.monotonic()
    result = HybridMemoryRetriever(passive, facts).recall('What are my hobbies?')
    assert time.monotonic()-start < 1
    assert len(result.memories) <= 3 and 'incomplete' in result.response


@pytest.mark.parametrize('error', [RuntimeError('unavailable'), TimeoutError('timeout'), OSError('missing')])
def test_ranker_unavailable_fallback(env, error):
    _, facts, passive, processor, _ = env
    processor.process('I enjoy drawing.')
    ranker = Mock()
    ranker.score.side_effect = error
    result = HybridMemoryRetriever(passive, facts, ranker=ranker).recall('What are my hobbies?')
    assert 'drawing' in result.response


def test_cancelled_retrieval_no_writes(env):
    _, facts, passive, _, _ = env
    event = Event(); event.set()
    with pytest.raises(ResponseInterrupted), cancellation_scope(event):
        HybridMemoryRetriever(passive, facts).recall('What are my hobbies?')
    assert passive.list_memories() == [] and facts.list_facts() == {}


def test_general_chat_does_not_retrieve(env):
    _, facts, passive, _, _ = env
    retriever = HybridMemoryRetriever(passive, facts)
    assert retriever.recall('Explain how professions change over time') is None
    assert retriever.recall('Add a task to review my work') is None


def test_ranker_is_local_and_semantic():
    ranker = LocalConceptRanker()
    assert ranker.score('my profession', 'I work as a nurse') > 0
    assert ranker.score('my preferred dish', 'My favorite food is rice') > 0


def test_confirmed_hobbies_override_passive(env):
    assistant, facts, _, processor, _ = env
    processor.process('I enjoy music.')
    facts.set_fact('user.hobbies', 'drawing')
    answer = assistant.process('What are my hobbies?')
    assert 'Confirmed hobbies: drawing' in answer and 'music' not in answer


def test_ranker_deadline_uses_only_grounded_fallback(env):
    _, facts, passive, processor, _ = env
    processor.process('I enjoy drawing.')
    ticks = [0]
    def clock():
        return ticks[0]
    class Late:
        def score(self, query, evidence):
            ticks[0] = 1
            return 100
    answer = HybridMemoryRetriever(passive, facts, ranker=Late(), clock=clock).recall('What are my hobbies?')
    assert 'drawing' in answer.response


def test_secret_legacy_exact_activity_never_returned(env):
    assistant, _, passive, _, _ = env
    with passive.database.connect() as connection:
        connection.execute("INSERT INTO passive_memories(category,subject,content,evidence,captured_at,fingerprint) VALUES(?,?,?,?,?,?)",
                           ('preference','speaker','Loves sk-abcdefghijk','I love sk-abcdefghijk.',datetime.now(timezone.utc).isoformat(),'legacy-secret'))
    assert 'sk-' not in assistant.process('What do I love doing?')


@pytest.mark.parametrize('question', ['What is my work address?', 'Which food do I like least?',
                                      'What music do I enjoy?', 'Where did I leave my work laptop?'])
def test_shared_words_do_not_prove_answer(env, question):
    assistant, _, _, processor, llm = env
    processor.process('I work as a developer. I love playing cricket.')
    answer = assistant.process(question)
    assert "don't have" in answer and 'cricket' not in answer and 'developer' not in answer
    llm.generate.assert_not_called()


def test_past_event_not_hidden_by_unrelated_preferences(env):
    assistant, _, passive, _, _ = env
    passive.add('event', 'speaker', 'Went hiking last Sunday', 'I went hiking last Sunday.')
    for index in range(100):
        passive.add('preference', 'speaker', f'Enjoys activity {index}', f'I enjoy activity {index}.')
    assert 'hiking' in assistant.process('What outdoor activity did I do last weekend?')


def test_locked_database_is_bounded_and_does_not_fall_back_to_passive(env):
    _, facts, passive, processor, _ = env
    processor.process('My favorite food is rice.')
    facts.set_fact('user.favorite_food', 'pizza')
    with facts.database.connect() as connection:
        connection.execute('BEGIN EXCLUSIVE')
        start = time.monotonic()
        answer = HybridMemoryRetriever(passive, facts).recall('Which dish is my favorite?')
        assert time.monotonic()-start < 0.5
        assert 'unavailable' in answer.response
        assert 'rice' not in answer.response


def test_oversized_legacy_candidates_not_loaded(env):
    _, _, passive, _, _ = env
    with passive.database.connect() as connection:
        connection.execute("INSERT INTO passive_memories(category,subject,content,evidence,captured_at,fingerprint) VALUES(?,?,?,?,?,?)",
                           ('event','speaker','Went ' + 'hiking '*1000,'I went ' + 'hiking '*1000,datetime.now(timezone.utc).isoformat(),'oversized'))
    assert passive.recall_candidates(category='event') == []
