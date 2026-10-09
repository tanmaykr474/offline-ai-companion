"""Shared, conservative secret handling. This is not a credential vault."""

import re
import os


SECRET_LABEL = (r"password|passcode|otp|one[- ]time (?:password|code)|pin|"
                r"api[ _-]?key|access[ _-]?token|auth(?:entication)?[ _-]?token|"
                r"refresh[ _-]?token|secret[ _-]?key|private[ _-]?key|"
                r"credit[ _-]?card|card[ _-]?(?:number|cvv)|cvv|bank[ _-]?account|"
                r"social security(?: number)?|ssn")
SECRET_PATTERN = re.compile(
    rf"\b(?:{SECRET_LABEL})\b\s*(?:is\b|equals\b|[:=])\s*\S+|"
    rf"\b(?:my|your)\s+(?:{SECRET_LABEL})\b\s+\S+|"
    r"\b(?:otp|pin|cvv)\s+\d{3,8}\b|\bBearer\s+\S+|"
    r"\bsk-[A-Za-z0-9_-]{8,}|\bAKIA[A-Z0-9]{16}\b|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", re.I,
)
# Automatic collection is stricter than explicitly requested personal storage.
AUTOMATIC_SENSITIVE_PATTERN = re.compile(
    rf"\b(?:{SECRET_LABEL}|diagnosis|medical record|medical history)\b", re.I,
)
STORAGE_REFUSAL = "I can't store credential secrets. Please use a password manager."


def contains_secret(text: str) -> bool:
    return bool(SECRET_PATTERN.search(text.replace("’", "'")))


def allows_storage(text: str, *, explicit: bool = False) -> bool:
    return not contains_secret(text) and (explicit or not AUTOMATIC_SENSITIVE_PATTERN.search(text))


def require_safe_storage(text: str) -> None:
    if not allows_storage(text, explicit=True):
        raise ValueError(STORAGE_REFUSAL)


def model_text(text: str) -> str:
    # Whole-field replacement avoids accidentally retaining adjacent credential
    # fragments. Personal information without secrets remains usable locally.
    return "[CREDENTIAL CONTENT OMITTED]" if contains_secret(text) else text


def history_text(text: str) -> str:
    return text if allows_storage(text) else "[PRIVATE CONTENT OMITTED]"


def debug_text(text: str) -> str:
    if os.getenv("NOVA_PRIVATE_DEBUG", "false").lower() in {"true", "1", "yes", "on"}:
        return model_text(text)
    return "[PRIVATE CONTENT HIDDEN]"
