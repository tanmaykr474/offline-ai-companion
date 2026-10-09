
from unittest.mock import Mock

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.conversation import (
    ConversationManager,
)


def make_assistant():
    llm = Mock()
    llm.generate.side_effect = [
        "Python is a programming language.",
        "Guido van Rossum created Python.",
    ]

    repository = Mock()
    repository.list_facts.return_value = {}
    repository.list_notes.return_value = []
    repository.list_tasks.return_value = []
    repository.list_reminders.return_value = []

    memory_tools = Mock()
    memory_tools.repository = repository

    assistant = Assistant(
        memory_tools=memory_tools,
        llm=llm,
        conversation_manager=ConversationManager(),
    )

    return assistant, llm


def test_chat_turn_is_recorded():
    assistant, llm = make_assistant()

    response = assistant.process("What is Python?")

    assert response == "Python is a programming language."
    assert assistant.conversation_manager.turn_count == 1


def test_followup_includes_previous_conversation():
    assistant, llm = make_assistant()

    assistant.process("What is Python?")
    assistant.process("Who created it?")

    second_prompt = llm.generate.call_args.args[0]

    assert "What is Python?" in second_prompt
    assert "Python is a programming language." in second_prompt
    assert "Who created it?" in second_prompt


def test_first_chat_has_no_previous_history():
    assistant, llm = make_assistant()

    assistant.process("What is Python?")

    assert assistant.conversation_manager.turn_count == 1

    # First request should use the original question directly
    # when no saved memory exists.
    llm.generate.assert_called_once_with(
        "What is Python?"
    )


def test_conversation_history_respects_limit():
    llm = Mock()
    llm.generate.return_value = "Response"

    repository = Mock()
    repository.list_facts.return_value = {}
    repository.list_notes.return_value = []
    repository.list_tasks.return_value = []
    repository.list_reminders.return_value = []

    memory_tools = Mock()
    memory_tools.repository = repository

    assistant = Assistant(
        memory_tools=memory_tools,
        llm=llm,
        conversation_manager=ConversationManager(max_turns=2),
    )

    assistant.process("Question one?")
    assistant.process("Question two?")
    assistant.process("Question three?")

    assert assistant.conversation_manager.turn_count == 2
