
from datetime import datetime, timedelta, timezone

import pytest

from offline_ai_companion.core.activation_controller import (
    ActivationController,
)
from offline_ai_companion.core.wake_detector import (
    WakeDetector,
)


@pytest.fixture
def controller():
    return ActivationController(
        wake_detector=WakeDetector(
            assistant_name="Nova",
            wake_phrases=(
                "Nova",
                "hey Nova",
            ),
        ),
        activation_timeout=8.0,
    )


@pytest.fixture
def start_time():
    return datetime(
        2026, 10, 9, 12, 0,
        tzinfo=timezone.utc,
    )


def test_background_speech_is_passive(
    controller,
    start_time,
):
    decision = controller.route(
        "I have a presentation tomorrow",
        now=start_time,
    )

    assert decision.action == "passive"
    assert decision.text == (
        "I have a presentation tomorrow"
    )


def test_hello_nova_routes_active_greeting(controller, start_time):
    decision = controller.route("Hello Nova", now=start_time)
    assert decision.action == "active"
    assert decision.text == "hello"


def test_wake_phrase_with_command(
    controller,
    start_time,
):
    decision = controller.route(
        "Hey Nova, what is my schedule?",
        now=start_time,
    )

    assert decision.action == "active"
    assert decision.text == "what is my schedule?"


def test_wake_phrase_alone_waits(
    controller,
    start_time,
):
    decision = controller.route(
        "Nova",
        now=start_time,
    )

    assert decision.action == "waiting"


def test_followup_within_timeout(
    controller,
    start_time,
):
    controller.route(
        "Nova",
        now=start_time,
    )

    decision = controller.route(
        "What is my name?",
        now=start_time + timedelta(seconds=3),
    )

    assert decision.action == "active"
    assert decision.text == "What is my name?"


def test_followup_after_timeout_is_passive(
    controller,
    start_time,
):
    controller.route(
        "Nova",
        now=start_time,
    )

    decision = controller.route(
        "What is my name?",
        now=start_time + timedelta(seconds=10),
    )

    assert decision.action == "passive"


def test_only_one_followup_is_activated(
    controller,
    start_time,
):
    controller.route(
        "Nova",
        now=start_time,
    )

    first = controller.route(
        "Tell me my tasks",
        now=start_time + timedelta(seconds=2),
    )

    second = controller.route(
        "I have a meeting tomorrow",
        now=start_time + timedelta(seconds=3),
    )

    assert first.action == "active"
    assert second.action == "passive"


def test_new_wake_phrase_reactivates(
    controller,
    start_time,
):
    controller.route(
        "Nova",
        now=start_time,
    )

    decision = controller.route(
        "Hey Nova, show my reminders",
        now=start_time + timedelta(seconds=2),
    )

    assert decision.action == "active"
    assert decision.text == "show my reminders"


def test_reset_cancels_activation(
    controller,
    start_time,
):
    controller.route(
        "Nova",
        now=start_time,
    )

    controller.reset()

    decision = controller.route(
        "Tell me my tasks",
        now=start_time + timedelta(seconds=2),
    )

    assert decision.action == "passive"


def test_invalid_timeout_rejected():
    with pytest.raises(ValueError):
        ActivationController(
            activation_timeout=0
        )


def test_empty_transcript_does_not_consume_activation(
    controller,
    start_time,
):
    controller.route(
        "Nova",
        now=start_time,
    )

    empty = controller.route(
        " ",
        now=start_time + timedelta(seconds=1),
    )

    followup = controller.route(
        "Show my tasks",
        now=start_time + timedelta(seconds=2),
    )

    assert empty.action == "passive"
    assert followup.action == "active"
