
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FactCommand:
    action: str
    key: str
    label: str
    value: str = ""


class FactParser:
    """Recognize supported personal facts and their questions."""

    FIELDS = {
        "favorite language": "favorite_language",
        "favorite programming language": "favorite_language",
        "favorite food": "favorite_food",
        "favorite color": "favorite_color",
        "hometown": "hometown",
        "city": "city",
        "job": "job",
        "occupation": "job",
        "company": "company",
    }

    QUESTION_ALIASES = {
        "favorite_language": {
            "which programming language is my favorite",
            "what programming language do i like most",
            "which language do i like most",
        },
        "favorite_food": {
            "what food do i like",
            "what food do i like most",
            "which food is my favorite",
            "what do i like to eat most",
        },
        "favorite_color": {
            "which color is my favorite",
            "what color do i like most",
        },
        "company": {
            "where do i work",
            "which company do i work for",
            "who is my employer",
        },
        "city": {
            "which city do i live in",
            "where do i live",
        },
        "hometown": {
            "where am i from",
            "what is my hometown",
        },
        "job": {
            "what do i do for work",
            "what is my occupation",
        },
    }

    def _normalize(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text.rstrip(" .!?")

    def _command(
        self,
        action: str,
        key: str,
        label: str,
        value: str = "",
    ) -> FactCommand:
        return FactCommand(
            action=action,
            key=f"user.{key}",
            label=label,
            value=value,
        )

    def parse(self, query: str) -> FactCommand | None:
        text = query.strip()

        if not text:
            return None

        normalized = self._normalize(text)

        # 1. Recognize questions before updates.
        for label, key in self.FIELDS.items():
            questions = {
                f"what is my {label}",
                f"what's my {label}",
                f"whats my {label}",
                f"tell me my {label}",
                f"do you remember my {label}",
                f"do you know my {label}",
                f"my {label} is what",
                f"my {label} is",
            }

            questions.update(
                self.QUESTION_ALIASES.get(key, set())
            )

            if normalized in questions:
                return self._command(
                    action="get",
                    key=key,
                    label=label,
                )

        # 2. Recognize explicit personal fact declarations.
        match = re.fullmatch(
            r"(?:remember that\s+)?my\s+"
            r"(.+?)\s+is\s+(.+)",
            text.rstrip(" .!"),
            flags=re.IGNORECASE,
        )

        if match:
            label = self._normalize(match.group(1))
            value = match.group(2).strip()

            if label in self.FIELDS:
                if (
                    "?" in text
                    or self._normalize(value) in {
                        "what",
                        "who",
                        "which",
                        "unknown",
                    }
                ):
                    return None

                return self._command(
                    action="set",
                    key=self.FIELDS[label],
                    label=label,
                    value=value,
                )

        # 3. Natural declarations for favorite food.
        food_match = re.fullmatch(
            r"i (?:really )?love eating\s+(.+)",
            text.rstrip(" .!"),
            flags=re.IGNORECASE,
        )

        if food_match:
            return self._command(
                "set",
                "favorite_food",
                "favorite food",
                food_match.group(1).strip(),
            )

        # 4. Natural workplace declarations.
        work_match = re.fullmatch(
            r"i (?:currently )?work (?:at|for)\s+(.+)",
            text.rstrip(" .!"),
            flags=re.IGNORECASE,
        )

        if work_match:
            return self._command(
                "set",
                "company",
                "company",
                work_match.group(1).strip(),
            )

        # 5. Natural city declarations.
        city_match = re.fullmatch(
            r"i (?:currently )?live in\s+(.+)",
            text.rstrip(" .!"),
            flags=re.IGNORECASE,
        )

        if city_match:
            return self._command(
                "set",
                "city",
                "city",
                city_match.group(1).strip(),
            )

        # Natural workplace updates.
        joined_match = re.fullmatch(
            r"i (?:recently |just )?joined\s+"
            r"(.+?)(?:\s+as\s+.+)?",
            text.rstrip(" .!'\""),
            flags=re.IGNORECASE,
        )

        if joined_match and "?" not in text:
            return self._command(
                "set",
                "company",
                "company",
                joined_match.group(1).strip(),
            )

        # Natural relocation updates.
        moved_match = re.fullmatch(
            r"i (?:recently |just )?moved to\s+(.+)",
            text.rstrip(" .!'\""),
            flags=re.IGNORECASE,
        )

        if moved_match and "?" not in text:
            return self._command(
                "set",
                "city",
                "city",
                moved_match.group(1).strip(),
            )

        return None
