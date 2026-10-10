
"""Extract and persist grounded, non-sensitive passive memories."""

import json
import re
from datetime import datetime, timezone
from offline_ai_companion.core.performance import timed
from offline_ai_companion.core.privacy_policy import AUTOMATIC_SENSITIVE_PATTERN, allows_storage

from offline_ai_companion.llm.ollama import OllamaLLM
from offline_ai_companion.config import PASSIVE_MEMORY_LLM_TIMEOUT
from offline_ai_companion.stt.transcript_filter import (
    is_invalid_transcript,
    strip_audio_captions,
)
from offline_ai_companion.memory.passive_grounding import (
    asserted_statement, grounded_event_time, supported_action,
)
from offline_ai_companion.memory.passive_repository import (
    PassiveMemoryRepository,
)


class PassiveMemoryProcessor:
    """Extract grounded memories without trusting unsupported LLM claims."""

    ALLOWED_CATEGORIES = {
        "event",
        "task",
        "preference",
        "fact",
    }

    MAX_TRANSCRIPT_LENGTH = 1500
    MAX_ITEMS = 5
    MAX_CONTENT_LENGTH = 300

    SENSITIVE_PATTERN = AUTOMATIC_SENSITIVE_PATTERN

    FAVORITE_PATTERN = re.compile(
        r"\bmy\s+favou?rite\s+"
        r"(?P<topic>[a-zA-Z][a-zA-Z0-9 _-]{1,70}?)"
        r"\s+is\s+"
        r"(?P<value>[^.!?\n]{1,100})"
        r"[.!?]?",
        flags=re.IGNORECASE,
    )

    def __init__(
        self,
        repository: PassiveMemoryRepository,
        llm=None,
    ) -> None:
        self.repository = repository
        self.llm = llm if llm is not None else OllamaLLM(
            timeout=PASSIVE_MEMORY_LLM_TIMEOUT, max_retries=0,
        )

    @staticmethod
    def evidence_matches(
        evidence: str,
        transcript: str,
    ) -> bool:
        """Allow case and whitespace differences, not paraphrasing."""

        if not isinstance(evidence, str):
            return False

        if not isinstance(transcript, str):
            return False

        def normalize(value: str) -> str:
            return " ".join(value.casefold().split())

        normalized_evidence = normalize(evidence)
        normalized_transcript = normalize(transcript)

        return bool(
            normalized_evidence
            and normalized_evidence in normalized_transcript
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Normalize text for conservative comparison."""

        return " ".join(value.casefold().split())

    def _extract_favorite(
        self,
        transcript: str,
    ) -> list[dict]:
        """Extract an explicitly stated favorite."""

        candidates = []
        for match in self.FAVORITE_PATTERN.finditer(transcript):
            topic = match.group("topic").strip()
            value = match.group("value").strip()
            content = f"Favorite {topic} is {value}"
            evidence = match.group(0).strip()
            if (topic and value and len(content) <= self.MAX_CONTENT_LENGTH
                    and asserted_statement(evidence, transcript) is not None):
                candidates.append({
                    "category": "preference", "subject": "speaker",
                    "content": content, "evidence": evidence, "event_time": None,
                })
        return candidates[:self.MAX_ITEMS]

    PERSONAL_PATTERNS = (
        (
            re.compile(
                r"\bI\s+(?:really\s+)?"
                r"(?P<verb>love|enjoy|like)\s+"
                r"(?P<activity>[a-zA-Z][a-zA-Z0-9 '-]{1,100})"
                r"(?=[.!?\n]|$)",
                re.IGNORECASE,
            ),
            "preference",
        ),
        (
            re.compile(
                r"\bI\s+(?:was\s+)?born\s+in\s+"
                r"(?P<place>[a-zA-Z][a-zA-Z '-]{1,80})"
                r"(?=[.!?\n]|$)",
                re.IGNORECASE,
            ),
            "fact",
        ),
        (
            re.compile(
                r"\bI\s+work\s+as\s+(?:a|an)\s+"
                r"(?P<occupation>[a-zA-Z][a-zA-Z '-]{1,80})"
                r"(?=[.!?\n]|$)",
                re.IGNORECASE,
            ),
            "fact",
        ),
    )

    def _extract_personal_statements(
        self,
        transcript: str,
    ) -> list[dict]:
        """Extract supported, explicitly stated observations."""

        candidates = []
        candidates.extend(self._extract_favorite(transcript))

        for pattern, category in self.PERSONAL_PATTERNS:
            for match in pattern.finditer(transcript):

                # Avoid converting negated or hypothetical
                # statements into affirmative memories.
                prefix = transcript[
                    max(0, match.start() - 40):match.start()
                ]

                if re.search(
                    r"\b(?:if|suppose|imagine|unless)\s*$",
                    prefix,
                    re.IGNORECASE,
                ):
                    continue

                evidence = match.group(0).strip()

                if category == "preference":
                    verb = match.group("verb").casefold()
                    activity = match.group("activity").strip()

                    verb_map = {
                        "love": "Loves",
                        "enjoy": "Enjoys",
                        "like": "Likes",
                    }

                    content = (
                        f"{verb_map[verb]} {activity}"
                    )

                elif "place" in match.groupdict():
                    place = match.group("place").strip()
                    content = f"Birthplace is {place}"

                else:
                    occupation = (
                        match.group("occupation").strip()
                    )
                    content = f"Works as a {occupation}"

                if len(content) > self.MAX_CONTENT_LENGTH:
                    continue

                candidates.append(
                    {
                        "category": category,
                        "subject": "speaker",
                        "content": content,
                        "evidence": evidence,
                        "event_time": None,
                    }
                )

        return [
            item for item in candidates
            if asserted_statement(item["evidence"], transcript) is not None
        ][:self.MAX_ITEMS]

    def _extract_with_llm(
        self,
        transcript: str,
        capture_time_utc: str,
    ) -> list[dict]:
        """Ask the LLM for candidates, not trusted memories."""

        prompt = f"""You extract memories from speech.

Return JSON with exactly one top-level field:
"memories", containing an array.

Each memory must contain:
category, subject, content, evidence, event_time.

Categories:
event, task, preference, fact.

Rules:
- Extract only facts explicitly stated by the speaker.
- Do not add background knowledge.
- Do not infer interests, projects, or intentions.
- Use subject "speaker" when identity is unknown.
- Copy evidence directly from the transcript.
- Do not treat the capture time as an event time.
- Use null event_time when no dated event is stated.
- Do not invent dates.
- Return no more than 5 memories.
- If uncertain, return an empty memories array.
- Return valid JSON only.

Capture time UTC: {capture_time_utc}

TRANSCRIPT START
{transcript}
TRANSCRIPT END

JSON:"""

        try:
            if isinstance(self.llm, OllamaLLM):
                response = self.llm.generate(
                    prompt,
                    temperature=0.0,
                    num_predict=512,
                    json_mode=True,
                )
            else:
                response = self.llm.generate(prompt)

            data = json.loads(response)

        except (RuntimeError, ValueError, TypeError) as exc:
            print(
                "[MEMORY ERROR] Extraction failed: "
                f"{type(exc).__name__}",
                flush=True,
            )
            return []

        if (
            not isinstance(data, dict)
            or set(data) != {"memories"}
            or not isinstance(data["memories"], list)
            or len(data["memories"]) > self.MAX_ITEMS
        ):
            return []

        return data["memories"]

    
    def _candidate_is_grounded(
        self,
        item: dict,
        transcript: str,
        captured_at: datetime | None = None,
    ) -> bool:
        """Validate structure and evidence-backed memory content."""

        if not isinstance(item, dict):
            return False

        required = {
            "category",
            "subject",
            "content",
            "evidence",
            "event_time",
        }

        if set(item) != required:
            return False

        category = item["category"]
        subject = item["subject"]
        content = item["content"]
        evidence = item["evidence"]
        event_time = item["event_time"]

        if not isinstance(category, str) or category not in self.ALLOWED_CATEGORIES:
            return False

        if not all(
            isinstance(value, str) and value.strip()
            for value in (subject, content, evidence)
        ):
            return False

        if (
            len(subject) > 100
            or len(content) > self.MAX_CONTENT_LENGTH
            or len(evidence) > self.MAX_TRANSCRIPT_LENGTH
        ):
            return False

        if subject.strip().casefold() != "speaker":
            return False

        if re.search(r"[\x00-\x1f]", subject + content):
            return False
        if not allows_storage(content + " " + evidence):
            return False

        if not self.evidence_matches(evidence, transcript):
            return False

        statement = asserted_statement(evidence, transcript)
        if statement is None:
            return False
        if category != "event" and event_time is not None:
            return False

        # Deterministically recognized personal observations
        # are allowed only when the exact content and evidence
        # match the recognized statement.
        recognized = self._extract_personal_statements(
            transcript
        )

        for expected in recognized:
            if (
                category == expected["category"]
                and self._normalize_text(content)
                == self._normalize_text(expected["content"])
                and self._normalize_text(evidence)
                == self._normalize_text(expected["evidence"])
                and event_time == expected["event_time"]
            ):
                return True

        if category in {"task", "event"}:
            if not supported_action(category, content, statement):
                return False
            if category == "event":
                if not re.search(
                    r"\b(?:tomorrow|today|yesterday|tonight|next week|next month|"
                    r"meeting|presentation|appointment|scheduled|on monday|"
                    r"on tuesday|on wednesday|on thursday|on friday|on saturday|"
                    r"on sunday)\b|\b\d{4}-\d{2}-\d{2}\b", evidence, re.I,
                ):
                    return False
                return grounded_event_time(evidence, captured_at, event_time)[0]
            return True

        # Arbitrary LLM-generated personal facts remain disabled.
        return False

    @timed("passive_extraction")
    def process(
        self,
        transcript: str,
        captured_at: datetime | None = None,
    ) -> int:
        """Extract, validate, and persist memories."""

        if not isinstance(transcript, str):
            return 0

        transcript = transcript.strip()

        if (
            not transcript
            or len(transcript) > self.MAX_TRANSCRIPT_LENGTH
        ):
            return 0

        # Caption-only transcriptions carry no spoken memory evidence.
        if is_invalid_transcript(transcript):
            return 0
        transcript = strip_audio_captions(transcript)

        if captured_at is None:
            captured_at = datetime.now(timezone.utc)

        if captured_at.utcoffset() is None:
            raise ValueError(
                "Capture timestamp must be timezone-aware."
            )

        # Filter recognized sensitive speech before LLM processing.
        if not allows_storage(transcript):
            return 0

        capture_time_utc = captured_at.astimezone(
            timezone.utc
        ).isoformat()

        # Prefer deterministic extraction for explicit favorites.
        # Extract supported personal observations first.
        candidates = self._extract_personal_statements(
            transcript
        )

        if candidates:
            print(
                "[MEMORY] Deterministic observation extraction.",
                flush=True,
            )
        else:
            candidates = self._extract_with_llm(
                transcript,
                capture_time_utc,
            )

        saved = 0
        rejected = 0
        seen = set()

        for item in candidates:
            if not self._candidate_is_grounded(
                item,
                transcript,
                captured_at,
            ):
                rejected += 1
                continue

            if item["category"] == "event":
                # Normalize only after validation, independently of model output.
                item = dict(item)
                item["event_time"] = grounded_event_time(
                    item["evidence"], captured_at, item["event_time"],
                )[1]

            key = (
                item["category"],
                self._normalize_text(item["subject"]),
                self._normalize_text(item["content"]),
                item["event_time"],
            )

            if key in seen:
                continue

            seen.add(key)

            try:
                inserted = self.repository.add(
                    category=item["category"],
                    subject=item["subject"],
                    content=item["content"],
                    evidence=item["evidence"],
                    event_time=item["event_time"],
                    captured_at=captured_at,
                )

            except (ValueError, TypeError):
                continue

            if inserted:
                saved += 1

        print(
            f"[MEMORY] Candidates={len(candidates)} rejected={rejected} saved={saved}.",
            flush=True,
        )
        if candidates and rejected == len(candidates):
            print(
                "[MEMORY] No supported observation in extraction results; "
                "nothing stored (normal for unrelated speech or STT noise).",
                flush=True,
            )
        return saved
