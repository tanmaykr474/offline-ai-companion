
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.passive_repository import (
    PassiveMemoryRepository,
)
from offline_ai_companion.memory.passive_processor import (
    PassiveMemoryProcessor,
)


@pytest.fixture
def environment(tmp_path):
    repository = PassiveMemoryRepository(
        Database(tmp_path / "passive.db")
    )
    llm = Mock()

    processor = PassiveMemoryProcessor(
        repository=repository,
        llm=llm,
    )

    return repository, llm, processor


def llm_response(memories):
    return json.dumps({"memories": memories})


def memory_item(
    category="event",
    subject="speaker",
    content="Project presentation tomorrow",
    evidence="I have a project presentation tomorrow",
    event_time=None,
):
    return {
        "category": category,
        "subject": subject,
        "content": content,
        "evidence": evidence,
        "event_time": event_time,
    }


def test_extracts_and_saves_event(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item()
    ])

    saved = processor.process(
        "I have a project presentation tomorrow"
    )

    assert saved == 1

    memories = repository.list_memories()

    assert len(memories) == 1
    assert memories[0].category == "event"
    assert memories[0].subject == "speaker"


def test_duplicate_memory_not_saved_twice(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item()
    ])

    transcript = "I have a project presentation tomorrow"

    assert processor.process(transcript) == 1
    assert processor.process(transcript) == 0
    assert len(repository.list_memories()) == 1


def test_multiple_memories(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item(),
        memory_item(
            category="task",
            content="Finish the project report",
            evidence="I need to finish the project report",
        ),
    ])

    saved = processor.process(
        "I have a project presentation tomorrow. "
        "I need to finish the project report."
    )

    assert saved == 2
    assert len(repository.list_memories()) == 2


def test_empty_transcript_is_ignored(environment):
    repository, llm, processor = environment

    assert processor.process("   ") == 0
    llm.generate.assert_not_called()


def test_invalid_json_is_ignored(environment):
    repository, llm, processor = environment

    llm.generate.return_value = "not json"

    assert processor.process("I have a meeting tomorrow") == 0
    assert repository.list_memories() == []


def test_unsupported_category_is_rejected(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item(category="secret")
    ])

    assert processor.process(
        "I have a project presentation tomorrow"
    ) == 0


def test_missing_evidence_is_rejected(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item(evidence="This was never spoken")
    ])

    assert processor.process(
        "I have a project presentation tomorrow"
    ) == 0


def test_sensitive_transcript_is_not_saved(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item(
            category="fact",
            content="My password is abc123",
            evidence="My password is abc123",
        )
    ])

    assert processor.process(
        "My password is abc123"
    ) == 0

    assert repository.list_memories() == []


def test_llm_failure_does_not_crash(environment):
    repository, llm, processor = environment

    llm.generate.side_effect = RuntimeError(
        "Ollama unavailable"
    )

    assert processor.process(
        "I have a meeting tomorrow"
    ) == 0


def test_memory_can_be_deleted(environment):
    repository, llm, processor = environment

    repository.add(
        category="fact",
        subject="speaker",
        content="Project name is Nova",
        evidence="Project name is Nova",
    )

    memory = repository.list_memories()[0]

    assert repository.delete(memory.id) is True
    assert repository.list_memories() == []


def test_all_memories_can_be_cleared(environment):
    repository, llm, processor = environment

    repository.add(
        "fact",
        "speaker",
        "Project name is Nova",
        "Project name is Nova",
    )

    assert repository.clear() == 1
    assert repository.list_memories() == []


def test_event_time_must_have_timezone(environment):
    repository, llm, processor = environment

    llm.generate.return_value = llm_response([
        memory_item(
            event_time="2026-10-10T10:00:00"
        )
    ])

    assert processor.process(
        "I have a project presentation tomorrow"
    ) == 0


def test_capture_timestamp_is_preserved(environment):
    repository, llm, processor = environment

    captured_at = datetime(
        2026, 10, 9, 10, 0,
        tzinfo=timezone.utc,
    )

    llm.generate.return_value = llm_response([
        memory_item()
    ])

    assert processor.process(
        "I have a project presentation tomorrow",
        captured_at=captured_at,
    ) == 1

    memory = repository.list_memories()[0]

    assert memory.captured_at == captured_at.isoformat()


def test_mixed_captions_and_speech_extract_grounded_memory(environment):
    repository, llm, processor = environment
    assert processor.process("[MUSIC] I love playing cricket. [XBOX SOUND]") == 1
    memory = repository.list_memories()[0]
    assert memory.content == "Loves playing cricket"
    assert memory.evidence == "I love playing cricket"
    llm.generate.assert_not_called()


def test_default_passive_client_has_separate_timeout_and_no_retries(environment):
    repository, _, _ = environment
    from offline_ai_companion.config import PASSIVE_MEMORY_LLM_TIMEOUT
    processor = PassiveMemoryProcessor(repository)
    assert processor.llm.timeout == PASSIVE_MEMORY_LLM_TIMEOUT
    assert processor.llm.max_retries == 0


def test_passive_timeout_is_not_retried_or_saved(environment):
    repository, _, _ = environment
    import httpx
    client = Mock(spec=httpx.Client)
    client.post.side_effect = httpx.ReadTimeout("Model busy")
    processor = PassiveMemoryProcessor(repository)
    processor.llm.client = client
    assert processor.process("I have a meeting tomorrow") == 0
    client.post.assert_called_once()
    assert client.post.call_args.kwargs["timeout"] == processor.llm.timeout
    assert repository.list_memories() == []
