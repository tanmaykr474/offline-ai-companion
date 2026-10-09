
from enum import Enum


class AssistantState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    MUTED = "muted"
    INTERRUPTED = "interrupted"
    SHUTTING_DOWN = "shutting_down"


def validate_transition(previous, target):
    S = AssistantState
    transitions = {
        S.IDLE: {S.LISTENING, S.PROCESSING, S.SPEAKING, S.INTERRUPTED, S.MUTED, S.SHUTTING_DOWN},
        S.LISTENING: {S.PROCESSING, S.SPEAKING, S.INTERRUPTED, S.MUTED, S.IDLE, S.SHUTTING_DOWN},
        S.PROCESSING: {S.SPEAKING, S.LISTENING, S.INTERRUPTED, S.MUTED, S.IDLE, S.SHUTTING_DOWN},
        S.SPEAKING: {S.PROCESSING, S.LISTENING, S.INTERRUPTED, S.MUTED, S.IDLE, S.SHUTTING_DOWN},
        S.INTERRUPTED: {S.LISTENING, S.PROCESSING, S.IDLE, S.MUTED, S.SHUTTING_DOWN},
        S.MUTED: {S.IDLE, S.LISTENING, S.SHUTTING_DOWN},
        S.SHUTTING_DOWN: {S.IDLE},
    }
    if target != previous and target not in transitions[previous]:
        raise ValueError("Illegal assistant audio state transition.")
