"""Deterministic recall of evidence-backed observations; no model calls."""

import re
import sqlite3
from dataclasses import dataclass
from offline_ai_companion.core.performance import timed
from offline_ai_companion.core.cancellation import check_cancel
from offline_ai_companion.core.privacy_policy import contains_secret

from offline_ai_companion.memory.fact_parser import FactParser
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.passive_repository import PassiveMemory


@dataclass(frozen=True)
class RecallResult:
    response: str
    memories: tuple[PassiveMemory, ...] = ()


class PassiveMemoryRetriever:
    """Match question relations rather than treating word overlap as truth.

    Source records retain evidence, identity and timestamps for callers.
    Unknown speakers are explicitly attributed, never identified as the user.
    """

    def __init__(self, repository, facts):
        self.repository = repository
        self.facts = facts
        self.parser = FactParser()
        self.validator = PassiveMemoryProcessor(repository, llm=object())

    @staticmethod
    def normalize(text):
        return " ".join(text.casefold().replace("’", "'").split()).rstrip(" .!?")

    def get_fact(self, key):
        if isinstance(getattr(self.facts, "database", None), Database):
            return self.facts.get_fact(key, recall_budget=True)
        return self.facts.get_fact(key)

    @timed("memory_retrieval")
    def recall(self, query: str) -> RecallResult | None:
        question = re.sub(r"^(?:hey\s+)?nova[,\s]+", "", query.strip(), flags=re.I)
        normalized = self.normalize(question)
        fact = self.parser.parse(question)
        topic = None
        relation = None
        key = None
        label = None
        if fact is not None and fact.action == "get":
            key, label = fact.key, fact.label
            if key.startswith("user.favorite_"):
                relation = "favorite"
                topic = key.removeprefix("user.favorite_").replace("_", " ")
            elif key == "user.job":
                relation = "occupation"

        favorite = re.fullmatch(
            r"(?:what(?:'s| is)|tell me|do you (?:know|remember)) my favou?rite (.+)",
            normalized,
        )
        if favorite:
            relation = "favorite"
            topic = favorite[1]
            topic = "language" if topic == "programming language" else topic
            key = "user.favorite_" + topic.replace(" ", "_")
            label = "favorite " + favorite[1]
        if normalized in {"where was i born", "where am i born", "what is my birthplace", "what's my birthplace", "tell me where i was born"}:
            relation, key, label = "birthplace", "user.birthplace", "birthplace"
        if normalized in {"what do i do for work", "what is my occupation", "what's my occupation", "what is my job", "what do i work as"}:
            relation, key, label = "occupation", "user.job", "occupation"
        activity = re.fullmatch(
            r"(?:what|which) (?:(?:sport|sports|activities|activity) )?do i (love|enjoy|like|prefer)(?: (?:doing|playing|to do|to play))?",
            normalized,
        )
        if activity:
            relation = "activity"
            if activity[1] == "prefer":
                key, label = "user.preferred_activity", "preferred activity"
        summary = normalized in {"what do you remember about me", "what do you know about me", "tell me what you remember about me"}

        if key:
            try:
                value = self.get_fact(key)
            except sqlite3.OperationalError:
                return RecallResult("Saved memory retrieval is temporarily unavailable. Please try again.")
            if value is not None and not contains_secret(key + " " + value):
                return RecallResult(f"Your {label} is {value}.")
        if relation is None and not summary:
            return None

        matches = []
        batch = []
        truncated = False
        if self.repository is not None:
            prefixes = {
                "favorite": (f"favorite {('programming language' if topic == 'language' else topic)} is ",
                             f"favorite {topic} is "),
                "birthplace": ("birthplace is ",),
                "occupation": ("works as ",),
                "activity": ("loves ", "enjoys ", "likes ", "prefers "),
            }.get(relation, ())
            try:
                batch = self.repository.recall_candidates(prefixes=prefixes)
            except (ValueError, sqlite3.OperationalError):
                return RecallResult("Saved memory retrieval is temporarily unavailable. Please try again.")
            truncated = len(batch) > 32
            batch = batch[:32]
        for memory in batch:
            check_cancel()
            if memory.subject.strip().casefold() != "speaker":
                continue
            if (contains_secret(memory.evidence + " " + memory.content)
                    or self.validator.SENSITIVE_PATTERN.search(memory.evidence + " " + memory.content)):
                continue
            # Reconstruct from the complete evidence, not from lexical similarity.
            candidates = self.validator._extract_personal_statements(memory.evidence)
            if not any(
                item["category"] == memory.category
                and self.normalize(item["content"]) == self.normalize(memory.content)
                and memory.event_time is None
                for item in candidates
            ):
                continue
            content = self.normalize(memory.content)
            relevant = summary
            if relation == "favorite":
                stored = re.fullmatch(r"favorite (.+?) is (.+)", content)
                if stored:
                    stored_topic = "language" if stored[1] == "programming language" else stored[1]
                    relevant = stored_topic == topic
            elif relation == "birthplace":
                relevant = content.startswith("birthplace is ")
            elif relation == "occupation":
                relevant = content.startswith("works as ")
            elif relation == "activity":
                verb = {"love": "loves", "enjoy": "enjoys", "like": "likes", "prefer": "prefers"}[activity[1]]
                relevant = content.startswith(verb + " ")
                if "sport" in normalized or "playing" in normalized or "to play" in normalized:
                    relevant = content.startswith(verb + " playing ")
            if relevant:
                # Re-read selected records so deletion/expiry during selection
                # cannot be reconstructed from an in-process candidate snapshot.
                try:
                    if self.repository.get(memory.id, recall_budget=True) == memory:
                        matches.append(memory)
                except sqlite3.OperationalError:
                    return RecallResult("Saved memory retrieval is temporarily unavailable. Please try again.")

        if summary:
            facts = self.facts.list_facts()
            lines = [f"Confirmed {key.removeprefix('user.').replace('_', ' ')}: {value}." for key, value in facts.items()]
            lines.extend(f"Recorded speaker observation: {m.content} (captured {m.captured_at})." for m in matches[:10])
            response = " ".join(lines) if lines else "I don't have any relevant saved information yet."
        elif not matches:
            response = f"I don't have your {label} saved yet." if label else "I don't have a relevant saved observation for that question."
        elif relation != "activity" and (truncated or len({self.normalize(m.content).replace('programming language', 'language') for m in matches}) > 1):
            response = "I have conflicting saved observations, so I'm not sure. " + " ".join(
                f"Speaker observation: {m.content} (captured {m.captured_at})." for m in matches[:5]
            )
        else:
            if relation == "favorite":
                value = re.fullmatch(r"Favorite (.+?) is (.+)", matches[0].content, re.I)[2]
                response = f"The saved preference is {value} for {label}."
            else:
                contents = list(dict.fromkeys(m.content for m in matches))
                response = "The saved observation says: " + "; ".join(contents[:5]) + "."
            response += " This was recorded from an unidentified speaker; I can't verify it was you."
        if truncated:
            response += " More observations exist; this bounded result may be incomplete. Review saved memories before drawing a conclusion."
        return RecallResult(response, tuple(matches))
