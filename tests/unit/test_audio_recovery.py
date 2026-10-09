
from threading import Event
from unittest.mock import Mock

import pytest

from offline_ai_companion.audio.recovery import (
    AudioRecovery,
)


def test_recovery_waits_before_retry():
    recovery = AudioRecovery(retry_delay=2.0)

    stop_event = Mock(spec=Event)
    stop_event.is_set.return_value = False

    recovery.handle_failure(
        "Microphone",
        RuntimeError("Device unavailable"),
        stop_event,
    )

    stop_event.wait.assert_called_once_with(2.0)


def test_recovery_skips_wait_when_stopping():
    recovery = AudioRecovery(retry_delay=2.0)

    stop_event = Mock(spec=Event)
    stop_event.is_set.return_value = True

    recovery.handle_failure(
        "Whisper",
        RuntimeError("Failed"),
        stop_event,
    )

    stop_event.wait.assert_not_called()


def test_recovery_accepts_zero_delay():
    recovery = AudioRecovery(retry_delay=0)

    assert recovery.retry_delay == 0


def test_recovery_rejects_negative_delay():
    with pytest.raises(ValueError):
        AudioRecovery(retry_delay=-1)
