
from unittest.mock import Mock

import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.router.query_router import QueryRouter
from offline_ai_companion.tools.memory_tools import MemoryTools
from offline_ai_companion.memory.intelligent_extractor import (
    FactProposal,
)


def make_assistant(tmp_path):
    repository = MemoryRepository(
        Database(tmp_path / "assistant.db")
    )

    llm = Mock()
    llm.generate.return_value = "A local AI response."

    assistant = Assistant(
        router=QueryRouter(),
        memory_tools=MemoryTools(repository),
        llm=llm,
    )

    return assistant, repository, llm


def test_note_command(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    response = assistant.process(
        "Remember that I have a demo tomorrow"
    )

    assert "Saved your note" in response
    assert len(repository.list_notes()) == 1
    llm.generate.assert_not_called()


def test_task_command(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process(
        "Add a task to finish the project"
    )

    assert repository.list_tasks()[0].title == (
        "finish the project"
    )
    llm.generate.assert_not_called()


def test_reminder_command(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    response = assistant.process(
        "Remind me to drink water in 5 minutes"
    )

    assert "Reminder saved" in response
    assert len(repository.list_reminders()) == 1
    llm.generate.assert_not_called()


def test_chat_uses_llm(tmp_path):
    assistant, _, llm = make_assistant(tmp_path)

    response = assistant.process(
        "What is artificial intelligence?"
    )

    assert response == "A local AI response."
    llm.generate.assert_called_once_with(
        "What is artificial intelligence?"
    )


def test_chat_recalls_saved_memory(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    repository.add_note(
        "My AI companion project uses Raspberry Pi 5."
    )

    response = assistant.process(
        "What hardware does my AI companion use?"
    )

    assert response == "A local AI response."

    prompt = llm.generate.call_args.args[0]

    assert "Raspberry Pi 5" in prompt
    assert "What hardware does my AI companion use?" in prompt




def test_memory_not_saved_again_during_recall(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process(
        "My favorite programming language is Python"
    )
    assistant.process("Yes")

    initial_facts = repository.list_facts().copy()

    response = assistant.process(
        "What is my favorite programming language?"
    )

    assert response == (
        "Your favorite programming language is Python."
    )
    assert repository.list_facts() == initial_facts

    llm.generate.assert_not_called()




def test_latest_name_overrides_previous_name(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("My name is Kevin")
    assistant.process("My name is Tanmay")

    assert repository.get_fact("user.name") == "Tanmay"
    assert assistant.process("What is my name?") == (
        "Your name is Tanmay."
    )

    llm.generate.assert_not_called()


@pytest.mark.parametrize(
    "question",
    [
        "What is my name?",
        "What's my name?",
        "What people call me?",
        "What do people call me?",
        "My name is what?",
        "My name is...",
        "Who am I?",
    ],
)
def test_name_questions_use_latest_fact(
    tmp_path,
    question,
):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("My name is Kevin")
    assistant.process("My name is Tanmay")

    response = assistant.process(question)

    assert response == "Your name is Tanmay."
    assert repository.get_fact("user.name") == "Tanmay"

    llm.generate.assert_not_called()


def test_name_persists_after_restart(tmp_path):
    database_path = tmp_path / "persistent.db"

    first_repository = MemoryRepository(
        Database(database_path)
    )

    first = Assistant(
        memory_tools=MemoryTools(first_repository),
        llm=Mock(),
    )

    first.process("My name is Kevin")
    first.process("My name is Tanmay")

    second_repository = MemoryRepository(
        Database(database_path)
    )

    second = Assistant(
        memory_tools=MemoryTools(second_repository),
        llm=Mock(),
    )

    assert second.process("What is my name?") == (
        "Your name is Tanmay."
    )


def test_general_fact_update(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("My favorite language is Python")
    assistant.process("Yes")

    assistant.process("My favorite language is Java")
    assistant.process("Yes")

    assert repository.get_fact(
        "user.favorite_language"
    ) == "Java"

    assert assistant.process(
        "What is my favorite language?"
    ) == "Your favorite language is Java."

    llm.generate.assert_not_called()



def test_fact_alias_recall(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process(
        "My favorite programming language is Python"
    )
    assistant.process("Yes")

    assert repository.get_fact(
        "user.favorite_language"
    ) == "Python"

    assert assistant.process(
        "What is my favorite language?"
    ) == "Your favorite language is Python."

    llm.generate.assert_not_called()




def test_fact_question_does_not_overwrite(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("My favorite food is Pizza")
    assistant.process("Yes")

    assistant.process("My favorite food is what?")

    assert repository.get_fact(
        "user.favorite_food"
    ) == "Pizza"

    llm.generate.assert_not_called()



def test_unknown_fact(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    response = assistant.process(
        "What is my favorite color?"
    )

    assert response == (
        "I don't have your favorite color saved yet."
    )

    llm.generate.assert_not_called()



def test_historical_note_recall_does_not_duplicate_notes(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    repository.add_note(
        "My AI companion uses a Raspberry Pi 5."
    )

    response = assistant.process(
        "What hardware does my AI companion use?"
    )

    assert response == "A local AI response."
    assert len(repository.list_notes()) == 1

    llm.generate.assert_called_once()



def test_natural_food_update_and_recall(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("I love eating Biryani")
    assistant.process("Yes")

    assistant.process("My favorite food is Pizza")
    assistant.process("Yes")

    assert repository.get_fact(
        "user.favorite_food"
    ) == "Pizza"

    assert assistant.process(
        "What food do I like?"
    ) == "Your favorite food is Pizza."

    llm.generate.assert_not_called()




def test_workplace_update_and_recall(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("I work at Infosys")
    assistant.process("Yes")

    assert repository.get_fact(
        "user.company"
    ) == "Infosys"

    assert assistant.process(
        "Where do I work?"
    ) == "Your company is Infosys."

    llm.generate.assert_not_called()




def test_city_update_and_recall(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    assistant.process("I live in Pune")
    assistant.process("Yes")

    assistant.process("I live in Mumbai")
    assistant.process("Yes")

    assert repository.get_fact(
        "user.city"
    ) == "Mumbai"

    assert assistant.process(
        "Where do I live?"
    ) == "Your city is Mumbai."

    llm.generate.assert_not_called()



def test_intelligent_fact_requires_confirmation(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    extractor = Mock()
    extractor.extract.return_value = FactProposal(
        key="user.company",
        value="Microsoft",
        evidence="joined Microsoft",
    )

    assistant.fact_extractor = extractor

    response = assistant.process(
        "I recently joined Microsoft"
    )

    assert response == (
        "Should I save your company as Microsoft?"
    )

    # No write before confirmation.
    assert repository.get_fact("user.company") is None

    response = assistant.process("Yes")

    assert response == (
        "Saved. Your company is now Microsoft."
    )

    assert repository.get_fact(
        "user.company"
    ) == "Microsoft"

    llm.generate.assert_not_called()


def test_intelligent_fact_rejection(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    extractor = Mock()
    extractor.extract.return_value = FactProposal(
        key="user.city",
        value="Bengaluru",
        evidence="moved to Bengaluru",
    )

    assistant.fact_extractor = extractor

    assistant.process("I moved to Bengaluru")
    response = assistant.process("No")

    assert response == "Okay, I won't save that fact."
    assert repository.get_fact("user.city") is None

    llm.generate.assert_not_called()


def test_intelligent_fact_updates_existing_value(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    repository.set_fact("user.company", "Infosys")

    extractor = Mock()
    extractor.extract.return_value = FactProposal(
        key="user.company",
        value="Microsoft",
        evidence="joined Microsoft",
    )

    assistant.fact_extractor = extractor

    response = assistant.process(
        "I recently joined Microsoft"
    )

    assert response == (
        "Your saved company is Infosys. "
        "Should I update it to Microsoft?"
    )

    assert repository.get_fact("user.company") == "Infosys"

    assistant.process("Yes")

    assert repository.get_fact(
        "user.company"
    ) == "Microsoft"


def test_unrelated_message_cancels_pending_fact(tmp_path):
    assistant, repository, llm = make_assistant(tmp_path)

    extractor = Mock()
    extractor.extract.return_value = FactProposal(
        key="user.company",
        value="Microsoft",
        evidence="joined Microsoft",
    )

    assistant.fact_extractor = extractor

    assistant.process("I recently joined Microsoft")

    response = assistant.process("What is my name?")

    assert response == "I don't have your name saved yet."
    assert repository.get_fact("user.company") is None
    assert assistant.confirmation_manager.pending is None


def test_confirmed_fact_survives_restart(tmp_path):
    database_path = tmp_path / "persistent_facts.db"

    repository = MemoryRepository(Database(database_path))

    assistant = Assistant(
        memory_tools=MemoryTools(repository),
        llm=Mock(),
    )

    extractor = Mock()
    extractor.extract.return_value = FactProposal(
        key="user.company",
        value="Microsoft",
        evidence="joined Microsoft",
    )

    assistant.fact_extractor = extractor

    assistant.process("I recently joined Microsoft")
    assistant.process("Yes")

    restarted_repository = MemoryRepository(
        Database(database_path)
    )

    restarted = Assistant(
        memory_tools=MemoryTools(restarted_repository),
        llm=Mock(),
    )

    assert restarted.process("Where do I work?") == (
        "Your company is Microsoft."
    )

