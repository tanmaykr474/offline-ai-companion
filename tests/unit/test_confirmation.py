
import pytest

from offline_ai_companion.memory.confirmation import (
    FactConfirmationManager,
)
from offline_ai_companion.memory.intelligent_extractor import (
    FactProposal,
)


@pytest.fixture
def manager():
    return FactConfirmationManager()


@pytest.fixture
def proposal():
    return FactProposal(
        key="user.company",
        value="Microsoft",
        evidence="joined Microsoft",
    )


def test_confirm_yes(manager, proposal):
    manager.propose(proposal)

    result = manager.resolve("Yes")

    assert result.status == "confirmed"
    assert result.proposal == proposal
    assert manager.pending is None


def test_reject_no(manager, proposal):
    manager.propose(proposal)

    result = manager.resolve("No")

    assert result.status == "rejected"
    assert manager.pending is None


def test_unrelated_message_does_not_confirm(
    manager, proposal
):
    manager.propose(proposal)

    result = manager.resolve(
        "What is my favorite food?"
    )

    assert result.status == "unrecognized"
    assert manager.pending == proposal


def test_resolve_without_pending(manager):
    result = manager.resolve("Yes")

    assert result.status == "none"


def test_clear(manager, proposal):
    manager.propose(proposal)
    manager.clear()

    assert manager.pending is None


@pytest.mark.parametrize(
    "answer",
    ["yes", "yeah", "confirm", "save it", "go ahead"],
)
def test_positive_confirmations(manager, proposal, answer):
    manager.propose(proposal)

    assert manager.resolve(answer).status == "confirmed"


@pytest.mark.parametrize(
    "answer",
    ["no", "cancel", "reject", "don't save"],
)
def test_negative_confirmations(manager, proposal, answer):
    manager.propose(proposal)

    assert manager.resolve(answer).status == "rejected"
