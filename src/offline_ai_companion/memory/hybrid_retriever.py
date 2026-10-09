"""Local concept ranking over bounded SQLite candidates, never generated answers.

This small semantic lexicon normalizes concepts across questions and evidence.
It needs no embeddings, downloads, HTTP, or additional runtime dependencies.
Unknown concepts fail closed. Similarity ranks already grounded candidates only.
"""
import math
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime

from offline_ai_companion.core.cancellation import check_cancel
from offline_ai_companion.core.privacy_policy import allows_storage, contains_secret
from offline_ai_companion.memory.passive_grounding import asserted_statement, grounded_event_time
from offline_ai_companion.memory.passive_retriever import PassiveMemoryRetriever, RecallResult


GROUPS = {
    "work": "work works working profession professional occupation job employment career living",
    "food": "food foods dish dishes cuisine meal meals eating",
    "favorite": "favorite favourite favorites favourites preferred most",
    "hobby": "hobby hobbies leisure pastime pastimes activity activities recreation recreational",
    "birthplace": "birthplace born birth",
    "event": "trip trips outing outings outdoor outdoors went visited journey journeys",
    "enjoy": "enjoy enjoys enjoying love loves loving like likes liking",
    "language": "language languages",
    "color": "color colour colors colours",
}
CONCEPTS = {word: concept for concept, words in GROUPS.items() for word in words.split()}
STOP = set("what which do did does i my me you your is are was were for a an the about of to tell remember know can doing recent recently last this it have saved information and one".split())


def concepts(text):
    text = re.sub(r"\bbirth place\b", "birthplace", text.casefold())
    return Counter(CONCEPTS.get(word, word) for word in re.findall(r"[a-z]+", text.casefold())
                   if word not in STOP)


class LocalConceptRanker:
    def score(self, query, evidence):
        left, right = concepts(query), concepts(evidence)
        product = sum(value * right.get(key, 0) for key, value in left.items())
        norm = math.sqrt(sum(v*v for v in left.values()) * sum(v*v for v in right.values()))
        return product / norm if norm else 0.0


