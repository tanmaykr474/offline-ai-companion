
import pytest

from offline_ai_companion.router.query_router import (
    QueryRouter,
)


@pytest.fixture
def router():
    return QueryRouter()


def test_add_note(router):
    result = router.route(
        "Remember that my project uses Raspberry Pi 5"
    )

    assert result.intent == "add_note"
    assert result.content == "my project uses Raspberry Pi 5"


@pytest.mark.parametrize(
    "query",
    [
        "My name is Kevin",
        "Remember that my name is Kevin",
    ],
)
def test_set_name(router, query):
    result = router.route(query)

    assert result.intent == "set_name"
    assert result.content == "Kevin"


@pytest.mark.parametrize(
    "query",
    [
        "What is my name?",
        "What's my name?",
        "What people call me?",
        "What do people call me?",
        "What do you call me?",
        "Tell me my name",
        "Do you remember my name?",
        "My name is what?",
        "My name is...",
        "Who am I?",
    ],
)
def test_name_questions(router, query):
    result = router.route(query)

    assert result.intent == "get_name"


def test_list_notes(router):
    assert router.route(
        "Show my notes"
    ).intent == "list_notes"


def test_add_task(router):
    result = router.route(
        "Add a task to finish testing"
    )

    assert result.intent == "add_task"
    assert result.content == "finish testing"


def test_list_tasks(router):
    assert router.route(
        "Show my pending tasks"
    ).intent == "list_tasks"


def test_add_reminder(router):
    result = router.route(
        "Remind me to drink water in 10 minutes"
    )

    assert result.intent == "add_reminder"
    assert result.content == "drink water"
    assert result.minutes == 10


def test_list_reminders(router):
    assert router.route(
        "Show my reminders"
    ).intent == "list_reminders"


def test_chat_fallback(router):
    result = router.route(
        "Explain machine learning"
    )

    assert result.intent == "chat"
    assert result.content == "Explain machine learning"


def test_empty_query(router):
    with pytest.raises(ValueError):
        router.route("   ")


@pytest.mark.parametrize(
    "query",
    [
        "My name is what?",
        "My name is who?",
        "My name is unknown?",
    ],
)
def test_invalid_name_does_not_update(router, query):
    result = router.route(query)

    assert result.intent != "set_name"
