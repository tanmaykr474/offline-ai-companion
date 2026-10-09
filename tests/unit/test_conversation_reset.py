
from unittest.mock import Mock

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.conversation import (
    ConversationManager,
)


def make_assistant():
    repository = Mock()
    repository.list_facts.return_value = {}
    repository.list_notes.return_value = []
    repository.list_tasks.return_value = []
    repository.list_reminders.return_value = []

    memory_tools = Mock()
    memory_tools.repository = repository

    conversation = ConversationManager()
    conversation.add_turn(
        "What is Python?",
        "Python is a programming language.",
    )

    assistant = Assistant(
        memory_tools=memory_tools,
        llm=Mock(),
        conversation_manager=conversation,
    )

    return assistant, repository


def test_reset_clears_conversation():
    assistant, repository = make_assistant()

    response = assistant.process(
        "Start a new conversation"
    )

    assert assistant.conversation_manager.turn_count == 0
    assert "new conversation" in response.lower()


def test_reset_preserves_saved_memory():
    assistant, repository = make_assistant()

    assistant.process("Reset conversation")

    repository.delete_fact.assert_not_called()
    repository.delete_note.assert_not_called()
    repository.delete_reminder.assert_not_called()


def test_reset_does_not_call_llm():
    assistant, repository = make_assistant()

    assistant.process("Clear chat history")

    assistant.llm.generate.assert_not_called()


def test_reset_accepts_punctuation():
    assistant, repository = make_assistant()

    assistant.process("New conversation!")

    assert assistant.conversation_manager.turn_count == 0


def test_reset_clears_pending_confirmation():
    assistant, repository = make_assistant()

    assistant.process("Forget this conversation")

    assert assistant.confirmation_manager.pending is None
