"""Deterministic review and optimistic, confirmed memory changes."""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from offline_ai_companion.core.privacy_policy import contains_secret, allows_storage
from offline_ai_companion.memory.fact_parser import FactParser
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor


@dataclass(frozen=True)
class MemoryCommand:
    action: str
    target: str = ""
    value: str = ""
    page: int = 1


def parse_memory_command(query):
    text = re.sub(r"^(?:hey\s+)?nova[,\s]+", "", query.strip(), flags=re.I).rstrip(" .!?")
    normalized = " ".join(text.lower().split())
    page_match = re.fullmatch(r"(.+?) page (\d+)", normalized)
    page = int(page_match[2]) if page_match else 1
    base = page_match[1] if page_match else normalized
    reviews = {
        "what do you remember about me": "all", "what do you know about me": "all",
        "tell me what you remember about me": "all", "show my saved memories": "all",
        "list my preferences": "preferences", "what facts have you saved about me": "facts",
        "show my saved facts": "facts", "show my passive memories": "passive",
    }
    if base in reviews:
        return MemoryCommand("review", reviews[base], page=page)
    match = re.fullmatch(r"(show|delete|remove) (?:passive )?memory (?:number )?(\d+)", normalized)
    if match:
        return MemoryCommand("show" if match[1] == "show" else "delete", "passive:" + match[2])
    match = re.fullmatch(r"(show|delete|remove) (passive:\d+|fact:user\.[a-z0-9_]+)", normalized)
    if match:
        return MemoryCommand("show" if match[1] == "show" else "delete", match[2])
    match = re.fullmatch(r"(show|delete|remove) fact (user\.[a-z0-9_]+)", normalized)
    if match:
        return MemoryCommand("show" if match[1] == "show" else "delete", "fact:" + match[2])
    bulk = {
        "forget everything you remember about me": "all",
        "clear my passive memories": "passive", "delete all saved facts": "facts",
    }
    if normalized in bulk:
        return MemoryCommand("bulk", bulk[normalized])
    match = re.fullmatch(r"(?:forget|remove) my (.+?)(?: preference)?", normalized)
    if match:
        return MemoryCommand("delete_label", match[1])
    match = re.fullmatch(r"forget that (.+)", text, re.I)
    if match:
        return MemoryCommand("delete_statement", match[1])
    match = re.fullmatch(r"(?:update|correct) my (.+?) to (.+)", text, re.I)
    if match:
        return MemoryCommand("correct", match[1].lower(), match[2])
    match = re.fullmatch(r"my (.+?) is now (.+)", text, re.I)
    if match:
        return MemoryCommand("correct", match[1].lower(), match[2])
    match = re.fullmatch(r"actually,? i prefer (.+?) instead of (.+)", text, re.I)
    if match:
        return MemoryCommand("replace_preference", match[2], match[1])
    return None


@dataclass(frozen=True)
class PendingChange:
    action: str
    target: str
    value: str
    snapshots: tuple
    deadline: datetime
    question: str


