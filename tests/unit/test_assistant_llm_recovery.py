
from unittest.mock import Mock

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.conversation import (
    ConversationManager,
)


def test_assistant_recovers_from_llm_failure():
    llm = Mock()
    llm.generate.side_effect = RuntimeError(
        "Ollama request timed out."
    )

    repository = Mock()
    repository.list_facts.return_value = {}
    repository.list_notes.return_value = []
    repository.list_tasks.return_value = []
    repository.list_reminders.return_value = []

    memory_tools = Mock()
    memory_tools.repository = repository

    conversation = ConversationManager()

    assistant = Assistant(
        memory_tools=memory_tools,
        llm=llm,
        conversation_manager=conversation,
    )

    response = assistant.process(
        "Explain quantum computing."
    )

    assert "Please try again" in response
    assert conversation.turn_count == 0
