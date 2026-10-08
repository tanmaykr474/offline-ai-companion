
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Note:
    id: int
    content: str
    created_at: str


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    is_completed: bool
    created_at: str


@dataclass(frozen=True)
class Reminder:
    id: int
    message: str
    remind_at: datetime
    is_completed: bool
    created_at: str