class MemoryManagement:
    PAGE_SIZE = 3
    MAX_RESPONSE = 1400
    YES = {"yes", "confirm", "yes delete", "confirm deletion", "yes update", "confirm update"}
    NO = {"no", "cancel", "nope", "reject", "do not delete", "don't delete"}

    def __init__(self, facts, passive, confirmation, clock=None, timeout_seconds=120):
        if timeout_seconds <= 0:
            raise ValueError("Confirmation timeout must be positive.")
        self.facts, self.passive, self.confirmation = facts, passive, confirmation
        self.database = facts.database
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout_seconds = timeout_seconds
        self.pending = None
        self.validator = PassiveMemoryProcessor(passive, llm=object())

    def clear(self):
        self.pending = None

    def _now(self):
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("Confirmation clock must be timezone-aware.")
        return now

    @staticmethod
    def fact_key(label):
        label = " ".join(label.lower().split())
        field = {**FactParser.FIELDS, "name": "name", "birthplace": "birthplace",
                 "preferred activity": "preferred_activity"}.get(label)
        if field is None and re.fullmatch(r"favou?rite [a-z][a-z _-]{0,60}", label):
            field = "favorite_" + label.split(" ", 1)[1].replace(" ", "_")
        return "user." + field if field else None

    def _passive_records(self):
        if self.passive is None:
            return []
        records, offset = [], 0
        while True:
            batch = self.passive.list_memories(limit=100, offset=offset)
            records.extend(batch)
            if len(batch) < 100:
                return records
            offset += len(batch)

    @staticmethod
    def _preview(text, limit=160):
        if contains_secret(text):
            return "[credential content omitted]"
        return " ".join(text.split())[:limit]

    def _passive_line(self, memory):
        private = contains_secret(" ".join((memory.subject, memory.content, memory.evidence,
                                            memory.captured_at, memory.event_time or "")))
        if private:
            return f"passive:{memory.id}: [credential content omitted]"
        subject = "unidentified speaker" if memory.subject.lower() == "speaker" else self._preview(memory.subject, 40)
        line = (f"passive:{memory.id} — {memory.category}, {subject}; "
                f"speaker observation: {self._preview(memory.content)} "
                f"(captured {self._preview(memory.captured_at, 40)})")
        if memory.event_time:
            line += f"; event time {self._preview(memory.event_time, 40)}"
        return line

    def review(self, scope, page):
        if page < 1:
            return "Memory pages start at 1."
        lines = []
        if scope != "passive":
            for key, value in self.facts.list_facts().items():
                if len(key) > 100:
                    continue
                if contains_secret(key + ": " + value):
                    continue
                if scope == "preferences" and not key.startswith(("user.favorite_", "user.preferred_")):
                    continue
                label = key.removeprefix("user.").replace("_", " ")
                lines.append(f"fact:{key} — Confirmed {label}: {self._preview(value)}.")
        if scope != "facts":
            for memory in self._passive_records():
                if scope == "preferences" and memory.category != "preference":
                    continue
                if contains_secret(" ".join((memory.subject, memory.content, memory.evidence))):
                    continue
                lines.append(self._passive_line(memory))
        start = (page - 1) * self.PAGE_SIZE
        selected = lines[start:start + self.PAGE_SIZE]
        if not selected:
            return "I don't have any saved information on that memory page."
        response = f"Memory page {page}. " + "\n".join(selected)
        if start + self.PAGE_SIZE < len(lines):
            response += f"\nMore results: repeat this review with page {page + 1}."
        return response[:self.MAX_RESPONSE]

    def _rows(self, connection, target):
        if target in {"all", "facts", "passive"}:
            result = []
            if target != "passive":
                result.extend(("fact", tuple(row)) for row in connection.execute("SELECT * FROM facts ORDER BY key"))
            if target != "facts":
                result.extend(("passive", tuple(row)) for row in connection.execute("SELECT * FROM passive_memories ORDER BY id"))
            return tuple(result)
        kind, identity = target.split(":", 1)
        if kind == "fact":
            row = connection.execute("SELECT * FROM facts WHERE key = ?", (identity,)).fetchone()
        else:
            row = connection.execute("SELECT * FROM passive_memories WHERE id = ?", (int(identity),)).fetchone()
        return ((kind, tuple(row)),) if row else ()

    def _propose(self, action, target, value=""):
        if self.passive is not None and self.passive.database.path.resolve() != self.database.path.resolve():
            return "Memory changes across different databases are unavailable. Nothing changed."
        with self.database.connect() as db:
            snapshots = self._rows(db, target)
        if action != "correct" and not snapshots:
            return "No matching saved memory was found. Nothing changed."
        if action == "correct":
            if len(value) > 160:
                return "Please use a correction of at most 160 characters. Nothing changed."
            if not allows_storage(target + ": " + value, explicit=True):
                return "Credential secrets cannot be saved. Nothing changed."
            question = (f"Save confirmed {target}: {self._preview(value)}? "
                        "Historical passive observations and their evidence will remain unchanged.")
        elif target in {"all", "facts", "passive"}:
            scope = {"all": "confirmed facts and all passive observations (including expired ones)",
                     "facts": "all confirmed facts", "passive": "all passive observations (including expired ones)"}[target]
            question = f"Delete {scope}, {len(snapshots)} records? Notes, tasks, reminders and conversation history are preserved."
        elif target.startswith("fact:"):
            question = f"Delete only confirmed {target}? Historical passive observations remain unchanged."
        else:
            record = self.passive.get(int(target.split(":")[1]), include_expired=True)
            if record is None:
                return "The selected observation changed. Nothing changed; repeat the command."
            question = f"Delete only {target}? " + self._passive_line(record)
        question += f" Reply Yes or No within {self.timeout_seconds} seconds."
        self.confirmation.clear()
        self.pending = PendingChange(action, target, value, snapshots,
                                     self._now() + timedelta(seconds=self.timeout_seconds), question)
        return question

    def _apply(self, operation):
        try:
            with self.database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if self._now() >= operation.deadline:
                    return "That memory confirmation expired. Nothing changed; repeat the command."
                if self._rows(db, operation.target) != operation.snapshots:
                    return "The reviewed records changed. Nothing was modified; repeat the command."
                if operation.action == "correct":
                    self.facts.set_fact(operation.target.removeprefix("fact:"), operation.value, connection=db)
                    label = operation.target.removeprefix("fact:user.").replace("_", " ")
                    return f"Saved. Confirmed {label} is now {operation.value}. Historical observations remain unchanged."
                if operation.target in {"all", "facts"}:
                    self.facts.clear_facts(connection=db)
                if operation.target in {"all", "passive"}:
                    if self.passive is not None:
                        self.passive.clear(connection=db)
                if operation.target.startswith("fact:"):
                    self.facts.delete_fact(operation.target.removeprefix("fact:"), connection=db)
                if operation.target.startswith("passive:"):
                    self.passive.delete(int(operation.target.split(":")[1]), connection=db)
            scope = {"all": "confirmed facts and passive observations", "facts": "all confirmed facts",
                     "passive": "all passive observations"}.get(operation.target, operation.target)
            return f"Deleted {scope}. Other categories were preserved."
        except (sqlite3.Error, ValueError, OSError, RuntimeError):
            return "The memory change failed and was rolled back. Nothing was modified."

    def handle(self, query):
        reply = re.sub(r"^(?:hey\s+)?nova[,\s]+", "", query.strip(), flags=re.I)
        normalized = " ".join(reply.lower().split()).rstrip(" .!?")
        if self.pending is not None:
            pending = self.pending
            self.clear()
            if self._now() >= pending.deadline:
                if normalized in self.YES | self.NO:
                    return "That memory confirmation expired. Nothing changed; repeat the command."
            elif normalized in self.YES:
                allowed = {"yes", "confirm"} | (
                    {"yes update", "confirm update"} if pending.action == "correct"
                    else {"yes delete", "confirm deletion"})
                if normalized not in allowed:
                    return "That confirmation named a different action. Nothing changed; repeat the command."
                return self._apply(pending)
            elif normalized in self.NO:
                return "Cancelled. No saved records were changed."
            elif re.match(r"^(?:yes|confirm|no|cancel)\b", normalized):
                return "That was not an unambiguous confirmation. Nothing changed; repeat the command."
            # Unrelated requests cancel the operation and continue normal routing.
        command = parse_memory_command(query)
        if command is None:
            if normalized in self.YES | self.NO and self.confirmation.pending is None:
                return "There is no pending memory change. Nothing changed."
            return None
        self.confirmation.clear()
        if command.action == "review":
            return self.review(command.target, command.page)
        if command.action == "show":
            if command.target.startswith("fact:"):
                key = command.target.removeprefix("fact:")
                value = self.facts.get_fact(key)
                if value is not None and contains_secret(key + ": " + value):
                    return f"{command.target}: [credential content omitted]"
                return f"{command.target}: {self._preview(value)}" if value is not None else "No matching saved fact."
            record = self.passive.get(int(command.target.split(":")[1])) if self.passive is not None else None
            if record is None:
                return "No visible passive observation with that ID."
            line = self._passive_line(record)
            if "credential content omitted" not in line:
                line += "; evidence: " + self._preview(record.evidence)
            return line
        if command.action == "bulk":
            return self._propose("delete", command.target)
        if command.action == "delete":
            if command.target.startswith("passive:") and self.passive is None:
                return "Passive memory is unavailable. Nothing changed."
            return self._propose("delete", command.target)
        if command.action == "correct":
            key = self.fact_key(command.target)
            if key is None:
                return "Please specify a supported fact or favorite topic. Nothing changed."
            return self._propose("correct", "fact:" + key, command.value)
        records = self._passive_records()
        if command.action == "replace_preference":
            old = command.target.lower().strip()
            topics = {key for key, value in self.facts.list_facts().items()
                      if key.startswith(("user.favorite_", "user.preferred_")) and value.lower() == old}
            if len(topics) == 1:
                return self._propose("correct", "fact:" + next(iter(topics)), command.value)
            if len(topics) > 1:
                return "Multiple confirmed preferences match. Specify the preference topic; nothing changed."
            activities = []
            for record in records:
                recognized = self.validator._extract_personal_statements(record.evidence)
                if (record.subject.lower() != "speaker" or not any(
                        item["content"].lower() == record.content.lower() for item in recognized)):
                    continue
                match = re.fullmatch(r"favorite (.+?) is (.+)", record.content, re.I)
                if match and match[2].lower() == old:
                    topics.add(self.fact_key("favorite " + match[1]))
                activity = re.fullmatch(r"(?:loves|likes|enjoys) (?:playing )?(.+)", record.content, re.I)
                if activity and activity[1].lower() == old:
                    activities.append(record)
            topics.discard(None)
            if len(topics) == 1:
                return self._propose("correct", "fact:" + next(iter(topics)), command.value)
            if not topics and len(activities) == 1:
                # The new user assertion confirms a preference; it does not
                # identify the historical speaker or change their evidence.
                return self._propose("correct", "fact:user.preferred_activity", command.value)
            return "Please specify the preference topic, for example Update my favorite sport to the new value. Nothing changed."
        if command.action == "delete_label":
            key = self.fact_key(command.target)
            if key and self.facts.get_fact(key) is not None:
                return self._propose("delete", "fact:" + key)
            prefixes = {"user.birthplace": "birthplace is ", "user.job": "works as "}
            prefix = prefixes.get(key)
            if key and key.startswith("user.favorite_"):
                topic = key.removeprefix("user.favorite_").replace("_", " ")
                prefix = f"favorite {topic} is "
                if topic == "language":
                    prefixes[key] = "favorite programming language is "
            matches = [r for r in records if r.subject.lower() == "speaker" and prefix
                       and r.content.lower().startswith((prefix, prefixes.get(key, prefix)))]
        else:
            candidates = PassiveMemoryProcessor(self.passive, llm=object())._extract_personal_statements(command.target)
            contents = {item["content"].lower() for item in candidates}
            matches = [r for r in records if r.subject.lower() == "speaker" and r.content.lower() in contents]
        if len(matches) == 1:
            return self._propose("delete", f"passive:{matches[0].id}")
        if len(matches) > 1:
            ids = ", ".join(f"passive:{r.id}" for r in matches[:5])
            return f"Multiple observations match: {ids}. Specify a typed ID; nothing changed."
        return "No matching saved memory was found. Nothing changed."