class HybridMemoryRetriever:
    MAX_CANDIDATES = 32
    MAX_RESULTS = 3

    def __init__(self, repository, facts, ranker=None, budget_seconds=0.25, clock=time.monotonic):
        if not 0 < budget_seconds <= 1:
            raise ValueError("Retrieval budget must be between zero and one second.")
        self.repository, self.facts = repository, facts
        self.exact = PassiveMemoryRetriever(repository, facts)
        self.ranker = ranker or LocalConceptRanker()
        self.budget, self.clock = budget_seconds, clock

    def recall(self, query):
        check_cancel()
        exact = self.exact.recall(query)
        if exact is not None:
            return exact
        text = re.sub(r"^(?:hey\s+)?nova[,\s]+", "", query.strip(), flags=re.I)
        # Assertions and commands retain their normal routing. A personal recall
        # question must contain first-person attribution and a question opener.
        if not re.match(r"^(?:what|which|where|when|do you|can you|tell me)\b", text, re.I):
            return None
        if not re.search(r"\b(?:my|me|i)\b", text, re.I):
            return None
        words = concepts(text)
        # A shared concept cannot answer a different relation (work address is
        # not occupation; least-liked food is not a favorite). Fail closed when
        # additional qualifiers would require unimplemented entailment.
        related = {"work", "hobby", "favorite", "food", "birthplace", "enjoy"}
        if ("work" in words or "birthplace" in words) and any(w not in related for w in words):
            return RecallResult("I don't have enough supported saved information to answer that question.")
        if "food" in words and "favorite" not in words:
            return RecallResult("I don't have enough supported saved information to answer that question.")
        past_event = bool("event" in words and "enjoy" not in words) or bool(re.search(r"\bdid i\b", text, re.I))
        questions = []
        if "favorite" in words:
            # General topic normalization, not individual stored values.
            topics = [w for w in words if w not in {"favorite", "enjoy", "hobby", "work", "event", "food"}]
            topic = "food" if "food" in words else " ".join(topics[:3])
            if topic and re.fullmatch(r"[a-z ]{1,70}", topic):
                questions.append("What is my favorite " + topic + "?")
        if "work" in words:
            questions.append("What do I do for work?")
        if "birthplace" in words:
            questions.append("Where was I born?")
        deadline = self.clock() + self.budget
        results = []
        for question in questions[:3]:
            check_cancel()
            if self.clock() >= deadline:
                break
            answer = self.exact.recall(question)
            if answer is not None:
                results.append(answer)
        if ("hobby" in words or ("enjoy" in words and not questions)) and not past_event:
            confirmed = []
            for key in ("user.hobbies", "user.hobby", "user.preferred_activity"):
                try:
                    value = self.exact.get_fact(key)
                except sqlite3.OperationalError:
                    return RecallResult("Saved memory retrieval is temporarily unavailable. Please try again.")
                if isinstance(value, str) and not contains_secret(key + " " + value):
                    confirmed.append(f"Confirmed {key.removeprefix('user.').replace('_', ' ')}: {value}.")
            results.append(RecallResult(" ".join(confirmed)) if confirmed else
                           self._observations(text, ("loves ", "enjoys ", "likes "), (), deadline))
        elif past_event:
            terms = tuple(w for w in words if w not in CONCEPTS.values() and len(w) > 2
                          and w not in {"weekend", "sunday", "saturday", "yesterday", "today"})[:8]
            results.append(self._observations(text, (), terms, deadline))
        if not results:
            # Unrecognized personal questions must not generate invented facts.
            # Only intercept explicit recall language; ordinary conversation stays intact.
            if re.search(r"\bremember\b", text, re.I):
                return RecallResult("I don't have enough supported saved information to answer that question.")
            return None
        return RecallResult(" ".join(r.response for r in results)[:1800],
                            tuple(m for r in results for m in r.memories))

    def _grounded(self, memory):
        if memory.subject.strip().casefold() != "speaker" or not allows_storage(memory.content + " " + memory.evidence):
            return False
        try:
            captured = datetime.fromisoformat(memory.captured_at)
            if captured.utcoffset() is None:
                return False
        except ValueError:
            return False
        item = {key: getattr(memory, key) for key in ("category", "subject", "content", "evidence", "event_time")}
        if self.exact.validator._candidate_is_grounded(item, memory.evidence, captured):
            return True
        # Retrieval-only support for verbatim historical observations. This does
        # not enable a new automatic extraction path or resolve weekday dates.
        if memory.category != "event" or asserted_statement(memory.evidence, memory.evidence) is None:
            return False
        evidence = self.exact.normalize(memory.evidence)
        content = self.exact.normalize(memory.content)
        return bool(re.fullmatch(r"i (?:went|visited|played|attended|travelled|traveled|walked|ran|cycled|hiked|swam) .+", evidence)
                    and content in {evidence, evidence.removeprefix("i ")}
                    and grounded_event_time(memory.evidence, captured, memory.event_time)[0])

    def _observations(self, query, prefixes, terms, deadline):
        if self.repository is None or self.clock() >= deadline:
            return RecallResult("I don't have enough supported saved information to answer that question.")
        check_cancel()
        try:
            rows = self.repository.recall_candidates(prefixes, tuple(t for t in terms if t.isalpha()),
                                                     budget_seconds=min(0.2, self.budget),
                                                     category="event" if not prefixes else None)
        except (sqlite3.OperationalError, ValueError):
            return RecallResult("Saved memory retrieval is temporarily unavailable. Please try again.")
        ranked = []
        for memory in rows[:self.MAX_CANDIDATES]:
            check_cancel()
            if self.clock() >= deadline:
                break
            if not self._grounded(memory):
                continue
            if prefixes:
                specific = [word for word in concepts(query)
                            if word not in CONCEPTS.values() and word not in {"work", "weekend"}]
                if specific and not all(re.search(r"\b" + re.escape(word) + r"\b", memory.evidence, re.I) for word in specific):
                    continue
                if "outdoor" in query.casefold() and not re.search(
                    r"\b(?:outdoor|hiking|walking|running|cycling|camping|climbing|kayaking|skiing)\b", memory.evidence, re.I
                ):
                    continue
            if not prefixes:
                if memory.category != "event":
                    continue
                if terms and not all(re.search(r"\b" + re.escape(term) + r"\b", memory.evidence, re.I) for term in terms):
                    continue
                if "outdoor" in query.casefold() and not re.search(
                    r"\b(?:outdoor|hiking|walking|running|cycling|camping|climbing|kayaking|skiing)\b", memory.evidence, re.I
                ):
                    continue
            # Require explicitly requested temporal evidence. Weekends are only
            # matched to literal Saturday/Sunday; no calendar dates are inferred.
            lower = query.casefold()
            if "weekend" in lower and not re.search(r"\b(?:last weekend|last saturday|last sunday)\b", memory.evidence, re.I):
                continue
            if "yesterday" in lower and "yesterday" not in memory.evidence.casefold():
                continue
            try:
                score = self.ranker.score(query, memory.evidence)
            except (RuntimeError, TimeoutError, OSError):
                score = LocalConceptRanker().score(query, memory.evidence)
            # Recheck budget after ranking; never use a late result.
            if self.clock() >= deadline:
                score = LocalConceptRanker().score(query, memory.evidence)
            if prefixes and "hobby" in concepts(query):
                score = max(score, 0.1)
            if isinstance(score, (int, float)) and math.isfinite(score) and score > 0:
                ranked.append((score, memory))
        ranked.sort(key=lambda item: (-item[0], -item[1].id))
        selected = []
        for _, memory in ranked[:self.MAX_RESULTS]:
            # No cache: deletion/expiration changes are honored at answer time.
            try:
                current = self.repository.get(memory.id, recall_budget=True)
            except sqlite3.OperationalError:
                return RecallResult("Saved memory retrieval is temporarily unavailable. Please try again.")
            if current == memory and self._grounded(current):
                selected.append(current)
        if not selected:
            return RecallResult("I don't have enough supported saved information to answer that question.")
        response = " ".join(f"Speaker observation passive:{m.id}: {m.content} (captured {m.captured_at})." for m in selected)
        response += " The speaker is unidentified; I can't verify it was you. These observations are not confirmed personal facts."
        if len(rows) > self.MAX_CANDIDATES:
            response += " More observations exist; this result is incomplete."
        return RecallResult(response, tuple(selected))
