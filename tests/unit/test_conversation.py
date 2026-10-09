
import pytest

from offline_ai_companion.core.conversation import (
    ConversationManager,
)


def test_conversation_starts_empty():
    manager = ConversationManager()

    assert manager.turn_count == 0
    assert manager.get_history() == []


def test_add_conversation_turn():
    manager = ConversationManager()

    manager.add_turn(
        "What is Python?",
        "Python is a programming language.",
    )

    assert manager.turn_count == 1
    assert manager.get_history()[0].user == (
        "What is Python?"
    )


def test_conversation_context_format():
    manager = ConversationManager()

    manager.add_turn(
        "What is Python?",
        "Python is a programming language.",
    )

    context = manager.build_context()

    assert "User: What is Python?" in context
    assert (
        "Assistant: Python is a programming language."
        in context
    )


def test_conversation_history_limit():
    manager = ConversationManager(max_turns=2)

    manager.add_turn("First", "Response 1")
    manager.add_turn("Second", "Response 2")
    manager.add_turn("Third", "Response 3")

    assert manager.turn_count == 2
    assert manager.get_history()[0].user == "Second"


def test_clear_conversation():
    manager = ConversationManager()

    manager.add_turn("Hello", "Hi")
    manager.clear()

    assert manager.turn_count == 0


def test_rejects_invalid_history_limit():
    with pytest.raises(ValueError):
        ConversationManager(max_turns=0)


def test_rejects_empty_messages():
    manager = ConversationManager()

    with pytest.raises(ValueError):
        manager.add_turn("", "Hello")

    with pytest.raises(ValueError):
        manager.add_turn("Hello", "")


def test_context_respects_character_budget():
    manager = ConversationManager(
        max_turns=10,
        max_context_chars=60,
    )

    manager.add_turn(
        "Old question",
        "Old response",
    )

    manager.add_turn(
        "New question",
        "New response",
    )

    context = manager.build_context()

    assert "New question" in context
    assert "New response" in context
    assert "Old question" not in context
    assert len(context) <= 60


def test_context_keeps_chronological_order():
    manager = ConversationManager(
        max_context_chars=1000,
    )

    manager.add_turn("First", "Response 1")
    manager.add_turn("Second", "Response 2")

    context = manager.build_context()

    assert context.index("First") < context.index("Second")


def test_oversized_turn_is_not_partially_included():
    manager = ConversationManager(
        max_context_chars=20,
    )

    manager.add_turn(
        "A very long question",
        "A very long answer",
    )

    assert manager.build_context() == ""


def test_rejects_invalid_context_budget():
    with pytest.raises(ValueError):
        ConversationManager(max_context_chars=0)


def test_context_budget_does_not_delete_history():
    manager = ConversationManager(
        max_context_chars=20,
    )

    manager.add_turn(
        "A long question",
        "A long response",
    )

    assert manager.build_context() == ""
    assert manager.turn_count == 1
