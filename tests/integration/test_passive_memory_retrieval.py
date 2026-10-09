
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import (
    MemoryRepository,
)
from offline_ai_companion.memory.passive_repository import (
    PassiveMemoryRepository,
)
from offline_ai_companion.tools.memory_tools import (
    MemoryTools,
)


@pytest.fixture
def environment(tmp_path):
    database = Database(
        tmp_path / "assistant_passive_memory.db"
    )

    memory_repository = MemoryRepository(database)

    passive_repository = PassiveMemoryRepository(
        database
    )

    llm = Mock()
    llm.generate.return_value = (
        "You have a project presentation on Monday."
    )

    extractor = Mock()
    extractor.extract.return_value = None

    assistant = Assistant(
        memory_tools=MemoryTools(
            memory_repository
        ),
        llm=llm,
        fact_extractor=extractor,
        passive_memory_repository=passive_repository,
    )

    return {
        "assistant": assistant,
        "memory_repository": memory_repository,
        "passive_repository": passive_repository,
        "llm": llm,
    }


def test_passive_memory_is_included_in_context(environment):
    passive_repository = environment[
        "passive_repository"
    ]

    passive_repository.add(
        category="event",
        subject="speaker",
        content="Project presentation on Monday",
        evidence="I have a project presentation on Monday",
        captured_at=datetime(
            2026, 10, 9,
            tzinfo=timezone.utc,
        ),
    )

    context = environment[
        "assistant"
    ]._build_memory_context()

    assert "PASSIVE MEMORY [event]" in context
    assert "Project presentation on Monday" in context
    assert "subject=speaker" in context


def test_question_uses_passive_memory(environment):
    passive_repository = environment[
        "passive_repository"
    ]

    passive_repository.add(
        category="event",
        subject="speaker",
        content="Project presentation on Monday",
        evidence="I have a project presentation on Monday",
    )

    response = environment[
        "assistant"
    ].process(
        "Do you remember any upcoming presentations?"
    )

    assert response == (
        "You have a project presentation on Monday."
    )

    prompt = environment[
        "llm"
    ].generate.call_args.args[0]

    assert "Project presentation on Monday" in prompt
    assert "upcoming presentations" in prompt


def test_event_time_is_available_to_llm(environment):
    passive_repository = environment[
        "passive_repository"
    ]

    passive_repository.add(
        category="event",
        subject="speaker",
        content="Project presentation",
        evidence="I have a project presentation",
        event_time="2026-10-12T11:00:00+05:30",
    )

    context = environment[
        "assistant"
    ]._build_memory_context()

    assert (
        "event_time=2026-10-12T11:00:00+05:30"
        in context
    )


def test_current_fact_and_passive_memory_coexist(environment):
    memory_repository = environment[
        "memory_repository"
    ]

    passive_repository = environment[
        "passive_repository"
    ]

    memory_repository.set_fact(
        "user.city",
        "Patna",
    )

    passive_repository.add(
        category="fact",
        subject="speaker",
        content="Speaker previously lived in Delhi",
        evidence="I previously lived in Delhi",
    )

    context = environment[
        "assistant"
    ]._build_memory_context()

    assert "CURRENT FACT user.city: Patna" in context
    assert "Speaker previously lived in Delhi" in context


def test_passive_memory_persists_across_instances(
    environment,
):
    original_assistant = environment[
        "assistant"
    ]

    passive_repository = environment[
        "passive_repository"
    ]

    passive_repository.add(
        category="task",
        subject="speaker",
        content="Finish the project report",
        evidence="I need to finish the project report",
    )

    second_assistant = Assistant(
        memory_tools=original_assistant.memory_tools,
        llm=Mock(),
        fact_extractor=Mock(),
        passive_memory_repository=(
            PassiveMemoryRepository(
                original_assistant
                .memory_tools
                .repository
                .database
            )
        ),
    )

    context = second_assistant._build_memory_context()

    assert "Finish the project report" in context


def test_deleted_passive_memory_is_not_retrieved(environment):
    passive_repository = environment[
        "passive_repository"
    ]

    passive_repository.add(
        category="preference",
        subject="speaker",
        content="Prefers Python",
        evidence="I prefer Python",
    )

    memory = passive_repository.list_memories()[0]

    assert passive_repository.delete(memory.id)

    context = environment[
        "assistant"
    ]._build_memory_context()

    assert "Prefers Python" not in context


def test_no_passive_memories_preserves_existing_behavior(
    environment,
):
    assistant = environment["assistant"]
    llm = environment["llm"]

    assistant.process(
        "Explain what a compiler does."
    )

    llm.generate.assert_called_once_with(
        "Explain what a compiler does."
    )
