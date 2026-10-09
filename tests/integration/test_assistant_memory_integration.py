
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.router.query_router import QueryRouter
from offline_ai_companion.tools.memory_tools import MemoryTools


@pytest.fixture
def integration_environment(tmp_path):
    """Create a real isolated SQLite database and assistant."""

    database_path = tmp_path / "integration.db"

    repository = MemoryRepository(
        Database(database_path)
    )

    llm = Mock()
    llm.generate.return_value = "This is a test response."

    extractor = Mock()
    extractor.extract.return_value = None

    def create_assistant():
        return Assistant(
            router=QueryRouter(),
            memory_tools=MemoryTools(repository),
            llm=llm,
            fact_extractor=extractor,
        )

    return {
        "repository": repository,
        "llm": llm,
        "extractor": extractor,
        "create_assistant": create_assistant,
    }


def test_name_persists_across_assistant_instances(
    integration_environment,
):
    env = integration_environment

    assistant = env["create_assistant"]()

    response = assistant.process("My name is Alex")

    assert "Alex" in response

    restarted_assistant = env["create_assistant"]()

    response = restarted_assistant.process(
        "What is my name?"
    )

    assert response == "Your name is Alex."

    assert (
        env["repository"].get_fact("user.name")
        == "Alex"
    )


def test_notes_persist_across_instances(
    integration_environment,
):
    env = integration_environment

    assistant = env["create_assistant"]()

    response = assistant.process(
        "Take a note buy groceries tomorrow"
    )

    assert "buy groceries tomorrow" in response

    restarted = env["create_assistant"]()

    notes = restarted.process("Show my notes")

    assert "buy groceries tomorrow" in notes


def test_tasks_persist_across_instances(
    integration_environment,
):
    env = integration_environment

    assistant = env["create_assistant"]()

    response = assistant.process(
        "Add a task to finish the presentation"
    )

    assert "finish the presentation" in response

    restarted = env["create_assistant"]()

    tasks = restarted.process("Show my tasks")

    assert "finish the presentation" in tasks


def test_reminder_creation_persists(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    before = datetime.now(timezone.utc)

    response = assistant.process(
        "Remind me to drink water in 5 minutes"
    )

    after = datetime.now(timezone.utc)

    reminders = env["repository"].list_reminders()

    assert "Reminder saved" in response
    assert len(reminders) == 1

    reminder = reminders[0]

    assert reminder.message == "drink water"
    assert reminder.is_completed is False

    delta_before = (
        reminder.remind_at - before
    ).total_seconds()

    delta_after = (
        reminder.remind_at - after
    ).total_seconds()

    assert delta_before >= 300
    assert delta_after <= 300


def test_personal_fact_requires_confirmation(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    response = assistant.process(
        "My favorite color is blue"
    )

    assert "Should I save" in response

    assert (
        env["repository"].get_fact(
            "user.favorite_color"
        )
        is None
    )

    confirmation = assistant.process("yes")

    assert "Saved" in confirmation

    assert (
        env["repository"].get_fact(
            "user.favorite_color"
        )
        == "blue"
    )


def test_rejected_fact_is_not_saved(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    assistant.process(
        "My favorite color is green"
    )

    response = assistant.process("no")

    assert "won't save" in response

    assert (
        env["repository"].get_fact(
            "user.favorite_color"
        )
        is None
    )


def test_confirmed_fact_update_replaces_previous_value(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    assistant.process("My favorite color is blue")
    assistant.process("yes")

    response = assistant.process(
        "My favorite color is red"
    )

    assert "Should I update" in response

    assert (
        env["repository"].get_fact(
            "user.favorite_color"
        )
        == "blue"
    )

    assistant.process("yes")

    assert (
        env["repository"].get_fact(
            "user.favorite_color"
        )
        == "red"
    )


def test_conversation_reset_preserves_memory(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    assistant.process("My name is Alex")
    assistant.process("Tell me a fun fact")

    assert assistant.conversation_manager.build_context()

    response = assistant.process(
        "Start a new conversation"
    )

    assert "saved memories are preserved" in response
    assert (
        assistant.conversation_manager.build_context()
        == ""
    )

    assert (
        assistant.process("What is my name?")
        == "Your name is Alex."
    )


def test_follow_up_includes_previous_conversation(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    env["llm"].generate.side_effect = [
        "Python is a programming language.",
        "It is widely used for automation.",
    ]

    assistant.process("What is Python?")
    assistant.process("What is it used for?")

    assert env["llm"].generate.call_count == 2

    second_prompt = (
        env["llm"].generate.call_args.args[0]
    )

    assert "What is Python?" in second_prompt
    assert (
        "Python is a programming language."
        in second_prompt
    )


def test_llm_failure_preserves_memory(
    integration_environment,
):
    env = integration_environment
    assistant = env["create_assistant"]()

    assistant.process("My name is Alex")

    env["llm"].generate.side_effect = RuntimeError(
        "Ollama unavailable"
    )

    response = assistant.process(
        "Explain machine learning"
    )

    assert "trouble with my local language model" in response

    assert (
        env["repository"].get_fact("user.name")
        == "Alex"
    )

    assert (
        assistant.conversation_manager.build_context()
        == ""
    )
